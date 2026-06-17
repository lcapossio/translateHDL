#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Leonardo Capossio - bard0 design
# Author: Leonardo Capossio - bard0 design - hello@bard0.com
"""Layer 3b — normalized VCD waveform comparison.

Generalized from spacewire_light's scripts/compare_vhdl_verilog_waveforms.py.
The hard part — reconciling GHDL vs Icarus timescales, differing signal-path
spellings, and bit-vector formatting — is kept verbatim; sources, tops, the
signal map and the comparison window come from the manifest.

manifest:
  simulation:
    waveform:
      golden:    {language: vhdl,    top: ..., sources: [...]}
      candidate: {language: verilog, top: ..., sources: [...]}
      start_ps: 25000              # ignore power-on settling before this
      signals:
        clk: ["tb.sysclk", "tb.clk"]   # [golden_path, candidate_path]
        ...
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from _common import (FAIL, PASS, LayerResult, ToolMissing, cli_main,
                     load_manifest, manifest_root, resolve_sources)
import languages

_HERE = Path(__file__).resolve().parent
_COCOTB_RUNNER = _HERE / "_cocotb_run.py"


def _cocotb_interp() -> str:
    # See compare_traces._cocotb_interp for the rationale (libpython/libm ABI).
    return os.environ.get("COCOTB_PYTHON") or sys.executable


def timescale_to_ps(text: str) -> float:
    match = re.search(r"\$timescale\s+(\d+)\s*([fpnum]?s)\s+\$end", text, re.S)
    if not match:
        raise ValueError(f"unsupported VCD timescale: {text!r}")
    value, unit = int(match.group(1)), match.group(2)
    factors = {"fs": 0.001, "ps": 1.0, "ns": 1000.0, "us": 1_000_000.0,
               "ms": 1_000_000_000.0, "s": 1_000_000_000_000.0}
    return value * factors[unit]


def canonical(value: str) -> str:
    value = value.lower()
    if value in {"x", "z", "u", "w", "-"}:
        return "x"
    if value.startswith("b"):
        bits = "".join("x" if b not in "01" else b for b in value[1:])
        return bits.lstrip("0") or "0"
    return value


def parse_vcd(path: Path, wanted: dict[str, str]) -> dict[str, list[tuple[int, str]]]:
    lines = path.read_text().splitlines()
    scale_ps = None
    scopes: list[str] = []
    code_to_names: dict[str, list[str]] = {}
    start_idx = 0
    in_defs = True

    for idx, line in enumerate(lines):
        s = line.strip()
        if s.startswith("$timescale"):
            text = s
            j = idx + 1
            while "$end" not in text and j < len(lines):
                text += " " + lines[j].strip()
                j += 1
            scale_ps = timescale_to_ps(text)
        elif s.startswith("$scope"):
            scopes.append(s.split()[2])
        elif s.startswith("$upscope"):
            scopes.pop()
        elif s.startswith("$var"):
            parts = s.split()
            code = parts[3]
            ref = " ".join(parts[4:-1])
            code_to_names.setdefault(code, []).append(".".join([*scopes, ref]))
        elif s.startswith("$enddefinitions"):
            start_idx = idx + 1
            in_defs = False
            break

    if in_defs or scale_ps is None:
        raise ValueError(f"{path}: incomplete VCD header")

    def _strip_range(n: str) -> str:
        return re.sub(r"\s*\[\d+:\d+\]\s*$", "", n).strip()

    codes: dict[str, str] = {}
    for name, full in wanted.items():
        want = _strip_range(full)
        for code, names in code_to_names.items():
            if any(full == n or want == _strip_range(n) for n in names):
                codes[name] = code
                break
        else:
            avail = "\n  ".join(sorted(n for ns in code_to_names.values() for n in ns))
            raise ValueError(f"{path}: missing signal {full}\nAvailable:\n  {avail}")

    target = {code: name for name, code in codes.items()}
    state = {name: "x" for name in wanted}
    samples: dict[str, list[tuple[int, str]]] = {name: [] for name in wanted}
    now = 0

    def emit(name: str, value: str) -> None:
        v = canonical(value)
        if state[name] != v:
            state[name] = v
            samples[name].append((now, v))

    for line in lines[start_idx:]:
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            now = int(round(int(s[1:]) * scale_ps))
        elif s[0] in "01xzXZ":
            if s[1:] in target:
                emit(target[s[1:]], s[0])
        elif s[0] == "b":
            value, code = s.split(None, 1)
            if code in target:
                emit(target[code], value)
    return samples


def value_at(changes: list[tuple[int, str]], t: int) -> str:
    value = "x"
    for ct, cv in changes:
        if ct > t:
            break
        value = cv
    return value


def _build(root: Path, side: dict, vcd: Path,
           cocotb_bench: Path | None = None, build_dir: Path | None = None,
           side_label: str = "") -> None:
    if cocotb_bench is not None:
        lang = side["language"]
        sim = "ghdl" if lang == "vhdl" else "icarus"
        std = str(side.get("std", "08" if lang == "vhdl" else "2001"))
        sources = [str(p) for p in resolve_sources(root, side["sources"])]
        build_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            _cocotb_interp(), str(_COCOTB_RUNNER),
            "--sim", sim, "--lang", lang, "--top", side["top"],
            "--bench", str(cocotb_bench), "--std", std,
            "--build-dir", str(build_dir),
            "--vcd", str(vcd),
            "--sources", *sources,
        ]
        print("+ " + " ".join(cmd), flush=True)
        proc = subprocess.run(cmd, cwd=str(root))
        if proc.returncode == 77:
            raise ToolMissing("cocotb")
        if proc.returncode != 0:
            raise RuntimeError(f"cocotb {side_label} side exited {proc.returncode}")
        return
    lang_obj = languages.get(side["language"])
    sources = resolve_sources(root, side["sources"])
    std = str(side.get("std", "08" if side["language"] == "vhdl" else "2001"))
    lang_obj.simulate_vcd(root, side["top"], sources, vcd, std=std)


def compare(manifest_path: str) -> LayerResult:
    man = load_manifest(manifest_path)
    root = manifest_root(manifest_path)
    res = LayerResult("L3b waveform", PASS)

    spec = (man.get("simulation") or {}).get("waveform")
    if not spec:
        res.detail = "no simulation.waveform section; nothing to compare"
        return res

    signals: dict[str, list[str]] = spec["signals"]
    start_ps = int(spec.get("start_ps", 0))

    cocotb_bench: Path | None = None
    if spec.get("cocotb_bench"):
        cocotb_bench = (root / spec["cocotb_bench"]).resolve()
        if not cocotb_bench.exists():
            raise FileNotFoundError(f"cocotb_bench not found: {cocotb_bench}")

    tmp = root / ".wavecmp_tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(exist_ok=True)
    try:
        gvcd, cvcd = tmp / "golden.vcd", tmp / "candidate.vcd"
        try:
            _build(root, spec["golden"], gvcd, cocotb_bench=cocotb_bench,
                   build_dir=(tmp / "cocotb_golden") if cocotb_bench else None,
                   side_label="golden")
            _build(root, spec["candidate"], cvcd, cocotb_bench=cocotb_bench,
                   build_dir=(tmp / "cocotb_candidate") if cocotb_bench else None,
                   side_label="candidate")
        except ToolMissing:
            raise

        golden = parse_vcd(gvcd, {n: p[0] for n, p in signals.items()})
        candidate = parse_vcd(cvcd, {n: p[1] for n, p in signals.items()})

        end_ps = min(
            max(t for ch in golden.values() for t, _ in ch),
            max(t for ch in candidate.values() for t, _ in ch),
        )
        for name in signals:
            times = sorted({t for ch in (golden[name], candidate[name])
                            for t, _ in ch if start_ps <= t <= end_ps})
            diff = next((t for t in times
                         if value_at(golden[name], t) != value_at(candidate[name], t)), None)
            if diff is None:
                res.add(name, PASS)
            else:
                res.add(name, FAIL, f"@{diff}ps golden={value_at(golden[name], diff)} "
                                    f"candidate={value_at(candidate[name], diff)}")
        res.detail = f"{len(signals)} signals, {start_ps}..{end_ps} ps"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    res.status = res.rollup()
    return res


if __name__ == "__main__":
    cli_main(compare)
