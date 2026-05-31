---
name: translate-hdl
description: Translate RTL between hardware description languages (VHDL to/from Verilog-2001, extensible to more) AND prove the translation is equivalent to the original. Use whenever the user asks to translate / port / convert / rewrite an HDL design from one language to another - e.g. "translate this VHDL to Verilog", "port this Verilog module to VHDL", "convert the core to Verilog", "rewrite this entity in Verilog" - or to verify/prove that an existing translation matches the original ("check parity", "prove these are equivalent", "is my Verilog port correct"). Produces a faithful, human-readable translation and runs a layered parity ladder whose centerpiece is formal sequential equivalence checking (Yosys/eqy).
---

# translateHDL

Translate RTL between HDLs **and prove equivalence** — the proof is the
deliverable. A translation you can't prove equivalent isn't done.

You do two things:

1. **Author a faithful translation.** Write readable RTL in the target language,
   preserving structure and state so the proof can close. Rules live in
   [rules/](rules/). Auto-translators (`sv2v`, `ghdl --synth`) may be used as
   *scaffolding or reference* for large ports, but the shipped RTL must be
   human-readable, human-reviewed, and proof-clean.
2. **Prove parity.** `scripts/parity.py` runs a 5-layer ladder against a YAML
   manifest and prints one verdict.

## When to invoke

Triggers: *"translate/port/convert this VHDL to Verilog"* (or the reverse),
*"rewrite this entity/module in [language]"*, *"is my translation correct"*,
*"prove these two implementations are equivalent"*, *"check HDL parity"*.

## Workflow

1. **Identify scope** — modules/files, direction, target language. Note anything
   intentionally out of scope (e.g. vendor/IP-dependent files).
2. **Read the rule guides**: [rules/vhdl_to_verilog.md](rules/vhdl_to_verilog.md)
   or [rules/verilog_to_vhdl.md](rules/verilog_to_vhdl.md), plus
   [rules/pitfalls.md](rules/pitfalls.md). For record ports read
   [rules/interface_contract.md](rules/interface_contract.md).
3. **Translate faithfully** — mirror the two-process pattern; preserve widths,
   reset kind, FSM encoding, port names. Faithfulness keeps L2 push-button.
4. **Write a parity manifest** from
   [templates/parity_manifest.yml](templates/parity_manifest.yml).
5. **State assumptions** (see below). A SEC PASS is only meaningful relative to
   its assumptions.
6. **Run the ladder**:
   ```sh
   python scripts/parity.py path/to/parity.yml --strict
   ```
7. **Interpret the verdict** and hand back the **evidence packet** (below).
   Iterate until L2 proves every synthesizable module and L3 covers the rest.
   Never report success on simulation alone; never report BOUNDED as a full proof.

## The parity ladder

| Layer | Script | What it establishes |
| --- | --- | --- |
| L0 interface | `iface_check.py` | ports/params agree (fast pre-check) |
| L1 lint | `lint.py` | both sides clean; Yosys catches multi-driver nets |
| **L2 formal SEC** | `formal_equiv.py` | **proof**: golden ≡ candidate (Yosys `equiv_induct`; `eqy` experimental) per module/config |
| L3a trace | `compare_traces.py` | matched deterministic benches emit identical `TRACE` lines |
| L3b waveform | `compare_waveforms.py` | normalized VCDs of observables agree |
| L4 synth | `synth_compare.py` | matched cell/wire/mem counts (sanity, not proof) |

## Verdicts

| Verdict | Exit | Meaning |
| --- | --- | --- |
| **PASS** | 0 | every executed layer agrees. A *closed* `equiv_induct` proof is **unbounded** (holds for all time, not a sample). |
| **BOUNDED** | 77 | induction did not close but a miter SAT check found no counterexample within `formal.bounded_depth` cycles. Strong evidence, **not a full proof** — usually an encoding/reachability limit; close with `eqy` or by aligning state encodings. |
| **FAIL** | 1 | a real divergence. L2 FAIL includes a concrete **counterexample** (`counterexample at cycle N: in_en=[0,1,1], in_rst=[0,0,1]`) — directly actionable. |
| **INCOMPLETE** | 77 | no divergence found but a layer was SKIPped (missing tool); never a false PASS. |

`--strict` turns BOUNDED and SKIP into FAIL (use in CI).
`--expect pass|fail|bounded|incomplete` asserts a verdict (exit 0 on match) —
for CI on a module that is *expected* to be BOUNDED.

## Assumptions & environment

A SEC PASS is only as good as these. SEC compares both designs under **all
input sequences**, so do **not** add input/protocol constraints just to pass.

- **Clock/domain correspondence** — multi-clock designs must map clocks the same way.
- **Reset & initial state** — same reset kind/polarity; matching power-on values
  (`async2sync` makes async resets comparable).
- **Black boxes / sub-IP** — cut or treat as identical black boxes.
- **Memory init** — RAM/ROM initial contents must match.
- **X / undefined** — faithful synthesizable RTL shouldn't depend on `x`/`'U'`.

If a module only proves when inputs are constrained, the divergence lives in
unreachable/don't-care space — record it, don't hide it.

## Deliverables (the evidence packet)

When done, hand back:

1. Translated RTL (committed, human-reviewed).
2. Parity manifest(s).
3. Exact proof command.
4. Per-layer verdict (L0–L4: PASS/FAIL/BOUNDED/SKIP).
5. Assumptions the proof relied on.
6. Known-BOUNDED modules with why + path to full closure.
7. Any wrappers/testbenches created.
8. Skipped layers and why.

## Extending to more languages

Add a `Language` to [scripts/languages.py](scripts/languages.py) and a
`rules/<from>_to_<to>.md` guide; the ladder is language-neutral.

## Limits & honesty notes

Formal SEC covers synthesizable RTL with mappable state. Timer/counter-gated
FSMs and differing encodings may not close under `equiv_induct` — set
`formal.bounded_depth` to triage (BOUNDED vs real bug). Record-flattened
interfaces need a wrapper — see [rules/interface_contract.md](rules/interface_contract.md).
The `eqy` engine is wired up but **experimental and untested**. L2 is decided by
parsing Yosys output (not exit code) because `yowasp-yosys` does not reliably
propagate non-zero exit; L1 and L4 use the same check. Tooling install notes and
worked cases such as syncdff proven and spwlink bounded are in
[examples/README.md](examples/README.md) and the manifests under [examples/](examples/).
