---
name: translate-hdl
description: Translate RTL between hardware description languages (VHDL <-> Verilog-2001, extensible to more) AND prove the translation is equivalent to the original. Use whenever the user asks to translate / port / convert / rewrite an HDL design from one language to another - e.g. "translate this VHDL to Verilog", "port this Verilog module to VHDL", "convert the core to Verilog", "rewrite this entity in Verilog" - or to verify/prove that an existing translation matches the original ("check parity", "prove these are equivalent", "is my Verilog port correct"). Produces a faithful, human-readable translation and runs a layered parity ladder whose centerpiece is formal sequential equivalence checking (Yosys/eqy).
---

# translateHDL

Translate RTL between HDLs **and prove equivalence**. A translation you can't
prove equivalent is a liability; this skill treats the proof as the deliverable,
not an afterthought.

## Two things this skill does

1. **Authors a faithful translation.** You (the model) write readable RTL in the
   target language, preserving structure and state so the proof can close. The
   rules live in [rules/](rules/). External tools are *checkers*, never the
   shipped output.
2. **Proves parity.** `scripts/parity.py` runs a 5-layer ladder against a YAML
   manifest and prints one verdict. Layer 2 (formal SEC) is a mathematical
   equivalence proof; the other layers cover what formal can't.

## When to invoke

Triggers: *"translate/port/convert this VHDL to Verilog"* (or the reverse),
*"rewrite this entity/module in <language>"*, *"is my translation correct"*,
*"prove these two implementations are equivalent"*, *"check HDL parity"*.

## Workflow

1. **Identify scope.** Which module(s)/files, which direction, which target
   language. Note anything intentionally out of scope (e.g. vendor/IP-dependent
   files - spacewire_light leaves its AMBA/GRLIB files untranslated).
2. **Read the source RTL** and the matching rule guide:
   [rules/vhdl_to_verilog.md](rules/vhdl_to_verilog.md) or
   [rules/verilog_to_vhdl.md](rules/verilog_to_vhdl.md), plus
   [rules/pitfalls.md](rules/pitfalls.md). For record ports read
   [rules/interface_contract.md](rules/interface_contract.md).
3. **Translate faithfully.** Mirror the two-process pattern, preserve widths,
   reset kind, FSM encoding, and port names where possible. Faithfulness is what
   keeps Layer 2 push-button.
4. **Write a parity manifest** from
   [templates/parity_manifest.yml](templates/parity_manifest.yml): the two sides'
   sources/tops, the modules+param sets to prove, and matched deterministic
   benches for trace/waveform comparison.
5. **Run the ladder** (full toolchain or CI):
   ```sh
   python scripts/parity.py path/to/parity.yml --strict
   ```
6. **Interpret the verdict** (below). Iterate on the translation until Layer 2
   passes for every synthesizable module and Layer 3 passes for the rest. Do not
   report success on simulation alone.

## The parity ladder

Run in order by `scripts/parity.py`; each is also a standalone script.

| Layer | Script | What it establishes |
| --- | --- | --- |
| L0 interface | `iface_check.py` | ports/params agree (fast pre-check) |
| L1 lint | `lint.py` | both sides analyze/elaborate clean; Yosys `check -assert` catches multi-driver nets |
| **L2 formal SEC** | `formal_equiv.py` | **proof**: golden and candidate are sequentially equivalent (Yosys `equiv_induct` / `eqy`), per module and per parameter set |
| L3a trace | `compare_traces.py` | matched deterministic benches emit byte-identical `TRACE` lines |
| L3b waveform | `compare_waveforms.py` | normalized VCDs of top-level observables agree (reconciles GHDL/Icarus timescale + names) |
| L4 synth | `synth_compare.py` | matched Yosys cell/wire/mem counts (gross-divergence sanity, not a proof) |

### Certainty hierarchy (read this)

- **L2 PASS = proven equivalent** for that module/config, within the induction
  bound. This is the certainty the user asked for.
- L0/L1/L3/L4 are the safety net and the **only** evidence for code formal can't
  reach (testbenches, non-synthesizable constructs, multi-language sim behavior).
- A layer returns **SKIP** when its tool is absent - never a false PASS. Without
  `--strict`, an all-SKIP/PASS run reports **INCOMPLETE**, not success. Use
  `--strict` in CI so a missing tool fails the build.

Exit codes: `0` PASS, `1` FAIL (real divergence), `77` INCOMPLETE (skips).

## Tooling

Needs GHDL (VHDL), Icarus Verilog (Verilog sim), Yosys (lint + formal + synth),
and optionally eqy + a SMT solver (large-module SEC). All ship together in the
**OSS CAD Suite** (Linux + Windows). Locally on a sim-only box you still get
L0/L1(verilog)/L3 results; the formal proof runs in CI (see
[templates/parity_ci.yml](templates/parity_ci.yml)) or after installing the suite.

## Extending to more languages

Add one `Language` to [scripts/languages.py](scripts/languages.py) (its lint /
simulate / Yosys-ingest commands) and a `rules/<from>_to_<to>.md` guide. The
ladder scripts are language-neutral - they go through the registry and the
manifest's per-side `language:` fields.

## Limits

Formal SEC covers synthesizable RTL with mappable state; differing state
encodings may need the `eqy` engine, and record-flattened interfaces may need a
wrapper ([rules/interface_contract.md](rules/interface_contract.md)). Testbench
behavior, delays and file I/O are covered by simulation parity only. See
[README.md](README.md) for the worked spacewire_light example.
