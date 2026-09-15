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

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import compare_traces  # noqa: E402
import compare_waveforms  # noqa: E402
import formal_equiv  # noqa: E402
import iface_check  # noqa: E402
import manifest as manifest_mod  # noqa: E402
import parity  # noqa: E402
import properties  # noqa: E402
import synth_compare  # noqa: E402
from _common import FAIL, N_A, PASS, SKIP  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "counter"
GOOD = str(FIX / "parity_good.yml")
BAD = str(FIX / "parity_bad.yml")
COCOTB = str(FIX / "parity_cocotb.yml")


def _status(result):
    return result.rollup()


def _mutated(mutate):
    """Write GOOD with its `properties` section mutated; return the path.

    Used to prove the schema REJECTS things, so each case must be written to a
    real file - validation resolves source paths relative to the manifest dir.
    """
    man = yaml.safe_load(Path(GOOD).read_text(encoding="utf-8"))
    mutate(man)
    with tempfile.NamedTemporaryFile("w", suffix=".yml", dir=str(FIX),
                                     delete=False, encoding="utf-8") as fh:
        yaml.safe_dump(man, fh)
        return fh.name


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


def test_good_properties_never_fail():
    # PASS if yosys present and the harness proves; SKIP if absent. An equivalent
    # design that satisfies the stated contract may never FAIL here.
    assert _run(properties.check, GOOD) in (PASS, SKIP)


def test_bad_properties_fail_on_candidate_only():
    # The +2 counter violates "counts by one". The value of this layer over L2 is
    # that it says WHICH side is wrong: golden proves, candidate fails.
    res = parity._run_layer(properties.check, BAD, "properties")
    if res.rollup() == SKIP:
        pytest.skip("yosys not available")
    assert res.rollup() == FAIL
    by_side = {name.split("[")[1].split(",")[0]: status for name, status, _ in res.items}
    assert by_side["golden"] == PASS
    assert by_side["candidate"] == FAIL


def test_properties_absent_section_is_not_evidence():
    # THE core honesty property of this layer. An unconfigured optional layer
    # must report N/A, never PASS: `parity.py m.yml --only L2b` on a manifest
    # with no properties section would otherwise exit 0 and print a verdict
    # claiming something was proven, having run nothing at all.
    assert _status(properties.check(COCOTB)) == N_A


def test_na_layer_cannot_produce_a_pass_verdict():
    # End-to-end guard for the same thing, through the orchestrator's verdict.
    out = _parity_out(COCOTB, "--only", "L2b")
    assert "RESULT: INCOMPLETE" in out, out
    assert "proven modules are equivalent" not in out, out


def test_property_failure_is_not_reported_as_non_equivalence():
    # A violated property localizes a broken contract to one side. It is NOT an
    # equivalence divergence (both sides can satisfy a weak contract and differ;
    # a golden can break a contract while matching its candidate exactly), so
    # the verdict must not say "Translation is NOT equivalent" on L2b alone.
    res = parity._run_layer(properties.check, BAD, "properties")
    if res.rollup() != FAIL:
        pytest.skip("yosys not available")
    out = _parity_out(BAD, "--only", "L2b")
    assert "a stated property was violated" in out, out
    assert "NOT equivalent" not in out, out


@pytest.mark.parametrize(("case", "mutate"), [
    ("bad mode", lambda m: m["properties"].update(mode="nonsense")),
    ("cover dropped", lambda m: m["properties"].update(mode="cover")),
    ("sby not shipped", lambda m: m["properties"].update(engine="sby")),
    ("no clock attestation", lambda m: m["properties"].pop("single_clock")),
    ("no expect_asserts", lambda m: m["properties"]["modules"][0].pop("expect_asserts")),
    ("zero expect_asserts", lambda m: m["properties"]["modules"][0].update(expect_asserts=0)),
    ("unnamed module", lambda m: m["properties"].update(modules=[{}])),
])
def test_properties_schema_rejects(case, mutate):
    # Each of these would otherwise reach the solver and either crash or, worse,
    # quietly check something other than what the user wrote.
    path = _mutated(mutate)
    try:
        assert _status(manifest_mod.run(path)) == FAIL, case
    finally:
        Path(path).unlink(missing_ok=True)


def test_properties_layer_self_validates():
    # `--only L2b` skips the MAN layer, so the layer has to re-run the schema
    # check itself or a malformed section reaches yosys unvalidated.
    path = _mutated(lambda m: m["properties"].pop("single_clock"))
    try:
        assert _status(properties.check(path)) == FAIL
    finally:
        Path(path).unlink(missing_ok=True)


def test_expect_asserts_mismatch_fails():
    # The vacuity gate: claim four properties where the harness states three and
    # the layer must FAIL rather than report the solver's happy verdict.
    path = _mutated(lambda m: m["properties"]["modules"][0].update(expect_asserts=4))
    try:
        res = parity._run_layer(properties.check, path, "properties")
        if res.rollup() == SKIP:
            pytest.skip("yosys not available")
        assert res.rollup() == FAIL
        assert any("ingestion mismatch" in d for _, _, d in res.items), res.items
    finally:
        Path(path).unlink(missing_ok=True)


