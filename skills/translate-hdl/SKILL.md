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

Triggers: *"translate/port/convert this VHDL to Verilog"* (or the reverse),
*"rewrite this entity/module in [language]"*, *"is my translation correct"*,
*"prove these two implementations are equivalent"*, *"check HDL parity"*.

## Workflow

1. **Scope**: modules/files, direction, target language. Note what is out of
   scope (vendor IP, etc.).
2. **Read** [rules/vhdl_to_verilog.md](rules/vhdl_to_verilog.md) or
   [rules/verilog_to_vhdl.md](rules/verilog_to_vhdl.md), plus
   [rules/pitfalls.md](rules/pitfalls.md); for record ports,
   [rules/interface_contract.md](rules/interface_contract.md).
3. **Translate faithfully**: preserve the two-process pattern, widths, reset
   kind, FSM encoding, port names. Faithfulness keeps L2 push-button.
4. **Write a manifest** from [templates/parity_manifest.yml](templates/parity_manifest.yml).
   *Optional:* `simulation.{trace,waveform}.cocotb_bench:` lets one Python
   testbench drive both sides (stimulus identical by construction).
5. **Run**: `python scripts/parity.py path/to/parity.yml --strict`
6. **Report** per [rules/proof_discipline.md](rules/proof_discipline.md): state
   the assumptions, deliver the evidence packet, and never present simulation
   alone or BOUNDED as a full proof.

## The parity ladder

| Layer | Script | Establishes |
| --- | --- | --- |
| L0 interface | `iface_check.py` | ports/params agree |
| L1 lint | `lint.py` | both sides clean; multi-driver nets caught |
| **L2 formal SEC** | `formal_equiv.py` | **proof**: golden ≡ candidate (`equiv_induct`) per module/config |
| L2b properties *(optional)* | `properties.py` | **proof**: stated properties hold on *each side* — a **contract** claim, outside the equivalence verdict |
| L3a trace | `compare_traces.py` | matched benches emit identical `TRACE` lines |
| L3b waveform | `compare_waveforms.py` | normalized VCDs of observables agree |
| L4 synth | `synth_compare.py` | matched cell/wire/mem counts (sanity, not proof) |

## Verdicts

| Verdict | Exit | Meaning |
| --- | --- | --- |
| **PASS** | 0 | every executed layer agrees. A *closed* `equiv_induct` is **unbounded** — holds for all time. |
| **BOUNDED** | 77 | induction did not close, but no counterexample within `formal.bounded_depth` cycles. Strong evidence, **not a full proof**. |
| **FAIL** | 1 | a real divergence, with a concrete counterexample (cycle + input vectors). |
| **INCOMPLETE** | 77 | a layer SKIPped (missing tool), or nothing was configured to run. Never a false PASS. |
| **N/A** | — | an *optional* layer had nothing configured. Carries no evidence, so it can never produce a PASS on its own. |

`--strict` turns BOUNDED and SKIP into FAIL (use in CI). `--expect
pass|fail|bounded|incomplete` asserts a specific verdict; `--only L0,L2` runs a
subset. A property-only run (`--only L2b`) is INCOMPLETE by construction -
assert it with `--expect incomplete --strict`, which still fails if L2b itself
proved nothing.

## Before reporting

Read [rules/proof_discipline.md](rules/proof_discipline.md) — what a verdict
does and does not mean, the assumptions to state, the evidence packet, where
the ladder stops, and why L2b is never an equivalence result.

## Extending

Add a `Language` to [scripts/languages.py](scripts/languages.py) and a
`rules/<from>_to_<to>.md` guide; the ladder is language-neutral. Worked cases
(syncdff proven, spwlink bounded) and the cocotb option are in
[examples/README.md](examples/README.md).
