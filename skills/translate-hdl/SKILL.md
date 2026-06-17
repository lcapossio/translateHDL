---
name: translate-hdl
description: Translate RTL between hardware description languages (VHDL to/from Verilog-2001, extensible to more) AND prove the translation is equivalent to the original. Use whenever the user asks to translate / port / convert / rewrite an HDL design from one language to another - e.g. "translate this VHDL to Verilog", "port this Verilog module to VHDL", "convert the core to Verilog", "rewrite this entity in Verilog" - or to verify/prove that an existing translation matches the original ("check parity", "prove these are equivalent", "is my Verilog port correct"). Produces a faithful, human-readable translation and runs a layered parity ladder whose centerpiece is formal sequential equivalence checking (Yosys/eqy).
---

# translateHDL

Translate RTL between HDLs **and prove equivalence** — the proof is the
deliverable. Two jobs: (1) author a faithful, human-readable translation
following [rules/](rules/); (2) run `scripts/parity.py` against a YAML
manifest. Auto-translators (`sv2v`, `ghdl --synth`) are *checkers/scaffolding*
only — never the shipped output.

## When to invoke

Triggers: *"translate/port/convert this VHDL to Verilog"* (or the reverse),
*"rewrite this entity/module in [language]"*, *"is my translation correct"*,
*"prove these two implementations are equivalent"*, *"check HDL parity"*.

## Workflow

1. **Scope**: modules/files, direction, target language. Note anything
   out of scope (vendor IP, etc.).
2. **Read** [rules/vhdl_to_verilog.md](rules/vhdl_to_verilog.md) or
   [rules/verilog_to_vhdl.md](rules/verilog_to_vhdl.md), plus
   [rules/pitfalls.md](rules/pitfalls.md); for record ports
   [rules/interface_contract.md](rules/interface_contract.md).
3. **Translate faithfully**: preserve the two-process pattern, widths,
   reset kind, FSM encoding, port names. Faithfulness keeps L2 push-button.
4. **Write a manifest** from [templates/parity_manifest.yml](templates/parity_manifest.yml).
   *Optional:* `simulation.{trace,waveform}.cocotb_bench:` lets one Python
   testbench drive both sides via cocotb (stimulus identical by construction).
5. **State the assumptions** (below) — a SEC PASS is only meaningful relative
   to them.
6. **Run**: `python scripts/parity.py path/to/parity.yml --strict`
7. **Interpret the verdict**, deliver the evidence packet, iterate. Never
   report sim alone or BOUNDED as a full proof.

## The parity ladder

| Layer | Script | Establishes |
| --- | --- | --- |
| L0 interface | `iface_check.py` | ports/params agree |
| L1 lint | `lint.py` | both sides clean; Yosys catches multi-driver nets |
| **L2 formal SEC** | `formal_equiv.py` | **proof**: golden ≡ candidate (Yosys `equiv_induct`; `eqy` experimental) per module/config |
| L3a trace | `compare_traces.py` | matched benches emit identical `TRACE` lines |
| L3b waveform | `compare_waveforms.py` | normalized VCDs of observables agree |
| L4 synth | `synth_compare.py` | matched cell/wire/mem counts (sanity, not proof) |

## Verdicts

| Verdict | Exit | Meaning |
| --- | --- | --- |
| **PASS** | 0 | every executed layer agrees. A *closed* `equiv_induct` is **unbounded** (holds for all time). |
| **BOUNDED** | 77 | induction did not close, but a miter SAT found no counterexample within `formal.bounded_depth` cycles. Strong evidence, **not a full proof** — usually an encoding/reachability limit. |
| **FAIL** | 1 | a real divergence. L2 FAIL includes a concrete counterexample (cycle + input vectors) — directly actionable. |
| **INCOMPLETE** | 77 | a layer SKIPped (missing tool); never a false PASS. |

`--strict` turns BOUNDED and SKIP into FAIL (use in CI). `--expect
pass|fail|bounded|incomplete` asserts a specific verdict.

## Assumptions & environment

SEC compares both designs under **all input sequences** — don't add input
constraints just to pass. Identify and match across sides:

- **Clock/domain correspondence** (multi-clock designs).
- **Reset & initial state** (kind/polarity, power-on values; `async2sync` makes async resets comparable).
- **Black boxes / sub-IP** (cut or treat as identical).
- **Memory init** (RAM/ROM contents must match).
- **X / undefined** — faithful synthesizable RTL shouldn't depend on `x`/`'U'`.

If a module only proves with constrained inputs, the divergence lives in
unreachable / don't-care space — record it, don't hide it.

## Deliverables (the evidence packet)

1. Translated RTL (committed, human-reviewed).
2. Parity manifest(s) + exact proof command.
3. Per-layer verdict for L0–L4.
4. Assumptions the proof relied on.
5. Known-BOUNDED modules with why + path to full closure.
6. Wrappers/testbenches created. Skipped layers and why.

## Extending to more languages

Add a `Language` to [scripts/languages.py](scripts/languages.py) and a
`rules/<from>_to_<to>.md` guide; the ladder is language-neutral.

## Limits & honesty notes

- Formal SEC covers synthesizable RTL with mappable state. Timer/counter-gated
  FSMs and differing encodings may not close under `equiv_induct` — set
  `formal.bounded_depth` to triage BOUNDED vs real bug.
- Record-flattened interfaces need a wrapper (see
  [rules/interface_contract.md](rules/interface_contract.md)).
- The `eqy` engine is wired up but **experimental and untested**.
- L1/L2/L4 verdicts are decided by parsing Yosys output, not exit code
  (`yowasp-yosys` doesn't reliably propagate non-zero exit).
- Worked cases (syncdff proven, spwlink bounded) + cocotb option are in
  [examples/README.md](examples/README.md).