# --- no layer may claim a pass it did not earn ------------------------------
#
# Three separate false-PASS bugs have come from the same one-line shape:
#
#     res = LayerResult("Lx", PASS)
#     if not man.get("<section>"):
#         return res            # <- "I checked nothing" reported as "it holds"
#
# L2b had it, then L2 (the centrepiece proof), L3a, L3b and L4 turned out to
# share it. This test is written against the SHAPE rather than the instances,
# so a new layer added later cannot reintroduce it quietly.

_OPTIONAL_SECTIONS = ["formal", "properties", "simulation", "synth"]

_SECTION_LAYERS = [
    ("L2 formal", formal_equiv.prove),
    ("L2b properties", properties.check),
    ("L3a trace", compare_traces.compare),
    ("L3b waveform", compare_waveforms.compare),
    ("L4 synth", synth_compare.compare),
]


@pytest.fixture
def stripped_manifest():
    """GOOD with every optional section removed - nothing left to check."""
    man = yaml.safe_load(Path(GOOD).read_text(encoding="utf-8"))
    for key in _OPTIONAL_SECTIONS:
        man.pop(key, None)
    with tempfile.NamedTemporaryFile("w", suffix=".yml", dir=str(FIX),
                                     delete=False, encoding="utf-8") as fh:
        yaml.safe_dump(man, fh)
        path = fh.name
    yield path
    Path(path).unlink(missing_ok=True)


@pytest.mark.parametrize(("name", "fn"), _SECTION_LAYERS, ids=[n for n, _ in _SECTION_LAYERS])
def test_unconfigured_layer_never_reports_pass(name, fn, stripped_manifest):
    assert _run(fn, stripped_manifest) == N_A, f"{name} claimed a verdict it never earned"


def test_disabled_formal_does_not_produce_a_proof_verdict(stripped_manifest):
    # The user-facing consequence: switching the proof off (because it is too
    # expensive) must not hand back a verdict that says "equivalent".
    # L0 + L2 only: L0 needs no external tool, so the verdict is the same on a
    # bare machine as in CI and this test asserts on wording, not toolchain.
    out = _parity_out(stripped_manifest, "--only", "L0,L2")
    assert "L2   N/A" in out, out
    assert "proven modules are equivalent" not in out, out
    assert "NO formal proof ran" in out, out


def test_simulation_only_run_is_not_called_a_proof():
    # A manifest with sim layers but no `formal:` section still exits 0 - the
    # layers that ran did agree - but the wording must not claim a proof.
    man = yaml.safe_load(Path(GOOD).read_text(encoding="utf-8"))
    man.pop("formal", None)
    man.pop("properties", None)
    with tempfile.NamedTemporaryFile("w", suffix=".yml", dir=str(FIX),
                                     delete=False, encoding="utf-8") as fh:
        yaml.safe_dump(man, fh)
        path = fh.name
    try:
        out = _parity_out(path, "--only", "L3a")
        assert "RESULT: PASS" in out, out
        assert "simulation evidence only" in out, out
    finally:
        Path(path).unlink(missing_ok=True)


def test_orchestrator_rejects_broken_fixture():
    # End-to-end: the orchestrator must exit 1 (FAIL) on the broken fixture
    # (the trace/waveform layers catch the divergence even without yosys).
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "parity.py"), BAD],
                       capture_output=True, text=True, check=False)
    assert r.returncode == 1, f"expected FAIL exit 1, got {r.returncode}\n{r.stdout}\n{r.stderr}"


def _parity(*extra):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "parity.py"), *extra],
                          capture_output=True, text=True,
                          check=False).returncode


def _parity_out(*extra):
    """Orchestrator stdout - for asserting on the WORDING of a verdict."""
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "parity.py"), *extra],
                       capture_output=True, text=True, check=False)
    return r.stdout + r.stderr


def test_cocotb_manifest_valid():
    # Schema-validate the cocotb fixture even if cocotb itself isn't installed.
    # The end-to-end cocotb run is exercised by the CI orchestrator step
    # (parity.py parity_cocotb.yml --strict) rather than here - pytest in a
    # mixed-toolchain environment runs into platform-specific GHDL/cocotb
    # quirks (e.g. mcode VHPI on Windows) that don't surface in the
    # orchestrator path on a Linux full-toolchain runner.
    assert _status(manifest_mod.run(COCOTB)) == PASS


def test_strict_evidence_gate_is_not_bypassed_by_expect():
    # A property-only run is INCOMPLETE by construction, so `--expect incomplete`
    # is the right assertion for it - but it must not become a way to accept an
    # L2b that proved nothing. --strict's refusal of a SKIPped/BOUNDED property
    # layer is evaluated BEFORE --expect, so the pair still fails without a
    # working solver. Outcome depends on the toolchain present, so derive it.
    out = _parity_out(GOOD, "--only", "L2b", "--expect", "incomplete")
    assert "EXPECT INCOMPLETE: OK" in out
    proved = "[L2b] PASS" in out
    rc = _parity(GOOD, "--only", "L2b", "--expect", "incomplete", "--strict")
    assert rc == (0 if proved else 1), out


def test_expect_flag_matches_and_mismatches():
    # --expect asserts the verdict: exit 0 on match, 1 on mismatch. Use L3a only
    # so the result is deterministic with just Icarus present.
    assert _parity(BAD, "--only", "L3a", "--expect", "fail") == 0
    assert _parity(BAD, "--only", "L3a", "--expect", "pass") == 1
    assert _parity(GOOD, "--only", "L3a", "--expect", "pass") == 0


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__)), "-v"]))
