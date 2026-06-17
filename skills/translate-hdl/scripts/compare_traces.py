#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Leonardo Capossio - bard0 design
# Author: Leonardo Capossio - bard0 design - hello@bard0.com
"""Layer 3a — deterministic trace comparison.

Generalized from spacewire_light's scripts/compare_vhdl_verilog_traces.py.
Both sides run a matched, deterministic testbench that prints lines beginning
with a marker (default ``TRACE ``). Determinism (e.g. seeded LFSR stimulus)
makes the two marker streams byte-identical iff the designs behave identically
at the observed points. This covers behavior that formal SEC cannot (testbench
sequencing, non-synthesizable stimulus).
"""

from __future__ import annotations

import os
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
    """Interpreter used to run _cocotb_run.py.

    Cocotb's VPI/VHPI shim loads libpython at runtime; if a simulator (e.g.
    OSS CAD Suite Icarus / GHDL) is built against its own bundled libpython +
    libm, calling it through a SYSTEM Python whose libpython.so needs a newer
    GLIBC than the bundled libm provides causes a silent VPI load failure
    (zero TRACE lines, no error from cocotb). Export ``COCOTB_PYTHON`` to the
    toolchain's bundled python (e.g. ``$OSS_CAD_SUITE/py3bin/python3``) to
    pin the cocotb subprocess to the matching ABI. Defaults to the
    orchestrator's interpreter.
    """
    return os.environ.get("COCOTB_PYTHON") or sys.executable


def _trace_lines(stdout: str, marker: str) -> list[str]:
    return [ln.strip() for ln in stdout.splitlines() if ln.startswith(marker)]


def _run_cocotb(root: Path, side: dict, bench: Path, build_dir: Path,
                side_label: str) -> str:
    """Drive one side through cocotb via the _cocotb_run.py subprocess helper."""
    lang = side["language"]
    sim = "ghdl" if lang == "vhdl" else "icarus"
    std = str(side.get("std", "08" if lang == "vhdl" else "2001"))
    sources = [str(p) for p in resolve_sources(root, side["sources"])]
    build_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        _cocotb_interp(), str(_COCOTB_RUNNER),
        "--sim", sim, "--lang", lang, "--top", side["top"],
        "--bench", str(bench), "--std", std,
        "--build-dir", str(build_dir),
        "--sources", *sources,
    ]
    print("+ " + " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode == 77:
        raise ToolMissing("cocotb")
    if proc.returncode != 0:
        raise RuntimeError(f"cocotb {side_label} side exited {proc.returncode}")
    return proc.stdout


def _run_side(root: Path, side: dict, marker: str,
              cocotb_bench: Path | None = None,
              build_dir: Path | None = None,
              side_label: str = "") -> list[str]:
    if cocotb_bench is not None:
        out = _run_cocotb(root, side, cocotb_bench, build_dir, side_label)
        return _trace_lines(out, marker)
    lang = languages.get(side["language"])
    sources = resolve_sources(root, side["sources"])
    std = str(side.get("std", "08" if side["language"] == "vhdl" else "2001"))
    out = lang.simulate(root, side["top"], sources, std=std)
    return _trace_lines(out, marker)


def compare(manifest_path: str) -> LayerResult:
    man = load_manifest(manifest_path)
    root = manifest_root(manifest_path)
    res = LayerResult("L3a trace", PASS)

    spec = (man.get("simulation") or {}).get("trace")
    if not spec:
        res.detail = "no simulation.trace section; nothing to compare"
        return res

    marker = spec.get("marker", "TRACE ")
    cocotb_bench: Path | None = None
    tmp: Path | None = None
    if spec.get("cocotb_bench"):
        cocotb_bench = (root / spec["cocotb_bench"]).resolve()
        if not cocotb_bench.exists():
            raise FileNotFoundError(f"cocotb_bench not found: {cocotb_bench}")
        tmp = root / ".cocotb_trace_tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)
    try:
        golden = _run_side(root, spec["golden"], marker,
                           cocotb_bench=cocotb_bench,
                           build_dir=(tmp / "golden") if tmp else None,
                           side_label="golden")
        candidate = _run_side(root, spec["candidate"], marker,
                              cocotb_bench=cocotb_bench,
                              build_dir=(tmp / "candidate") if tmp else None,
                              side_label="candidate")
    except ToolMissing:
        raise  # surfaced as SKIP by cli_main / orchestrator
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)

    print("\n-- golden trace --\n" + "\n".join(golden))
    print("\n-- candidate trace --\n" + "\n".join(candidate))

    if not golden:
        res.add("trace", FAIL, f"golden produced no '{marker.strip()}' lines")
    elif golden == candidate:
        res.add("trace", PASS, f"{len(golden)} marker lines identical")
    else:
        first = next((i for i, (a, b) in enumerate(zip(golden, candidate)) if a != b),
                     min(len(golden), len(candidate)))
        res.add("trace", FAIL, f"diverge at line {first}: "
                               f"{golden[first:first+1]} vs {candidate[first:first+1]}; "
                               f"len {len(golden)} vs {len(candidate)}")
    res.status = res.rollup()
    return res


if __name__ == "__main__":
    cli_main(compare)
