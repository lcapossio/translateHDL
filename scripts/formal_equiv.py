#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Leonardo Capossio - bard0 design
# Author: Leonardo Capossio - bard0 design - hello@bard0.com
"""Layer 2 — formal sequential equivalence checking (the primary proof).

For each synthesizable module listed under ``formal.modules`` (per parameter
set), prove that the golden and candidate implementations are sequentially
equivalent. A PASS here is a *proof* (within the engine's induction bound), not
a sample of behavior — this is what turns "strong parity" into "certainty".

Engines
-------
* ``yosys`` (default): built-in flow — read both sides into one session as
  modules ``gold``/``gate``, ``equiv_make``, then ``equiv_simple`` +
  ``equiv_induct``, then ``equiv_status -assert``. No extra dependency beyond
  Yosys (+ GHDL when a side is VHDL).
* ``eqy``: emit an ``.eqy`` config and run YosysHQ's eqy, which partitions large
  modules for scalable SEC. Use for big modules where induction is slow.

Bringing each side into Yosys goes through the language registry: Verilog reads
natively; VHDL is converted to a Verilog netlist via ``ghdl --synth``.

Interface note: ``equiv_make`` matches ports by name. When the two sides share
port names (faithful leaf translations, and Verilog<->VHDL without records) this
is automatic. For record-flattened interfaces whose names differ, supply a
per-module ``wrapper`` source (a tiny Verilog module that adapts names) in the
golden side, or switch that module to the ``eqy`` engine with a ``[match]``
section. translateHDL deliberately favors faithful, name-preserving translation
precisely so this layer stays push-button.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from _common import (FAIL, PASS, SKIP, LayerResult, ToolMissing, cli_main, have,
                     load_manifest, manifest_root, resolve_sources, run_capture,
                     run_output, tool)
import languages


def _read_cmds(root: Path, side: dict, top: str, params: dict, tmp: Path,
               wrapper: str | None) -> list[str]:
    lang = languages.get(side["language"])
    sources = resolve_sources(root, side["sources"])
    if wrapper:
        sources = resolve_sources(root, [wrapper]) + sources
    std = str(side.get("std", "08" if side["language"] == "vhdl" else "2001"))
    return lang.yosys_read(root, top, sources, params=params, std=std, workdir=tmp)


def _yosys_equiv_script(gold_cmds: list[str], gate_cmds: list[str], top: str,
                        induct_depth: int) -> str:
    return "\n".join([
        "design -reset",
        *gold_cmds,
        f"hierarchy -top {top}",
        "proc", "flatten", "memory_collect", "opt -full",
        f"rename {top} gold",
        "design -stash gold",

        "design -reset",
        *gate_cmds,
        f"hierarchy -top {top}",
        "proc", "flatten", "memory_collect", "opt -full",
        f"rename {top} gate",
        "design -stash gate",

        "design -reset",
        "design -copy-from gold -as gold gold",
        "design -copy-from gate -as gate gate",
        "equiv_make gold gate equiv",
        "hierarchy -top equiv",
        "clean -purge",
        "opt -full",
        "equiv_simple",
        f"equiv_induct -seq {induct_depth}",
        "equiv_status",
    ]) + "\n"


def _prove_yosys(root: Path, man: dict, module: str, params: dict, tmp: Path,
                 wrapper: str | None, induct_depth: int) -> tuple[str, str]:
    gold = _read_cmds(root, man["golden"], module, params, tmp, wrapper)
    gate = _read_cmds(root, man["candidate"], module, params, tmp, None)
    script = _yosys_equiv_script(gold, gate, module, induct_depth)
    # Decide on OUTPUT, not exit code: equiv_status prints a definitive summary
    # and some yosys builds (yowasp) do not propagate a non-zero exit on assert
    # failure, so an exit-code-only check could mistake "not equivalent" for PASS.
    _, out = run_output([tool("yosys"), "-"], root, input_text=script)
    if "Equivalence successfully proven" in out:
        return PASS, "equiv_induct + equiv_status: equivalence successfully proven"
    m = re.search(r"Found a total of (\d+) unproven", out) or re.search(r"(\d+) are unproven", out)
    if m:
        return FAIL, f"equiv_status: {m.group(1)} unproven $equiv cell(s) — designs differ"
    tail = next((ln for ln in reversed(out.splitlines()) if "ERROR" in ln), "")
    return FAIL, f"equivalence not established{(' — ' + tail) if tail else ''}"


def _prove_eqy(root: Path, man: dict, module: str, params: dict, tmp: Path) -> tuple[str, str]:
    if not have("eqy"):
        raise ToolMissing(["eqy"])
    # Minimal eqy config: gold/gate are yosys scripts produced via the registry.
    gold = "\n".join(_read_cmds(root, man["golden"], module, params, tmp, None))
    gate = "\n".join(_read_cmds(root, man["candidate"], module, params, tmp, None))
    cfg = tmp / f"{module}.eqy"
    cfg.write_text(
        f"[gold]\n{gold}\nprep -top {module}\n\n"
        f"[gate]\n{gate}\nprep -top {module}\n\n"
        f"[strategy simple]\nuse sby\ndepth 10\nengine smtbmc\n",
        encoding="utf-8",
    )
    try:
        out = run_capture([tool("eqy"), "-f", str(cfg)], root)
    except Exception as exc:  # noqa: BLE001
        return FAIL, f"eqy failed: {exc}"
    return (PASS, "eqy: equivalent") if "Equivalence successfully proven" in out \
        else (FAIL, "eqy: not proven")


def prove(manifest_path: str) -> LayerResult:
    man = load_manifest(manifest_path)
    root = manifest_root(manifest_path)
    res = LayerResult("L2 formal", PASS)

    spec = man.get("formal")
    if not spec or not spec.get("enabled", True):
        res.detail = "no formal section; skipped"
        return res

    engine = spec.get("engine", "yosys")
    induct_depth = int(spec.get("induct_depth", 20))
    # Tool availability up front so we SKIP cleanly rather than half-run.
    needs = {"yosys"}
    if "vhdl" in (man["golden"]["language"].lower(), man["candidate"]["language"].lower()):
        needs.add("ghdl")
    if engine == "eqy":
        needs.add("eqy")
    missing = [t for t in needs if not have(t)]
    if missing:
        raise ToolMissing(missing)

    with tempfile.TemporaryDirectory(prefix=".formal_", dir=root) as tmpname:
        tmp = Path(tmpname)
        for mod in spec["modules"]:
            name = mod["name"]
            wrapper = mod.get("wrapper")
            param_sets = mod.get("param_sets") or [{}]
            for params in param_sets:
                tag = name + ("[" + ",".join(f"{k}={v}" for k, v in params.items()) + "]"
                              if params else "")
                if engine == "eqy":
                    status, detail = _prove_eqy(root, man, name, params, tmp)
                else:
                    status, detail = _prove_yosys(root, man, name, params, tmp, wrapper, induct_depth)
                res.add(tag, status, detail)

    res.status = res.rollup()
    res.detail = f"engine={engine}, {len(res.items)} module/config proofs"
    return res


if __name__ == "__main__":
    cli_main(prove)
