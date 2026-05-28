#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Leonardo Capossio - bard0 design
# Author: Leonardo Capossio - bard0 design - hello@bard0.com
"""Layer 1 — lint both designs clean.

Generalized from spacewire_light's scripts/lint_hdl.py. Each side is analyzed /
elaborated with its native toolchain; for Verilog an optional Yosys structural
pass (``hierarchy -check; proc; check -assert``) catches issues iverilog misses,
such as multi-driven nets. Missing tools yield SKIP, never a false PASS.
"""

from __future__ import annotations

from pathlib import Path

from _common import (FAIL, PASS, SKIP, LayerResult, ToolMissing, cli_main,
                     have, load_manifest, manifest_root, resolve_sources, run, tool)
import languages


def _yosys_check(root: Path, top: str, sources: list[str], params: dict | None) -> None:
    cmds = ["read_verilog " + " ".join(sources)]
    chparam = "".join(f" -chparam {k} {int(v)}" for k, v in (params or {}).items())
    cmds += [f"hierarchy -check -top {top}{chparam}", "proc", "check -assert"]
    run([tool("yosys"), "-q", "-"], root, input_text="\n".join(cmds) + "\n")


def _lint_side(root: Path, side: dict, res: LayerResult, label: str) -> None:
    lang = languages.get(side["language"])
    sources = resolve_sources(root, side["sources"])
    std = str(side.get("std", "08" if side["language"] == "vhdl" else "2001"))
    try:
        lang.lint(root, sources, std=std)
        res.add(f"{label}:{side['language']} analyze", PASS)
    except ToolMissing as exc:
        res.add(f"{label}:{side['language']} analyze", SKIP, str(exc))
        return

    if side["language"] == "verilog":
        if have("yosys"):
            try:
                _yosys_check(root, side["top"], sources, side.get("params"))
                res.add(f"{label}: yosys structural check", PASS)
            except Exception as exc:  # noqa: BLE001 - report any structural failure
                res.add(f"{label}: yosys structural check", FAIL, str(exc))
        else:
            res.add(f"{label}: yosys structural check", SKIP, "yosys not installed")


def lint(manifest_path: str) -> LayerResult:
    man = load_manifest(manifest_path)
    root = manifest_root(manifest_path)
    res = LayerResult("L1 lint", PASS)
    _lint_side(root, man["golden"], res, "golden")
    _lint_side(root, man["candidate"], res, "candidate")
    res.status = res.rollup()
    return res


if __name__ == "__main__":
    cli_main(lint)
