#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Leonardo Capossio - bard0 design
# Author: Leonardo Capossio - bard0 design - hello@bard0.com
"""Layer 2b - assertion-based property verification (optional).

Layer 2 proves golden == candidate. This layer proves something Layer 2 cannot:
that a stated *property* holds of each side on its own. It exists for the cases
where sequential equivalence is unavailable or insufficient:

* the two sides legitimately differ in state encoding / pipelining, so SEC only
  reaches BOUNDED - properties can still be proven unbounded on both sides;
* the behaviour of interest is a reset/protocol/handshake contract, and a
  property that passes on golden but fails on candidate localizes the break to
  ONE side, which equivalence checking cannot do.

What this layer does NOT claim
------------------------------
A property result is a statement about one side against a contract; it is NOT
an equivalence result, and the orchestrator keeps it out of the equivalence
verdict (see parity.py). Two sides can satisfy the same weak contract and still
differ; a golden can violate a contract while being perfectly equivalent to its
candidate. Nothing here substitutes for Layer 2.

Vacuity is the main hazard
--------------------------
The dangerous failure mode is not a wrong proof, it is proving NOTHING and
reporting success: a property file that is silently not read, PSL outside
GHDL's supported subset, a wrong ``<side>_top`` with no properties under it. A
solver will happily prove an empty conjunction and print SUCCESS. So every
module MUST declare ``expect_asserts`` and the count of ``$assert`` cells in
the FINAL prepared design is compared against it - a mismatch is FAIL, never a
pass. That check is the reason this layer can be trusted at all.

Scope of this version
---------------------
* Engine: Yosys' built-in ``sat`` only. (SymbiYosys is deliberately not wired
  up: an advertised backend with no executed test is a liability.)
* Modes: ``prove`` (temporal induction, an unbounded proof -> PASS) and ``bmc``
  (bounded -> BOUNDED, never PASS). ``cover`` is not offered.
* Clocking: single-clock synchronous designs only, and the manifest must say so
  with ``single_clock: true``. Yosys' ``sat`` uses one global time step and
  ``async2sync`` carries its own timing assumption, so multiple clocks, both
  edges, or async logic can hide real interleavings and produce a false PASS.

Properties live in the design's own language: PSL for VHDL (in comments, read
via the ghdl-yosys-plugin with ``-fpsl``), immediate ``assert`` statements for
Verilog (read with ``read_verilog -sv -formal``; native Yosys supports a subset
of SystemVerilog assertions, not full concurrent SVA - that needs Verific).

Status mapping is deliberately conservative and matches the rest of the ladder:
bounded evidence is BOUNDED and never PASS, a missing tool or an inconclusive
solver is SKIP and never PASS, and an ingestion mismatch is FAIL.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import languages
import manifest as manifest_mod
from _common import (
    BOUNDED,
    FAIL,
    N_A,
    PASS,
    SKIP,
    LayerResult,
    ToolMissing,
    cli_main,
    have,
    load_manifest,
    manifest_root,
    resolve_sources,
    run_output,
    tool,
)

_DEFAULT_DEPTH = 20
_DEFAULT_TIMEOUT = 300


def _prep(cmds: list[str], top: str, stat_json: Path) -> list[str]:
    # Same normalization as Layer 2 (memory_map/async2sync) so a design that is
    # provable there is provable here; `prep -top` also runs proc/opt and keeps
    # the formal cells. `-flatten` so properties can reference submodule state.
    # `tee -o <file> stat -json` captures the cell inventory of the design the
    # solver is about to see - writing it to a file rather than scraping stdout
    # keeps the vacuity check independent of Yosys' human-readable stat format.
    return [
        "design -reset", *cmds,
        f"prep -top {top} -flatten",
        "memory_map", "async2sync", "opt -full",
        f"tee -o {stat_json.as_posix()} stat -json",
    ]


def _sat_cmd(mode: str, depth: int) -> str:
    # -set-assumes: without it Yosys' `sat` IGNORES $assume cells, so any
    # property resting on a legal-environment assumption fails spuriously.
    common = "-prove-asserts -set-assumes -show-inputs -show-public"
    if mode == "prove":
        # Temporal induction: unbounded proof, no depth bound on the claim.
        return f"sat -tempinduct {common}"
    return f"sat -seq {depth} {common}"


def _count_asserts(stat_json: Path) -> int | None:
    """$assert cells in the final prepared design, or None if unreadable.

    None is NOT zero: "the design has no properties" and "the inventory could
    not be read" are different facts and get different statuses.
    """
    try:
        data = json.loads(stat_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    mods = data.get("modules")
    if isinstance(mods, dict):
        return sum(int(m.get("num_cells_by_type", {}).get("$assert", 0))
                   for m in mods.values() if isinstance(m, dict))
    design = data.get("design")
    if isinstance(design, dict):
        return int(design.get("num_cells_by_type", {}).get("$assert", 0))
    return None


def _ce_summary(out: str) -> str:
    """Compact counterexample from `sat -show-inputs` output.

    Same per-cycle table Layer 2 parses, but a property miter has no `trigger`
    wire to key on, so the whole input stimulus up to the last dumped cycle is
    the trace that reaches the violation.
    """
    cycles: dict[int, dict[str, str]] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].isdigit() and parts[1].startswith(chr(92)):
            cycles.setdefault(int(parts[0]), {})[parts[1].lstrip(chr(92))] = parts[-1]
    if not cycles:
        return "counterexample found (rerun the layer directly for the full trace)"
    by_sig: dict[str, list[str]] = {}
    for cyc in sorted(cycles):
        for sig, val in cycles[cyc].items():
            if "." in sig:
                continue   # hierarchical copy of a top-level signal; keep it short
            by_sig.setdefault(sig, []).append(val)
    cols = ", ".join(f"{k}=[{','.join(v)}]" for k, v in sorted(by_sig.items()))
    return f"counterexample over {max(cycles)} cycle(s): {cols}"


_DIAG_RE = re.compile(r"^\s*\S+:\d+:\d+:")


def _error_report(out: str, limit: int = 6) -> str:
    """Summarize a failed Yosys run.

    Yosys' own final line is usually a bare summary ("vhdl import failed.")
    while the diagnostics that say WHY come from the front end just above it.
    Reporting only the last line throws away the whole reason, so collect the
    ERROR line together with the source-located diagnostics preceding it.
    """
    lines = out.splitlines()
    idx = next((i for i in range(len(lines) - 1, -1, -1) if "ERROR" in lines[i]), None)
    if idx is None:
        return ""
    picked = [lines[idx].strip()]
    for line in reversed(lines[max(0, idx - 40):idx]):
        text = line.strip()
        if not text:
            continue
        if _DIAG_RE.match(text) or "error:" in text.lower():
            picked.insert(0, text)
            if len(picked) > limit:
                break
        elif len(picked) > 1:
            break   # diagnostics run contiguously; stop at the first unrelated line
    return "; ".join(picked)


def _verdict(out: str, mode: str, depth: int) -> tuple[str, str]:
    if "ERROR" in out:
        return FAIL, f"yosys error: {_error_report(out)}"
    if "FAIL!" in out:
        return FAIL, f"property violated ({mode}); {_ce_summary(out)}"
    if "SUCCESS!" not in out:
        # No definitive verdict: induction did not close, or the run stopped
        # early. Nothing was proved and nothing was refuted -> no evidence.
        return SKIP, f"inconclusive ({mode}): solver produced no verdict; see log"
    if mode == "prove":
        return PASS, "sat -tempinduct: all assertions hold (unbounded proof)"
    # The initial state is whatever the RTL's own initializers give plus
    # unconstrained state - formal does not apply a reset sequence unless the
    # properties themselves assume one. Say that rather than "from reset".
    return BOUNDED, (f"no assertion violated within {depth} cycles of the initial state "
                     f"(bounded evidence, not a proof - use mode: prove)")


def _check_module(root: Path, script: str, mode: str, depth: int, timeout: float,
                  stat_json: Path, expect: int,
                  yosys_args: tuple[str, ...] = ()) -> tuple[str, str]:
    """Run one property check and gate the verdict on property ingestion."""
    try:
        _, out = run_output([tool("yosys"), *yosys_args, "-"], root,
                            input_text=script, timeout=timeout)
    except subprocess.TimeoutExpired:
        return SKIP, (f"inconclusive: solver exceeded {timeout:g}s. A true property that is "
                      f"not k-inductive never closes - strengthen it, or use mode: bmc")

    if "ERROR" in out and "SUCCESS!" not in out and "FAIL!" not in out:
        report = _error_report(out)
        if any(marker in report.lower() for marker in _GHDL_UNSUPPORTED):
            # The command exists but this build refuses to elaborate VHDL. That
            # is a missing capability, not a broken design: SKIP, never FAIL.
            return SKIP, f"yosys cannot elaborate VHDL in this build: {report}"
        # Any other read/elaborate error is reported as such; it must never be
        # mistaken for "this design has no properties".
        return FAIL, f"yosys error: {report}"

    # --- vacuity gate: did the properties we declared actually get in? -------
    found = _count_asserts(stat_json)
    if found is None:
        return FAIL, ("could not read the cell inventory of the prepared design, so property "
                      "ingestion is unverifiable - refusing to report a proof")
    if found != expect:
        why = ("none were read - is the property file listed under this module, is "
               "<side>_top the harness, and is the property syntax in the reader's "
               "supported subset?" if found == 0 else
               "some properties were dropped, or expect_asserts is stale")
        return FAIL, (f"property ingestion mismatch: expected {expect} $assert cell(s), "
                      f"prepared design has {found} - {why}")

    status, detail = _verdict(out, mode, depth)
    return status, f"{detail} [{found}/{expect} assert cell(s) verified present]"


# Yosys messages that mean "this build cannot elaborate VHDL", as opposed to
# anything else the frontend might print. Matched case-insensitively.
_NO_GHDL = ("no such command", "can't load module", "cannot load module")
# ...and the message from a build that registers the command but refuses to run
# it. Seen only at execution time, so it is handled where the run happens.
_GHDL_UNSUPPORTED = ("not built with", "ghdl support")


@lru_cache(maxsize=None)
def _ghdl_yosys_args(root: Path) -> tuple[str, ...] | None:
    """Yosys arguments that expose a `ghdl` command, or None if there is none.

    Two build shapes exist and the difference is invisible until you run it.
    Some builds compile the GHDL frontend in, so plain `yosys` has a `ghdl`
    command; others - the OSS CAD Suite among them - ship it as a loadable
    module that must be requested with `-m ghdl`, and plain `yosys` then answers
    "No such command: ghdl" exactly as if the plugin were absent. Probe both, so
    a present-but-unloaded plugin is used rather than reported missing.

    Deliberately asks `help ghdl` (does the command exist?) and matches only the
    two messages that mean "no VHDL frontend here". An earlier version ran
    `ghdl --help` and rejected any output containing "error", which a working
    frontend's own help text can legitimately contain - that false negative
    SKIPped the VHDL side on a suite that had the plugin all along. A build that
    registers the command and then refuses at execution is caught by
    _GHDL_UNSUPPORTED during the real run.

    Cached: a process spawn per side is wasteful and the answer cannot change
    mid-run.
    """
    for args in ((), ("-m", "ghdl")):
        _, out = run_output([tool("yosys"), *args, "-p", "help ghdl"], root)
        if not any(marker in out.lower() for marker in _NO_GHDL):
            return args
    return None


def _expect_asserts(spec: dict, mod: dict, side: str) -> int:
    """Declared property count for one side (per-side override wins)."""
    val = mod.get(f"{side}_expect_asserts", mod.get("expect_asserts",
                                                    spec.get("expect_asserts")))
    return int(val)


def _side_ready(side_spec: dict, root: Path) -> tuple[str, tuple[str, ...]]:
    """(reason to SKIP, extra yosys args). An empty reason means "can check".

    Checked per side, not up front: a missing VHDL toolchain must not suppress
    the Verilog side, because per-side evidence is the whole point of L2b.
    """
    if side_spec["language"].lower() != "vhdl":
        return "", ()
    if not have("ghdl"):
        return "ghdl not installed (needed to read VHDL/PSL)", ()
    args = _ghdl_yosys_args(root)
    if args is None:
        # Yosys without a working ghdl frontend cannot read VHDL *with* its
        # PSL; the netlist bridge used by Layer 2 silently drops properties, so
        # SKIP rather than "prove" an assertion-free design.
        return ("yosys has no working `ghdl` command - tried built-in and `-m ghdl`; "
                "install ghdl-yosys-plugin (bundled with the OSS CAD Suite)"), ()
    return "", args


def check(manifest_path: str) -> LayerResult:
    man = load_manifest(manifest_path)
    root = manifest_root(manifest_path)
    res = LayerResult("L2b properties", N_A)

    spec = man.get("properties")
    if not spec or not spec.get("enabled", True):
        # N_A, NOT pass: this layer was never asked to check anything, and an
        # unconfigured layer must not contribute evidence to any verdict.
        res.detail = "no properties section - layer not configured (no evidence either way)"
        return res

    # Self-validate: `parity.py --only L2b` skips the manifest layer, so the
    # schema check has to happen here too or a malformed section reaches the
    # solver and crashes (or worse, quietly checks the wrong thing).
    bad = [i for i in manifest_mod.validate_properties(man, root) if i[1] == FAIL]
    if bad:
        res.status = FAIL
        res.detail = "invalid `properties` section"
        for tag, _, detail in bad:
            res.add(tag, FAIL, detail)
        return res

    mode = str(spec.get("mode", "prove")).lower()
    depth = int(spec.get("depth", _DEFAULT_DEPTH))
    timeout = float(spec.get("timeout_s", _DEFAULT_TIMEOUT))
    default_sides = spec.get("sides") or ["golden", "candidate"]

    if not have("yosys"):
        raise ToolMissing(["yosys"])

    with tempfile.TemporaryDirectory(prefix=".formal_props_", dir=root) as tmpname:
        tmp = Path(tmpname)
        for mod in spec["modules"]:
            name = mod["name"]
            sides = mod.get("sides") or default_sides
            param_sets = mod.get("param_sets") or [{}]
            for side in sides:
                side_spec = man[side]
                lang = languages.get(side_spec["language"])
                top = mod.get(f"{side}_top", name)
                sources = resolve_sources(root, side_spec["sources"])
                props = resolve_sources(root, mod.get(f"{side}_props") or [])
                std = str(side_spec.get("std", "08" if side_spec["language"] == "vhdl"
                                        else "2001"))
                expect = _expect_asserts(spec, mod, side)
                reason, yosys_args = _side_ready(side_spec, root)
                for i, params in enumerate(param_sets):
                    tag = f"{name}[{side}" + (
                        "," + ",".join(f"{k}={v}" for k, v in params.items())
                        if params else "") + "]"
                    if reason:
                        res.add(tag, SKIP, reason)
                        continue
                    stat_json = tmp / f"{name}_{side}_{i}_stat.json"
                    cmds = lang.yosys_read_formal(root, top, sources, props=props,
                                                  params=params, std=std, workdir=tmp)
                    script = "\n".join([*_prep(cmds, top, stat_json),
                                        _sat_cmd(mode, depth)]) + "\n"
                    status, detail = _check_module(root, script, mode, depth, timeout,
                                                   stat_json, expect, yosys_args)
                    res.add(tag, status, detail)

    res.status = res.rollup()
    res.detail = (f"engine=yosys, mode={mode}, {len(res.items)} property check(s) "
                  f"- contract results per side, NOT an equivalence result")
    return res


if __name__ == "__main__":
    cli_main(check)
