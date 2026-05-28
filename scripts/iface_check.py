#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Leonardo Capossio - bard0 design
# Author: Leonardo Capossio - bard0 design - hello@bard0.com
"""Layer 0 — interface equivalence.

A fast structural pre-check: before spending time on proofs, confirm the two
tops agree on ports (names, directions, and — where parseable — widths) and
parameters. This catches the cheap mistakes (a flipped direction, a dropped
port, a width typo) in seconds.

Scope honesty: Verilog ANSI port lists are parsed fully. VHDL entity ports are
parsed for name + direction; VHDL *record* ports (as used in spacewire_light)
cannot be width-resolved by regex, so for mixed VHDL/Verilog designs the
manifest supplies ``interface.port_map`` (golden -> candidate, with record
fields expanded). Where no map is given for a mixed design, this layer reports
what it can and defers the authoritative check to Layer 2 (formal SEC), which
fails outright if ports are wired wrong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from _common import (FAIL, PASS, SKIP, LayerResult, cli_main, load_manifest,
                     manifest_root, resolve_sources)


@dataclass(frozen=True)
class Port:
    name: str
    direction: str          # in | out | inout
    width: int | None       # bit count if determinable, else None
    typ: str = ""


def _norm_dir(direction: str) -> str:
    # Reconcile VHDL (in/out/inout) and Verilog (input/output/inout) vocab.
    return {"in": "input", "out": "output"}.get(direction, direction)


def _strip_comments(text: str) -> str:
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"--[^\n]*", "", text)        # VHDL line comments
    return text


def _verilog_width(rng: str) -> int | None:
    # rng like "[7:0]" or "[WIDTH-1:0]"; only resolve pure-integer ranges.
    m = re.search(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", rng)
    if not m:
        return None
    hi, lo = int(m.group(1)), int(m.group(2))
    return abs(hi - lo) + 1


def parse_verilog(text: str, top: str) -> tuple[dict[str, Port], dict[str, str]]:
    text = _strip_comments(text)
    m = re.search(rf"\bmodule\s+{re.escape(top)}\b(.*?)\bendmodule\b", text, re.S)
    if not m:
        raise ValueError(f"verilog module '{top}' not found")
    body = m.group(1)

    params: dict[str, str] = {}
    pm = re.search(r"#\s*\((.*?)\)\s*\(", body, re.S)
    if pm:
        for pmatch in re.finditer(r"parameter\b[^,;=]*?(\w+)\s*=\s*([^,)\n]+)", pm.group(1)):
            params[pmatch.group(1)] = pmatch.group(2).strip()

    ports: dict[str, Port] = {}
    for d in re.finditer(
        r"\b(input|output|inout)\b\s*(?:wire|reg|logic)?\s*(signed)?\s*(\[[^\]]*\])?\s*([\w\s,]+?)\s*(?=;|,|\)|input|output|inout|$)",
        body,
    ):
        direction, _signed, rng, names = d.group(1), d.group(2), d.group(3) or "", d.group(4)
        width = _verilog_width(rng) if rng else 1
        for name in (n.strip() for n in names.split(",")):
            if name and re.fullmatch(r"\w+", name):
                ports[name] = Port(name, direction, width)
    return ports, params


def parse_vhdl(text: str, top: str) -> tuple[dict[str, Port], dict[str, str]]:
    text = _strip_comments(text)
    m = re.search(rf"\bentity\s+{re.escape(top)}\s+is\b(.*?)\bend\b", text, re.S | re.I)
    if not m:
        raise ValueError(f"vhdl entity '{top}' not found")
    body = m.group(1)

    params: dict[str, str] = {}
    gm = re.search(r"\bgeneric\s*\((.*?)\)\s*;", body, re.S | re.I)
    if gm:
        for line in gm.group(1).split(";"):
            gmatch = re.match(r"\s*(\w+)\s*:", line)
            if gmatch:
                params[gmatch.group(1)] = ""

    ports: dict[str, Port] = {}
    pm = re.search(r"\bport\s*\((.*)\)\s*;", body, re.S | re.I)
    if pm:
        depth_text = pm.group(1)
        for decl in re.split(r";", depth_text):
            dmatch = re.match(r"\s*([\w\s,]+?)\s*:\s*(in|out|inout)\b\s*(.*)", decl, re.S | re.I)
            if not dmatch:
                continue
            names, direction, typ = dmatch.group(1), dmatch.group(2).lower(), dmatch.group(3).strip()
            width = None
            wm = re.search(r"\(\s*(\d+)\s+downto\s+(\d+)\s*\)", typ, re.I)
            if wm:
                width = abs(int(wm.group(1)) - int(wm.group(2))) + 1
            elif re.search(r"\bstd_u?logic\b", typ, re.I) and "(" not in typ:
                width = 1
            for name in (n.strip() for n in names.split(",")):
                if name:
                    ports[name] = Port(name, direction, width, typ.split("(")[0].strip())
    return ports, params


PARSERS = {"verilog": parse_verilog, "vhdl": parse_vhdl}


def _read_top(root: Path, side: dict) -> tuple[dict[str, Port], dict[str, str], str]:
    lang = side["language"].lower()
    top = side["top"]
    sources = resolve_sources(root, side["sources"])
    blob = "\n".join(Path(s).read_text(encoding="utf-8", errors="ignore") for s in sources)
    ports, params = PARSERS[lang](blob, top)
    return ports, params, lang


def check(manifest_path: str) -> LayerResult:
    man = load_manifest(manifest_path)
    root = manifest_root(manifest_path)
    res = LayerResult("L0 interface", PASS)

    gp, gpar, glang = _read_top(root, man["golden"])
    cp, cpar, clang = _read_top(root, man["candidate"])

    iface = man.get("interface", {})
    port_map: dict[str, str] = iface.get("port_map", {})  # golden -> candidate

    if glang == clang or not port_map:
        # Direct name-based comparison.
        missing = sorted(set(gp) - set(cp))
        extra = sorted(set(cp) - set(gp))
        if glang != clang and (missing or extra):
            # Mixed languages w/o a map and names diverge: defer to Layer 2.
            res.status = SKIP
            res.detail = (f"mixed-language ports differ and no interface.port_map given; "
                          f"deferring to Layer 2 formal SEC "
                          f"({len(missing)} golden-only, {len(extra)} candidate-only)")
            return res
        for name in missing:
            res.add(name, FAIL, "present in golden, missing in candidate")
        for name in extra:
            res.add(name, FAIL, "present in candidate, missing in golden")
        for name in sorted(set(gp) & set(cp)):
            g, c = gp[name], cp[name]
            if _norm_dir(g.direction) != _norm_dir(c.direction):
                res.add(name, FAIL, f"direction {g.direction} vs {c.direction}")
            elif g.width is not None and c.width is not None and g.width != c.width:
                res.add(name, FAIL, f"width {g.width} vs {c.width}")
            else:
                res.add(name, PASS, f"{_norm_dir(g.direction)} [{g.width}]")
    else:
        # Mixed languages with an explicit map (records expanded on candidate).
        for gname, cname in port_map.items():
            if gname not in gp:
                res.add(gname, FAIL, "mapped golden port not found")
            elif cname not in cp:
                res.add(f"{gname}->{cname}", FAIL, "mapped candidate port not found")
            else:
                g, c = gp[gname], cp[cname]
                if _norm_dir(g.direction) != _norm_dir(c.direction):
                    res.add(f"{gname}->{cname}", FAIL, f"direction {g.direction}/{c.direction}")
                else:
                    res.add(f"{gname}->{cname}", PASS, _norm_dir(c.direction))

    # Parameters: names should correspond (values/types may legitimately differ,
    # e.g. VHDL real generics -> precomputed Verilog integers).
    if not (glang != clang and not port_map):
        gset, cset = set(gpar), set(cpar)
        if gset and cset and gset != cset:
            res.add("parameters", SKIP,
                    f"golden={sorted(gset)} candidate={sorted(cset)} (review: may be intentional)")

    res.status = res.rollup()
    res.detail = f"{glang}:{man['golden']['top']} vs {clang}:{man['candidate']['top']}"
    return res


if __name__ == "__main__":
    cli_main(check)
