#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
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

import languages
from _common import FAIL, PASS, LayerResult, cli_main, load_manifest, manifest_root, resolve_sources

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
    # cocotb_bench is optional; if set under simulation.{trace,waveform}, the
    # referenced .py must exist. Drives both sides identically by construction
    # (no testbench-isomorphism check needed because there is only one bench).
    for sect in ("trace", "waveform"):
        bench = ((man.get("simulation") or {}).get(sect) or {}).get("cocotb_bench")
        if bench:
            p = (root / bench).resolve()
            tag = f"simulation.{sect}.cocotb_bench"
            if p.exists():
                issues.append((tag, PASS, str(p.name)))
            else:
                issues.append((tag, FAIL, f"file not found: {p}"))
    issues += validate_properties(man, root)
    return issues


def validate_properties(man: dict, root: Path) -> list[tuple[str, str, str]]:
    """Schema-check the optional Layer 2b `properties` section.

    Stricter than the other sections on purpose. L2b's failure mode is proving
    NOTHING and calling it success, so the schema forces the user to state what
    they expect to be proved (`expect_asserts`) and to attest to the clocking
    model the engine actually supports (`single_clock`). Both are load-bearing,
    not paperwork: properties.py refuses to report a proof without them.
    """
    spec = man.get("properties")
    if not spec or not spec.get("enabled", True):
        return []
    issues: list[tuple[str, str, str]] = []

    mode = str(spec.get("mode", "prove")).lower()
    if mode not in ("prove", "bmc"):
        hint = " (cover is not supported in this version)" if mode == "cover" else ""
        issues.append(("properties.mode", FAIL, f"must be prove|bmc, got '{mode}'{hint}"))

    engine = str(spec.get("engine", "yosys")).lower()
    if engine != "yosys":
        hint = (" (sby is not wired up in this version - it has no executed test, "
                "and an untested backend cannot be trusted with a verdict)"
                if engine == "sby" else "")
        issues.append(("properties.engine", FAIL, f"must be yosys, got '{engine}'{hint}"))

    # Yosys' `sat` advances one global time step and `async2sync` carries its own
    # timing assumption, so a multi-clock or async design can be "proved" under a
    # transition model that never explores the real interleavings. Require the
    # user to attest to the model rather than silently assuming it.
    if spec.get("single_clock") is not True:
        issues.append(("properties.single_clock", FAIL,
                       "must be `single_clock: true` - this engine models one global "
                       "clock step, so multi-clock / dual-edge / async designs are out "
                       "of scope and would risk a false PASS"))

    for key in ("depth", "timeout_s"):
        if key in spec:
            try:
                if float(spec[key]) <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                issues.append((f"properties.{key}", FAIL,
                               f"must be a positive number, got {spec[key]!r}"))

    mods = spec.get("modules")
    if not mods:
        issues.append(("properties.modules", FAIL, "at least one module is required"))
        return issues

    for mod in mods:
        if not isinstance(mod, dict) or not mod.get("name"):
            issues.append(("properties.modules", FAIL,
                           f"each module needs a `name`, got {mod!r}"))
            continue
        name = mod["name"]
        for side in mod.get("sides") or spec.get("sides") or ("golden", "candidate"):
            if side not in ("golden", "candidate"):
                issues.append((f"properties:{name}", FAIL,
                               f"unknown side '{side}' (use golden/candidate)"))
                continue
            tag = f"properties:{name}[{side}]"

            # The vacuity gate. Without a declared count, a run that reads none
            # of the properties proves an empty conjunction and reports success.
            expect = mod.get(f"{side}_expect_asserts", mod.get("expect_asserts",
                                                               spec.get("expect_asserts")))
            try:
                if int(expect) < 1:
                    raise ValueError
            except (TypeError, ValueError):
                issues.append((tag, FAIL,
                               "needs `expect_asserts: <n>` (n >= 1): the number of assert "
                               "cells this side must contribute. The layer compares it "
                               "against the prepared design and FAILs on a mismatch, which "
                               "is what stops a silently-unread property file from passing"))
                continue

            files = mod.get(f"{side}_props") or []
            try:
                resolve_sources(root, files)
                issues.append((tag, PASS,
                               f"{len(files)} property file(s), expect {int(expect)} assert(s)"
                               if files else
                               f"inline properties in RTL, expect {int(expect)} assert(s)"))
            except FileNotFoundError as exc:
                issues.append((tag, FAIL, str(exc)))
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
