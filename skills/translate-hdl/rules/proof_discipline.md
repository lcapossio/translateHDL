# Proof discipline

What a parity verdict does and does not mean, what you must state alongside it,
and where the ladder stops. Read once before reporting any result.

## Assumptions & environment

Sequential equivalence compares both designs under **all input sequences**.
Never add input constraints just to make a proof close — that converts a real
divergence into a silent one. Identify and match across sides:

- **Clock/domain correspondence** (multi-clock designs).
- **Reset & initial state**: kind, polarity, power-on values. `async2sync`
  makes async resets comparable to synchronous ones.
- **Black boxes / sub-IP**: cut them, or treat both sides as identical.
- **Memory init**: RAM/ROM contents must match.
- **X / undefined**: faithful synthesizable RTL must not depend on `x` / `'U'`.

If a module only proves under constrained inputs, the divergence lives in
unreachable or don't-care space. **Record it, don't hide it.**

## Deliverables (the evidence packet)

1. Translated RTL (committed, human-reviewed).
2. Parity manifest(s) plus the exact command that produced the proof.
3. Per-layer verdict for every layer that ran.
4. The assumptions the proof relied on (above).
5. Known-BOUNDED modules, why, and the path to full closure.
6. Wrappers and testbenches created; layers skipped and why.

## Limits

- **Formal SEC** covers synthesizable RTL with mappable state. Timer- or
  counter-gated FSMs and differing state encodings may not close under
  `equiv_induct`; set `formal.bounded_depth` to triage BOUNDED vs a real bug.
- **Record-flattened interfaces** need a wrapper — see
  [interface_contract.md](interface_contract.md).
- **`eqy` engine** is wired up but experimental and untested.
- **Verdicts are parsed from tool output, not exit codes.** Some builds
  (notably `yowasp-yosys`) exit 0 even when a check fails, so an exit-code-only
  gate can report a false proof.

## Working bottom-up, and when the proof is too expensive

Prove **leaf modules first, then upward**. `formal.modules:` is a list of
independent proof obligations, so a design is proven module by module:
`equiv_induct` closes easily on leaves and struggles on deep FSMs, and a
failure at the top of a proven hierarchy is a composition problem rather than a
hunt through the whole design. Faithful translation (same FSM encoding, widths,
reset kind) is what keeps each step push-button.

When a proof is too expensive, reduce it honestly rather than hiding it:

| Want | Do | Verdict |
| --- | --- | --- |
| Prove only some modules | list just those under `formal.modules:` | PASS for what ran |
| Accept bounded evidence | set `formal.bounded_depth: N` | BOUNDED |
| Cheaper induction | lower `induct_depth`, trim `param_sets` | PASS if it still closes |
| Run a subset of layers | `parity.py m.yml --only L0,L1,L3a` | per layer |
| Check contracts only | `parity.py m.yml --only L2b --expect incomplete --strict` | **INCOMPLETE** |
| Defer the cost | sim layers locally, formal in CI with `--strict` | full proof in CI |
| Skip the proof entirely | `formal: {enabled: false}` | **N/A** |

A disabled or unconfigured layer reports **N/A**, never PASS, and a run with no
formal proof says so in the verdict: *"NO formal proof ran — simulation
evidence only."* That is the honest outcome of skipping it. Simulation
agreement is evidence; it is not equivalence.

## L2b: properties vs equivalence

L2b asks *"does this side satisfy its stated contract?"* — not *"do the two
sides agree"*. It is a different claim and never enters the equivalence
verdict: two sides can satisfy the same weak contract and still differ, and a
golden can violate a contract while being perfectly equivalent to its
candidate. Its value is **localization** (which side broke the contract) and
reaching an unbounded result where SEC stalls at BOUNDED on differing state
encodings.

Properties attach through a harness module wrapping the unmodified DUT, named
by `<side>_top`. Cross-language use means **two** harnesses, and nothing proves
they state the same contract — review them side by side.

Its real hazard is proving *nothing* and reporting success: an unread property
file, PSL outside the supported subset, a `<side>_top` with no properties under
it. A solver proves an empty conjunction happily. Hence:

- `expect_asserts` is **mandatory**; the assert-cell count of the prepared
  design is checked against it and a mismatch is FAIL.
- `single_clock: true` is **mandatory**; the engine models one global clock
  step, so multi-clock, dual-edge and async designs are out of scope rather
  than silently mis-modelled.
- Engine is the built-in `sat` only. Missing VHDL/PSL support SKIPs that side,
  and the other side still runs.

Full key reference: [../templates/parity_manifest.yml](../templates/parity_manifest.yml).
