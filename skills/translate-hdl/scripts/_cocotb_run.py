#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Leonardo Capossio - bard0 design
# Author: Leonardo Capossio - bard0 design - hello@bard0.com
"""Run a cocotb testbench against one side of a parity comparison.

Invoked as a subprocess by ``compare_traces.py`` / ``compare_waveforms.py`` when
the manifest opts in via ``simulation.{trace,waveform}.cocotb_bench``. Keeping
cocotb in a child process avoids importing it into the orchestrator (it's
heavy + has VPI/VHPI side effects) and lets us pipe the simulator's stdout
back so the trace comparator can filter ``TRACE `` lines as usual.

One Python testbench drives BOTH the VHDL and Verilog DUTs — same stimulus
*by construction*, eliminating the mirrored-bench drift the
``stimulus_markers`` substring check can only weakly catch.

Usage::

  python _cocotb_run.py --sim ghdl|icarus --lang vhdl|verilog --top NAME \\
      --bench path/to/tb.py --std STD --build-dir DIR \\
      [--sources A B C ...] [--vcd OUT.vcd]

stdout is whatever the simulator (and the bench) emitted; any "TRACE " lines
the bench printed pass straight through. Exits 0 on cocotb test PASS, 1 on
test FAIL (xml report scanned for failures), nonzero on infrastructure error.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _has_failures(results_xml: Path) -> tuple[int, int]:
    """Return (failures, errors) from a cocotb JUnit results file."""
    if not results_xml.exists():
        return (0, 0)
    root = ET.parse(results_xml).getroot()
    # cocotb emits <testsuites><testsuite ...><testcase ...>...
    fails = errs = 0
    for tc in root.iter("testcase"):
        if tc.find("failure") is not None:
            fails += 1
        if tc.find("error") is not None:
            errs += 1
    return fails, errs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--sim", required=True, choices=("ghdl", "icarus"))
    ap.add_argument("--lang", required=True, choices=("vhdl", "verilog"))
    ap.add_argument("--top", required=True)
    ap.add_argument("--bench", required=True, help="path to cocotb .py testbench")
    ap.add_argument("--std", default="", help="VHDL std (e.g. 08) or Verilog gen (e.g. 2001)")
    ap.add_argument("--build-dir", required=True, help="cocotb sim_build dir (isolated per side)")
    ap.add_argument("--sources", nargs="+", required=True)
    ap.add_argument("--vcd", default="", help="if set, copy cocotb's VCD here")
    args = ap.parse_args(argv)

    bench = Path(args.bench).resolve()
    if not bench.exists():
        print(f"ERROR: cocotb bench not found: {bench}", file=sys.stderr)
        return 2
    build_dir = Path(args.build_dir).resolve()
    build_dir.mkdir(parents=True, exist_ok=True)

    # Make the bench .py importable as a module by stem name (cocotb test_module).
    sys.path.insert(0, str(bench.parent))

    # Pre-check the simulator binary so its absence becomes a clean SKIP (77),
    # not a confusing CalledProcessError out of cocotb's runner._execute.
    import shutil as _shutil  # noqa: PLC0415
    sim_binary = {"ghdl": "ghdl", "icarus": "iverilog"}[args.sim]
    if not _shutil.which(sim_binary):
        print(f"SIMULATOR-MISSING: {sim_binary} not on PATH (needed for cocotb --sim {args.sim})",
              file=sys.stderr)
        return 77

    try:
        # cocotb 2.x: Runner lives in the separate cocotb_tools package.
        from cocotb_tools.runner import get_runner   # noqa: PLC0415  (deferred; heavy)
    except ImportError:
        try:
            # cocotb 1.x fallback.
            from cocotb.runner import get_runner    # noqa: PLC0415
        except Exception as exc:
            print(f"COCOTB-MISSING: {exc}", file=sys.stderr)
            return 77
    except Exception as exc:
        print(f"COCOTB-MISSING: {exc}", file=sys.stderr)
        return 77

    runner = get_runner(args.sim)
    build_kwargs: dict = {
        "hdl_toplevel": args.top,
        "build_dir": str(build_dir),
        "waves": True,
        "always": True,                       # rebuild — sources may have changed under us
    }
    # cocotb 2.x prefers the language-agnostic `sources=` and infers VHDL vs
    # Verilog from file suffix (.vhd / .vhdl / .v / .sv).
    build_kwargs["sources"] = args.sources
    ghdl_args: list[str] = []
    if args.lang == "vhdl":
        hdl_toplevel_lang = "vhdl"
        # spacewire_light + GRLIB rely on -fsynopsys (std_logic_arith etc.).
        ghdl_args = ["-fsynopsys"]
        if args.std:
            ghdl_args.append(f"--std={args.std}")
        build_kwargs["build_args"] = ghdl_args
    else:
        hdl_toplevel_lang = "verilog"
        # cocotb's Icarus runner already passes -g2012 (it needs the cocotb VPI
        # dump bench compiled in that gen); don't fight it by adding -g2001.

    # cocotb 2.x: hdl_toplevel_lang belongs on test(), not build().
    runner.build(**build_kwargs)

    # cocotb's GHDL runner constructs `ghdl -r --work=<lib> <top> ...` and does
    # NOT propagate --std / -fsynopsys to that runtime step (only to -i/-m).
    # Without them, mcode-backend GHDL (Windows) fails with "cannot find entity"
    # because the .cf was tagged --std=08 but -r defaulted to --std=93. Pass
    # the same flags via test_args so the runtime line matches the build.
    test_kwargs: dict = {
        "hdl_toplevel": args.top,
        "hdl_toplevel_lang": hdl_toplevel_lang,
        "test_module": bench.stem,
        "build_dir": str(build_dir),
        "waves": True,
    }
    if args.lang == "vhdl":
        test_kwargs["test_args"] = ghdl_args
    runner.test(**test_kwargs)

    # Surface test failures even if cocotb itself returned 0 (it sometimes does).
    results = build_dir / "results.xml"
    fails, errs = _has_failures(results)
    if fails or errs:
        print(f"COCOTB-FAIL: {fails} failure(s), {errs} error(s) in {results}", file=sys.stderr)
        return 1

    if args.vcd:
        # cocotb dumps to <build>/<top>.vcd or <build>/dump.vcd depending on backend
        candidates = sorted(build_dir.glob("*.vcd"))
        if not candidates:
            # Some backends nest under sim_build/<top>/
            candidates = sorted(build_dir.rglob("*.vcd"))
        if not candidates:
            print(f"ERROR: cocotb produced no VCD under {build_dir}", file=sys.stderr)
            return 3
        shutil.copy(candidates[0], args.vcd)

    return 0


if __name__ == "__main__":
    sys.exit(main())
