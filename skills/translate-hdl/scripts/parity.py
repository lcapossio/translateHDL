#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Leonardo Capossio - bard0 design
# Author: Leonardo Capossio - bard0 design - hello@bard0.com
"""Parity ladder orchestrator.

Runs every layer against a manifest and prints a single verdict table.

    python scripts/parity.py <manifest.yml> [--only L0,L2] [--strict]

Exit codes:
    0  every executed layer PASSed and nothing equivalence-relevant was skipped
    1  at least one layer FAILed (a real divergence)
    77 no FAILs, but a tool was missing so the proof is incomplete (SKIP)

``--strict`` turns any SKIP into a failure (use in CI where all tools must be
present, so a missing tool can never silently weaken the guarantee).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import compare_traces
import compare_waveforms
import formal_equiv
import iface_check
import lint
import manifest as manifest_mod
import properties
import synth_compare
from _common import BOUNDED, EXIT, FAIL, N_A, PASS, SKIP, LayerResult, ToolMissing

# Tags whose result is a CONTRACT claim about one side, not an equivalence
# claim about the pair. Kept out of the equivalence verdict below.
PROPERTY_TAGS = {"L2b"}

LAYERS = [
    ("MAN", "manifest", manifest_mod.run),
    ("L0", "interface", iface_check.check),
    ("L1", "lint", lint.lint),
    ("L2", "formal SEC", formal_equiv.prove),
    ("L2b", "properties", properties.check),
    ("L3a", "trace", compare_traces.compare),
    ("L3b", "waveform", compare_waveforms.compare),
    ("L4", "synth", synth_compare.compare),
]


def _run_layer(fn, manifest_path: str, name: str) -> LayerResult:
    try:
        return fn(manifest_path)
    except ToolMissing as exc:
        r = LayerResult(name, SKIP, str(exc))
        return r
    except Exception as exc:  # noqa: BLE001 - a crashing layer is a failure, not a pass
        return LayerResult(name, FAIL, f"layer crashed: {exc}")


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("usage: python scripts/parity.py <manifest.yml> [--only L0,L2] [--strict] "
              "[--expect pass|fail|bounded|incomplete]", file=sys.stderr)
        return 2
    manifest_path = args[0]
    strict = "--strict" in args
    only = None
    expect = None
    for i, a in enumerate(args):
        if a.startswith("--only"):
            only = set((a.split("=", 1)[1] if "=" in a else args[i + 1]).split(","))
        elif a == "--expect":
            expect = args[i + 1].lower()
        elif a.startswith("--expect="):
            expect = a.split("=", 1)[1].lower()
    valid = {"pass", "fail", "bounded", "incomplete"}
    if expect is not None and expect not in valid:
        print(f"--expect must be one of {sorted(valid)}", file=sys.stderr)
        return 2

    results: list[tuple[str, LayerResult]] = []
    for tag, name, fn in LAYERS:
        if only and tag not in only:
            continue
        print(f"\n{'=' * 70}\n== {tag} {name}\n{'=' * 70}")
        res = _run_layer(fn, manifest_path, name)
        status = res.rollup()
        results.append((tag, res))
        print(f"\n[{tag}] {status}: {res.detail}".rstrip())
        for iname, istatus, idetail in res.items:
            print(f"    {istatus:<5} {iname} {('- ' + idetail) if idetail else ''}")

    print(f"\n{'=' * 70}\n== VERDICT\n{'=' * 70}")
    # L2b answers a DIFFERENT question from every other layer. The rest of
    # the ladder asks "is the candidate the same as the golden?"; L2b asks
    # "does this side satisfy its stated contract?" - both sides can satisfy
    # a weak contract and still differ, and the golden can break a contract
    # while being perfectly equivalent to the candidate. Different claim, so
    # it is excluded from the equivalence verdict and reported separately.
    equiv = [(tag, r) for tag, r in results if tag not in PROPERTY_TAGS]
    props = next((r for tag, r in results if tag == "L2b"), None)

    any_fail = any(r.rollup() == FAIL for _, r in equiv)
    any_bounded = any(r.rollup() == BOUNDED for _, r in equiv)
    any_skip = any(r.rollup() == SKIP for _, r in equiv)
    # N_A carries no evidence: a run of nothing but N_A layers is not a pass.
    any_evidence = any(r.rollup() in (PASS, BOUNDED) for _, r in equiv)
    for tag, r in results:
        print(f"  {tag:<4} {r.rollup():<7} {r.layer}")

    formal = next((r for t, r in results if t == "L2"), None)
    if formal is not None and formal.rollup() == PASS and any(s == PASS for _, s, _ in formal.items):
        print("\n  Layer 2 formally proved the listed modules equivalent.")

    if props is not None and props.rollup() == PASS and props.items:
        print("  Layer 2b proved the declared properties for the listed sides "
              "(a contract result about each side, NOT an equivalence result).")

    # Natural verdict (independent of --strict / --expect).
    if any_fail:
        verdict, msg = "fail", "a divergence was found. Translation is NOT equivalent."
    elif any_bounded:
        verdict, msg = "bounded", ("no divergence found and bounded-equivalent, but a module "
                                   "is not fully proven (see L2 detail). Stronger engine needed.")
    elif any_skip:
        verdict, msg = "incomplete", ("no divergence found, but some layers were skipped "
                                      "(missing tools). Run in CI for a full proof.")
    elif not equiv:
        # e.g. `--only L2b`: a property-only run makes no equivalence claim at
        # all, and must not borrow the word "pass" from a layer that never ran.
        verdict, msg = "incomplete", ("no equivalence layer was run (property layers only). "
                                      "This run makes no equivalence claim.")
    elif not any_evidence:
        verdict, msg = "incomplete", ("no equivalence layer produced any evidence - "
                                      "nothing was configured to run. Not a proof.")
    elif formal is None or formal.rollup() == N_A:
        # Every executed layer agrees, but the layer that produces the PROOF
        # never ran. Simulation agreement is evidence, not equivalence - saying
        # "proven equivalent" here would be the claim this project exists to
        # avoid making.
        verdict, msg = "pass", ("all executed layers agree, but NO formal proof ran "
                                "(L2 not configured) - simulation evidence only.")
    else:
        verdict, msg = "pass", "all executed parity layers agree; proven modules are equivalent."

    # A property failure fails the run in its OWN words; it never rewrites the
    # equivalence sentence above into "translation is NOT equivalent".
    if props is not None and props.rollup() == FAIL:
        print(f"\n  EQUIVALENCE: {verdict.upper()} - {msg}")
        verdict, msg = "fail", ("a stated property was violated (see L2b). That localizes "
                                "a broken contract to one side; it is not by itself an "
                                "equivalence divergence.")
    print(f"\nRESULT: {verdict.upper()} - {msg}")

    # --strict refuses a properties layer that was configured but could not run,
    # or that produced only bounded evidence. This runs BEFORE --expect: the
    # expected verdict of a property-only run is "incomplete" either way, so a
    # later check would let `--expect incomplete` accept a layer that proved
    # nothing - exactly the false pass this project exists to prevent.
    if strict and props is not None and props.rollup() in (SKIP, BOUNDED):
        print(f"RESULT: FAIL (--strict) - L2b {props.rollup()}: {props.detail}")
        return EXIT[FAIL]

    # --expect: assert the verdict (lets CI demand e.g. a BOUNDED module, or a
    # deliberately property-only run, without shell exit-code logic). Takes
    # precedence over --strict for the OVERALL verdict only.
    if expect is not None:
        ok = verdict == expect
        print(f"EXPECT {expect.upper()}: {'OK' if ok else 'MISMATCH (got ' + verdict.upper() + ')'}")
        return EXIT[PASS] if ok else EXIT[FAIL]

    # --strict turns BOUNDED / INCOMPLETE into failures.
    if strict and verdict in ("bounded", "incomplete"):
        print("RESULT: FAIL (--strict) - not a full proof.")
        return EXIT[FAIL]
    return {"fail": EXIT[FAIL], "bounded": EXIT[BOUNDED],
            "incomplete": EXIT[SKIP], "pass": EXIT[PASS]}[verdict]


if __name__ == "__main__":
    raise SystemExit(main())
