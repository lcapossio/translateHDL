# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Leonardo Capossio - bard0 design
# Author: Leonardo Capossio - bard0 design - hello@bard0.com
"""Self-tests for the translateHDL parity ladder.

The point of these tests is to prove the *harness* works: on an equivalent
translation no layer may FAIL, and on a deliberately broken one the comparison
layers must FAIL (never silently PASS). Layers whose tools are absent return
SKIP, so assertions are written as "must not FAIL" / "must not PASS" to stay
green on a machine that only has Icarus, while still being strict in CI where
the full toolchain is installed.

Run: pytest tests/  (from the repo root)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _common import FAIL, PASS, SKIP  # noqa: E402
import compare_traces  # noqa: E402
import compare_waveforms  # noqa: E402
import iface_check  # noqa: E402
import manifest as manifest_mod  # noqa: E402
import formal_equiv  # noqa: E402
import parity  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "counter"
GOOD = str(FIX / "parity_good.yml")
BAD = str(FIX / "parity_bad.yml")


def _status(result):
    return result.rollup()


def _run(fn, manifest):
    # Mirror the orchestrator: a missing tool becomes SKIP, not an exception.
    return parity._run_layer(fn, manifest, fn.__name__).rollup()


def test_manifest_valid():
    assert _status(manifest_mod.run(GOOD)) == PASS


def test_interface_matches():
    assert _status(iface_check.check(GOOD)) == PASS


def test_good_trace_passes():
    assert _status(compare_traces.compare(GOOD)) == PASS


def test_bad_trace_fails():
    assert _status(compare_traces.compare(BAD)) == FAIL


def test_good_waveform_passes():
    assert _status(compare_waveforms.compare(GOOD)) == PASS


def test_bad_waveform_fails():
    assert _status(compare_waveforms.compare(BAD)) == FAIL


def test_good_formal_never_fails():
    # PASS if yosys present and proof closes; SKIP if yosys absent. Never FAIL
    # on an equivalent design.
    assert _run(formal_equiv.prove, GOOD) in (PASS, SKIP)


def test_bad_formal_never_passes():
    # FAIL if yosys present (bug caught); SKIP if absent. Must never PASS a
    # broken design.
    assert _run(formal_equiv.prove, BAD) in (FAIL, SKIP)


def test_orchestrator_rejects_broken_fixture():
    # End-to-end: the orchestrator must exit 1 (FAIL) on the broken fixture
    # (the trace/waveform layers catch the divergence even without yosys).
    import subprocess
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "parity.py"), BAD],
                       capture_output=True, text=True)
    assert r.returncode == 1, f"expected FAIL exit 1, got {r.returncode}\n{r.stdout}\n{r.stderr}"


def _parity(*extra):
    import subprocess
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "parity.py"), *extra],
                          capture_output=True, text=True).returncode


def test_expect_flag_matches_and_mismatches():
    # --expect asserts the verdict: exit 0 on match, 1 on mismatch. Use L3a only
    # so the result is deterministic with just Icarus present.
    assert _parity(BAD, "--only", "L3a", "--expect", "fail") == 0
    assert _parity(BAD, "--only", "L3a", "--expect", "pass") == 1
    assert _parity(GOOD, "--only", "L3a", "--expect", "pass") == 0


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__)), "-v"]))
