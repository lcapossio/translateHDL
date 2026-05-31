#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Leonardo Capossio - bard0 design
# Author: Leonardo Capossio - bard0 design - hello@bard0.com
"""Layer 2 — formal sequential equivalence checking (the primary proof).

For each synthesizable module listed under ``formal.modules`` (per parameter
set), prove that the golden and candidate implementations are sequentially
equivalent. A PASS here is a *proof* (within the engine's induction bound), not
a sample of behavior — this is what turns "strong parity" into "certainty".

Engines
-------
* ``yosys`` (default): built-in flow — read both sides into one session as
  modules ``gold``/``gate``, ``equiv_make``, then ``equiv_simple`` +
  ``equiv_induct``, then ``equiv_status -assert``. No extra dependency beyond
  Yosys (+ GHDL when a side is VHDL).
* ``eqy``: emit an ``.eqy`` config and run YosysHQ's eqy, which partitions large
  modules for scalable SEC. Use for big modules where induction is slow.

Bringing each side into Yosys goes through the language registry: Verilog reads
natively; VHDL is converted to a Verilog netlist via ``ghdl --synth``.

Interface note: ``equiv_make`` matches ports by name. When the two sides share
port names (faithful leaf translations, and Verilog<->VHDL without records) this
is automatic. For record-flattened interfaces whose names differ, supply a
per-module ``wrapper`` source (a tiny Verilog module that adapts names) in the
golden side, or switch that module to the ``eqy`` engine with a ``[match]``
section. translateHDL deliberately favors faithful, name-preserving translation
precisely so this layer stays push-button.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from _common import (BOUNDED, FAIL, PASS, LayerResult, ToolMissing, cli_main,
                     have, load_manifest, manifest_root, resolve_sources, run_capture,
                     run_output, tool)
import languages


def _read_cmds(root: Path, side: dict, top: str, params: dict, tmp: Path,
               wrapper: str | None) -> list[str]:
    lang = languages.get(side["language"])
    sources = resolve_sources(root, side["sources"])
    if wrapper:
        # Append, not prepend: a VHDL wrapper depends on the entities/packages
        # before it, and GHDL analyzes in order.
        sources = sources + resolve_sources(root, [wrapper])
    std = str(side.get("std", "08" if side["language"] == "vhdl" else "2001"))
    return lang.yosys_read(root, top, sources, params=params, std=std, workdir=tmp)


def _side_prep(cmds: list[str], top: str, name: str) -> list[str]:
    # Read one side and normalize it for SAT-based equivalence:
    #   memory_map  -> turn ROM/RAM ($mem) into logic the solver can reason about
    #   async2sync  -> convert async-reset FFs ($adff) to a synchronous form
    # Both transforms are applied identically to gold and gate, so the comparison
    # stays faithful; both are no-ops when the feature is absent.
    return [
        "design -reset", *cmds, f"hierarchy -top {top}",
        "proc", "flatten", "memory_map", "async2sync", "opt -full",
        f"rename {top} {name}", f"design -stash {name}",
    ]


def _combine() -> list[str]:
    return [
        "design -reset",
        "design -copy-from gold -as gold gold",
        "design -copy-from gate -as gate gate",
    ]


def _yosys_equiv_script(gold_cmds: list[str], gate_cmds: list[str], gold_top: str,
                        gate_top: str, induct_depth: int) -> str:
    return "\n".join([
        *_side_prep(gold_cmds, gold_top, "gold"),
        *_side_prep(gate_cmds, gate_top, "gate"),
        *_combine(),
        "equiv_make gold gate equiv",
        "hierarchy -top equiv",
        "clean -purge",
        "opt -full",
        # equiv_struct merges structurally-equivalent points; it is what lets
        # induction close designs whose state is encoded differently (e.g. a VHDL
        # enum FSM vs Verilog binary localparams) by relating the re-encoded state.
        "equiv_struct",
        "equiv_simple",
        f"equiv_induct -seq {induct_depth}",
        "equiv_status",
    ]) + "\n"


def _bounded_miter_script(gold_cmds: list[str], gate_cmds: list[str], gold_top: str,
                          gate_top: str, depth: int) -> str:
    # Bounded equivalence: prove no input sequence makes the designs differ within
    # `depth` cycles of reset. Not a full proof, but it tells "proof limitation"
    # (induction can't close, but no divergence exists) apart from a real bug
    # (a concrete counterexample trace). -show-inputs/-show-public expose the
    # per-cycle stimulus + the `trigger` wire so a counterexample is parseable.
    return "\n".join([
        *_side_prep(gold_cmds, gold_top, "gold"),
        *_side_prep(gate_cmds, gate_top, "gate"),
        *_combine(),
        "miter -equiv -make_assert -flatten gold gate miter",
        "hierarchy -top miter",
        "opt -full",
        f"sat -seq {depth} -prove-asserts -show-inputs -show-public",
    ]) + "\n"


# Default depth for the automatic counterexample probe when the manifest does
# not set formal.bounded_depth. Small + fast; long enough to catch shallow bugs.
_CE_PROBE_DEPTH = 20


def _extract_ce(out: str) -> dict | None:
    """Extract a counterexample trace from `sat -prove-asserts` output, or None.

    Yosys prints a per-cycle table (cycle, escaped-name, ..., value) followed by
    "SAT proof finished - model found: FAIL!" when a divergence exists. We
    locate the first cycle where the miter's `\\trigger` wire is 1 and return
    the input (`\\in_*`) stimulus up to and including that cycle.
    """
    if "model found" not in out or "FAIL" not in out:
        return None
    cycles: dict[int, dict[str, str]] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].isdigit() and parts[1].startswith("\\"):
            cyc = int(parts[0])
            sig = parts[1].lstrip("\\")
            val = parts[-1]
            cycles.setdefault(cyc, {})[sig] = val
    if not cycles:
        return None
    div = next((c for c in sorted(cycles) if cycles[c].get("trigger") == "1"), None)
    if div is None:
        return None
    trace = []
    for c in sorted(cycles):
        if c > div:
            break
        inputs = {k: v for k, v in cycles[c].items() if k.startswith("in_")}
        trace.append((c, inputs))
    return {"cycle": div, "trace": trace}


def _format_ce(ce: dict) -> str:
    # Compact one-line summary: per-input vector across cycles 1..div.
    by_sig: dict[str, list[str]] = {}
    for _, inputs in ce["trace"]:
        for k, v in inputs.items():
            by_sig.setdefault(k, []).append(v)
    cols = ", ".join(f"{k}=[{','.join(vs)}]" for k, vs in sorted(by_sig.items()))
    return f"counterexample at cycle {ce['cycle']}: {cols}"


def _prove_yosys(root: Path, man: dict, gold_top: str, gate_top: str,
                 gparams: dict, cparams: dict, tmp: Path,
                 wrapper: str | None, induct_depth: int,
                 bounded_depth: int) -> tuple[str, str]:
    gold = _read_cmds(root, man["golden"], gold_top, gparams, tmp, wrapper)
    gate = _read_cmds(root, man["candidate"], gate_top, cparams, tmp, None)
    script = _yosys_equiv_script(gold, gate, gold_top, gate_top, induct_depth)
    # Decide on OUTPUT, not exit code: equiv_status prints a definitive summary
    # and some yosys builds (yowasp) do not propagate a non-zero exit on assert
    # failure, so an exit-code-only check could mistake "not equivalent" for PASS.
    _, out = run_output([tool("yosys"), "-"], root, input_text=script)
    if "Equivalence successfully proven" in out:
        return PASS, "equiv_induct + equiv_status: equivalence successfully proven"
    m = re.search(r"Found a total of (\d+) unproven", out) or re.search(r"(\d+) are unproven", out)
    n = m.group(1) if m else "?"
    if not m and "ERROR" in out:
        tail = next((ln for ln in reversed(out.splitlines()) if "ERROR" in ln), "")
        return FAIL, f"equivalence not established — {tail}"

    # Induction did not close. Always run a bounded miter to either dig out a
    # concrete counterexample (real bug, actionable) or attest bounded equivalence
    # up to a depth (proof limitation, BOUNDED). Probe depth defaults to a small
    # value when the manifest does not set bounded_depth, so the verdict carries
    # actionable info without extra configuration.
    probe_depth = bounded_depth if bounded_depth > 0 else _CE_PROBE_DEPTH
    bscript = _bounded_miter_script(gold, gate, gold_top, gate_top, probe_depth)
    _, bout = run_output([tool("yosys"), "-"], root, input_text=bscript)
    ce = _extract_ce(bout)
    if ce is not None:
        return FAIL, f"{n} unproven $equiv cell(s); {_format_ce(ce)}"
    if "no model found" in bout:
        if bounded_depth > 0:
            return BOUNDED, (f"{n} cell(s) not inductively closed, but bounded-equivalent "
                             f"for {bounded_depth} cycles from reset (no counterexample); "
                             f"full proof needs a stronger engine")
        return FAIL, (f"{n} unproven $equiv cell(s); no shallow counterexample within "
                      f"{probe_depth} cycles (likely a proof limitation, not a bug). "
                      f"Set formal.bounded_depth to claim BOUNDED.")
    return FAIL, f"equiv_status: {n} unproven and bounded check inconclusive"


def _prove_eqy(root: Path, man: dict, module: str, params: dict, tmp: Path) -> tuple[str, str]:
    if not have("eqy"):
        raise ToolMissing(["eqy"])
    # Minimal eqy config: gold/gate are yosys scripts produced via the registry.
    gold = "\n".join(_read_cmds(root, man["golden"], module, params, tmp, None))
    gate = "\n".join(_read_cmds(root, man["candidate"], module, params, tmp, None))
    cfg = tmp / f"{module}.eqy"
    cfg.write_text(
        f"[gold]\n{gold}\nprep -top {module}\n\n"
        f"[gate]\n{gate}\nprep -top {module}\n\n"
        f"[strategy simple]\nuse sby\ndepth 10\nengine smtbmc\n",
        encoding="utf-8",
    )
    try:
        out = run_capture([tool("eqy"), "-f", str(cfg)], root)
    except Exception as exc:  # noqa: BLE001
        return FAIL, f"eqy failed: {exc}"
    return (PASS, "eqy: equivalent") if "Equivalence successfully proven" in out \
        else (FAIL, "eqy: not proven")


def prove(manifest_path: str) -> LayerResult:
    man = load_manifest(manifest_path)
    root = manifest_root(manifest_path)
    res = LayerResult("L2 formal", PASS)

    spec = man.get("formal")
    if not spec or not spec.get("enabled", True):
        res.detail = "no formal section; skipped"
        return res

    engine = spec.get("engine", "yosys")
    induct_depth = int(spec.get("induct_depth", 20))
    bounded_depth = int(spec.get("bounded_depth", 0))
    # Tool availability up front so we SKIP cleanly rather than half-run.
    needs = {"yosys"}
    if "vhdl" in (man["golden"]["language"].lower(), man["candidate"]["language"].lower()):
        needs.add("ghdl")
    if engine == "eqy":
        needs.add("eqy")
    missing = [t for t in needs if not have(t)]
    if missing:
        raise ToolMissing(missing)

    with tempfile.TemporaryDirectory(prefix=".formal_", dir=root) as tmpname:
        tmp = Path(tmpname)
        for mod in spec["modules"]:
            name = mod["name"]
            gold_top = mod.get("golden_top", name)
            gate_top = mod.get("candidate_top", name)
            wrapper = mod.get("wrapper")
            # Symmetric param_sets (same on both sides) or per-side configs
            # (e.g. VHDL generic `reset_time` vs Verilog param `RESET_TIME`).
            if mod.get("configs"):
                configs = [(c.get("golden", {}), c.get("candidate", {})) for c in mod["configs"]]
            else:
                configs = [(p, p) for p in (mod.get("param_sets") or [{}])]
            for gparams, cparams in configs:
                merged = {**gparams, **cparams}
                tag = name + ("[" + ",".join(f"{k}={v}" for k, v in merged.items()) + "]"
                              if merged else "")
                if engine == "eqy":
                    status, detail = _prove_eqy(root, man, name, gparams, tmp)
                else:
                    status, detail = _prove_yosys(root, man, gold_top, gate_top,
                                                  gparams, cparams, tmp, wrapper, induct_depth,
                                                  bounded_depth)
                res.add(tag, status, detail)

    res.status = res.rollup()
    res.detail = f"engine={engine}, {len(res.items)} module/config proofs"
    return res


if __name__ == "__main__":
    cli_main(prove)
