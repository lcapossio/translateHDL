#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
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

from pathlib import Path

from _common import (FAIL, PASS, LayerResult, ToolMissing, cli_main,
                     load_manifest, manifest_root, resolve_sources)
import languages


def _trace_lines(stdout: str, marker: str) -> list[str]:
    return [ln.strip() for ln in stdout.splitlines() if ln.startswith(marker)]


def _run_side(root: Path, side: dict, marker: str) -> list[str]:
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
    try:
        golden = _run_side(root, spec["golden"], marker)
        candidate = _run_side(root, spec["candidate"], marker)
    except ToolMissing:
        raise  # surfaced as SKIP by cli_main / orchestrator

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
