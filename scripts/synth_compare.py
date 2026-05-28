#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Leonardo Capossio - bard0 design
# Author: Leonardo Capossio - bard0 design - hello@bard0.com
"""Layer 4 — synthesis resource sanity.

Generalized from spacewire_light's scripts/synth_resource_compare.py. This is
NOT an equivalence proof — Layer 2 is. It synthesizes both sides with Yosys and
compares cell/wire/memory counts per parameter set, flagging gross structural
divergence and documenting area parity. A delta beyond ``synth.tolerance_pct``
(default 5%) is reported as FAIL; otherwise PASS with the table.
"""

from __future__ import annotations

import json
from pathlib import Path

from _common import (FAIL, PASS, LayerResult, ToolMissing, cli_main, have,
                     load_manifest, manifest_root, resolve_sources, run_capture, tool)
import languages


def _stats(root: Path, side: dict, params: dict, tmp: Path, tag: str) -> dict:
    lang = languages.get(side["language"])
    sources = resolve_sources(root, side["sources"])
    std = str(side.get("std", "08" if side["language"] == "vhdl" else "2001"))
    read_cmds = lang.yosys_read(root, side["top"], sources, params=params, std=std, workdir=tmp)
    stats_path = tmp / f"{tag}.json"
    script = "\n".join([*read_cmds, "proc", "memory", "opt",
                        f"tee -o {stats_path.as_posix()} stat -json"])
    run_capture([tool("yosys"), "-q", "-"], root, input_text=script + "\n")
    data = json.loads(stats_path.read_text(encoding="utf-8"))
    top = next(iter(data.get("modules", {}).values()), {})
    return {"cells": top.get("num_cells", 0), "wires": top.get("num_wires", 0),
            "wire_bits": top.get("num_wire_bits", 0),
            "memories": top.get("num_memories", 0),
            "memory_bits": top.get("num_memory_bits", 0)}


def compare(manifest_path: str) -> LayerResult:
    man = load_manifest(manifest_path)
    root = manifest_root(manifest_path)
    res = LayerResult("L4 synth", PASS)

    spec = man.get("synth")
    if not spec or not spec.get("enabled", True):
        res.detail = "no synth section; skipped"
        return res
    if not have("yosys"):
        raise ToolMissing(["yosys"])

    tol = float(spec.get("tolerance_pct", 5.0))
    param_sets = spec.get("param_sets") or [{}]
    import tempfile
    with tempfile.TemporaryDirectory(prefix=".synthcmp_", dir=root) as tmpname:
        tmp = Path(tmpname)
        rows = []
        for i, params in enumerate(param_sets):
            g = _stats(root, man["golden"], params, tmp, f"g{i}")
            c = _stats(root, man["candidate"], params, tmp, f"c{i}")
            ref = g["cells"] or 1
            delta = 100.0 * (c["cells"] - g["cells"]) / ref
            label = ",".join(f"{k}={v}" for k, v in params.items()) or "default"
            rows.append((label, g["cells"], c["cells"], delta))
            status = FAIL if abs(delta) > tol else PASS
            res.add(label, status, f"cells golden={g['cells']} candidate={c['cells']} "
                                   f"({delta:+.1f}%)")

    print("\nSynthesis resource comparison (cells)")
    print(f"{'config':<28} {'golden':>8} {'candidate':>10} {'delta':>8}")
    for label, gc, cc, d in rows:
        print(f"{label:<28} {gc:>8} {cc:>10} {d:>+7.1f}%")
    res.detail = f"tolerance {tol}%"
    res.status = res.rollup()
    return res


if __name__ == "__main__":
    cli_main(compare)
