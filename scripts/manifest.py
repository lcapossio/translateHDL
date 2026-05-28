#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Leonardo Capossio - bard0 design
# Author: Leonardo Capossio - bard0 design - hello@bard0.com
"""Parity-manifest schema validation + testbench-isomorphism check.

Generalized from spacewire_light's scripts/check_spwlink_parity_manifest.py.
Two jobs:

1. ``validate`` — structural sanity: required sections present, languages known,
   every referenced source file exists.
2. testbench isomorphism — for each entry under ``simulation.testbenches``,
   confirm the declared ``stimulus`` markers appear in BOTH the golden and the
   candidate bench source(s). This is what keeps a "stimulus-isomorphic" claim
   honest: if someone deletes a test case from one side, this fails.
"""

from __future__ import annotations

from pathlib import Path

from _common import (FAIL, PASS, LayerResult, cli_main, load_manifest,
                     manifest_root, resolve_sources)
import languages

REQUIRED_SIDE_KEYS = {"language", "top", "sources"}


def validate(man: dict, root: Path) -> list[tuple[str, str, str]]:
    issues: list[tuple[str, str, str]] = []
    for side in ("golden", "candidate"):
        if side not in man:
            issues.append((side, FAIL, "missing required top-level section"))
            continue
        missing = REQUIRED_SIDE_KEYS - set(man[side])
        if missing:
            issues.append((side, FAIL, f"missing keys: {sorted(missing)}"))
            continue
        if man[side]["language"].lower() not in languages.REGISTRY:
            issues.append((side, FAIL, f"unknown language '{man[side]['language']}'"))
        try:
            resolve_sources(root, man[side]["sources"])
            issues.append((f"{side} sources", PASS, f"{len(man[side]['sources'])} files"))
        except FileNotFoundError as exc:
            issues.append((f"{side} sources", FAIL, str(exc)))
    return issues


def _bench_text(root: Path, spec: dict) -> str:
    return "\n".join(Path(s).read_text(encoding="utf-8", errors="ignore")
                     for s in resolve_sources(root, spec["sources"]))


def check_testbenches(man: dict, root: Path) -> list[tuple[str, str, str]]:
    issues: list[tuple[str, str, str]] = []
    tbs = (man.get("simulation") or {}).get("testbenches") or []
    for tb in tbs:
        name = tb.get("name", "<unnamed>")
        markers = tb.get("stimulus", [])
        golden_txt = _bench_text(root, tb["golden"]) if "golden" in tb else ""
        cand_txt = _bench_text(root, tb["candidate"]) if "candidate" in tb else ""
        for marker in markers:
            g = marker in golden_txt
            c = marker in cand_txt
            if g and c:
                issues.append((f"{name}:{marker}", PASS, "present both sides"))
            else:
                where = "golden" if not g else "candidate"
                issues.append((f"{name}:{marker}", FAIL, f"missing in {where}"))
    return issues


def run(manifest_path: str) -> LayerResult:
    man = load_manifest(manifest_path)
    root = manifest_root(manifest_path)
    res = LayerResult("manifest", PASS)
    for name, status, detail in validate(man, root) + check_testbenches(man, root):
        res.add(name, status, detail)
    res.status = res.rollup()
    return res


if __name__ == "__main__":
    cli_main(run)
