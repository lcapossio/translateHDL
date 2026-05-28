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
   rules live in [rules/](rules/). Auto-translators (`sv2v`, `ghdl --synth`, etc.)
   may be used as *scaffolding or a reference* for large ports, but the **shipped
   RTL must be human-readable, human-reviewed, and proof-clean** — never commit
   raw machine output. External tools' main role here is to *check*, not produce.
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
5. **State the proof's assumptions & environment** (see the section below) before
   trusting any PASS. A SEC PASS is only meaningful relative to its assumptions.
6. **Run the ladder** (full toolchain or CI):
   ```sh
   python scripts/parity.py path/to/parity.yml --strict
   ```
7. **Interpret the verdict** (below) and hand back the **evidence packet** (see
   "Deliverables"). Iterate until Layer 2 proves every synthesizable module and
   Layer 3 covers the rest. Do not report success on simulation alone, and do not
   report BOUNDED as if it were a full proof.

## The parity ladder

Run in order by `scripts/parity.py`; each is also a standalone script.

| Layer | Script | What it establishes |
| --- | --- | --- |
| L0 interface | `iface_check.py` | ports/params agree (fast pre-check) |
| L1 lint | `lint.py` | both sides analyze/elaborate clean; Yosys `check -assert` catches multi-driver nets |
| **L2 formal SEC** | `formal_equiv.py` | **proof**: golden and candidate are sequentially equivalent (Yosys `equiv_induct`; `eqy` engine is experimental/untested), per module and per parameter set |
| L3a trace | `compare_traces.py` | matched deterministic benches emit byte-identical `TRACE` lines |
| L3b waveform | `compare_waveforms.py` | normalized VCDs of top-level observables agree (reconciles GHDL/Icarus timescale + names) |
| L4 synth | `synth_compare.py` | matched Yosys cell/wire/mem counts (gross-divergence sanity, not a proof) |

### Verdicts & certainty hierarchy (read this)

- **L2 PASS = formally proven equivalent** for that module/config. A *closed*
  `equiv_induct` proof is **unbounded** — it holds for all time, not just up to
  some depth. This is the certainty the user asked for.
- **L2 BOUNDED = bounded-equivalent only.** Induction did not close, but a miter
  SAT check found no counterexample within `formal.bounded_depth` cycles of
  reset. Strong evidence (no shallow divergence) but **not a full proof** —
  typically a proof limitation (unreachable states / differing FSM encoding).
  Close it with a stronger engine (`eqy`) or by aligning state encodings.
- **FAIL** = a real divergence: a formal counterexample, or an interface / lint /
  trace / waveform mismatch.
- **SKIP** = a required tool is absent — never a false PASS.
- L0/L1/L3/L4 are the safety net and the **only** evidence for code formal can't
  reach (testbenches, non-synthesizable constructs, multi-language sim behavior).

Run verdicts and exit codes:

| Verdict | Exit | Meaning |
| --- | --- | --- |
| PASS | 0 | every executed layer proven/agrees |
| FAIL | 1 | a real divergence was found |
| BOUNDED | 77 | bounded-equivalent, a module not fully proven (see L2 detail) |
| INCOMPLETE | 77 | no divergence, but a layer was SKIPped (missing tool) |

`--strict` turns **BOUNDED and SKIP into FAIL** — use it in CI, which demands a
full proof with the full toolchain.

## Assumptions & environment (a SEC PASS is only as good as these)

Sequential equivalence compares the two designs under **all input sequences** by
default — that is what you want for "is this the same implementation," so do
**not** add input/protocol (valid-ready) constraints just to make a proof pass.
What you must identify and make consistent across both sides:

- **Clock/domain correspondence** — which clock drives which register; multi-clock
  designs (e.g. spwstream's `clk`/`rxclk`/`txclk`) must map clocks the same way.
- **Reset & initial state** — same reset kind/polarity, and matching power-on
  values (`equiv_induct`'s base case starts from reset/init). `async2sync` is
  applied to both sides so async resets are comparable.
- **Black boxes / sub-IP** — vendor primitives, RAM/FIFO macros, soft cores: cut
  or treat as identical black boxes; never "prove" past an unmodeled box.
- **Memory initialization** — RAM/ROM initial contents must match; SEC maps
  memories to logic (`memory_map`), so init values matter.
- **X / undefined semantics** — Verilog `x` vs VHDL `'U'`/`'X'` differ; faithful
  synthesizable RTL should not depend on them.

Record these in the manifest/PR. **Heuristic:** if a module only proves once you
*constrain inputs*, that usually means the difference lives in unreachable /
don't-care space (the common cause of a BOUNDED result) — note it rather than
hiding it behind an assumption.

## Deliverables (the evidence packet)

When the task is done, hand back — not just "it passed":

1. **Translated RTL** (the committed, human-reviewed files).
2. **Parity manifest(s)** used.
3. **The exact proof command** (`python scripts/parity.py <manifest> --strict`).
4. **Per-layer verdict summary**: PASS / FAIL / BOUNDED / SKIP for L0–L4.
5. **Assumptions & environment** (the list above) the proof relied on.
6. **Known-unproven / BOUNDED modules**, with why (e.g. FSM encoding) and the
   path to full closure.
7. **Any wrappers, testbenches, or fixtures** created (e.g. a record-port wrapper).
8. **Skipped layers** and why (missing tool → run in CI).

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

Formal SEC covers synthesizable RTL with mappable state. Timer/counter-gated
FSMs and differing state encodings may not close under `equiv_induct` — set
`formal.bounded_depth` to triage (BOUNDED = proof limitation vs real bug); full
closure may then need a stronger engine (`eqy` is wired up but **experimental and
untested** — validate before relying on it). Record-flattened interfaces need a
wrapper — see the concrete recipe in
[rules/interface_contract.md](rules/interface_contract.md). Testbench behavior,
delays and file I/O are covered by simulation parity only.

Layer 2 is decided by parsing Yosys output (not exit code), because
`yowasp-yosys` does not reliably propagate a non-zero exit on assert failure;
Layers 1 and 4 use the same output-based check. See [README.md](README.md) for
the worked spacewire_light examples (syncdff proven, spwlink bounded).
