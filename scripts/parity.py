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

from _common import BOUNDED, EXIT, FAIL, PASS, SKIP, LayerResult, ToolMissing  # noqa: E402
import manifest as manifest_mod  # noqa: E402
import iface_check  # noqa: E402
import lint  # noqa: E402
import formal_equiv  # noqa: E402
import compare_traces  # noqa: E402
import compare_waveforms  # noqa: E402
import synth_compare  # noqa: E402

LAYERS = [
    ("MAN", "manifest", manifest_mod.run),
    ("L0", "interface", iface_check.check),
    ("L1", "lint", lint.lint),
    ("L2", "formal SEC", formal_equiv.prove),
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
        print("usage: python scripts/parity.py <manifest.yml> [--only L0,L2] [--strict]",
              file=sys.stderr)
        return 2
    manifest_path = args[0]
    strict = "--strict" in args
    only = None
    for a in args:
        if a.startswith("--only"):
            only = set((a.split("=", 1)[1] if "=" in a else args[args.index(a) + 1]).split(","))

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
    any_fail = any(r.rollup() == FAIL for _, r in results)
    any_bounded = any(r.rollup() == BOUNDED for _, r in results)
    any_skip = any(r.rollup() == SKIP for _, r in results)
    for tag, r in results:
        print(f"  {tag:<4} {r.rollup():<7} {r.layer}")

    formal = next((r for t, r in results if t == "L2"), None)
    if formal is not None and formal.rollup() == PASS and any(s == PASS for _, s, _ in formal.items):
        print("\n  Layer 2 formally proved the listed modules equivalent.")

    if any_fail:
        print("\nRESULT: FAIL - a divergence was found. Translation is NOT equivalent.")
        return EXIT[FAIL]
    if any_bounded:
        if strict:
            print("\nRESULT: FAIL (--strict) - equivalence is only bounded-proven, "
                  "not fully proven. Use a stronger engine (eqy) to close it.")
            return EXIT[FAIL]
        print("\nRESULT: BOUNDED - no divergence found and bounded-equivalent, but a "
              "module is not fully proven (see L2 detail). Stronger engine needed for full proof.")
        return EXIT[BOUNDED]
    if any_skip:
        if strict:
            print("\nRESULT: FAIL (--strict) - a layer was skipped (missing tool); "
                  "proof incomplete.")
            return EXIT[FAIL]
        print("\nRESULT: INCOMPLETE - no divergence found, but some layers were skipped "
              "(missing tools). Install the toolchain or run in CI for a full proof.")
        return EXIT[SKIP]
    print("\nRESULT: PASS - all executed parity layers agree; "
          "formally-proven modules are equivalent.")
    return EXIT[PASS]


if __name__ == "__main__":
    raise SystemExit(main())
