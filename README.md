# translateHDL

Translate RTL between hardware description languages **and prove the translation
is equivalent to the original.**

VHDL ↔ Verilog-2001 today, architected for more languages. The translation is
authored to be faithful and human-readable; equivalence is established by a
layered **parity ladder** whose centerpiece is **formal sequential equivalence
checking** (Yosys / eqy). A translation that can't be proven equivalent isn't
done.

This repo is both a standalone toolset and a Claude Code skill (see
[SKILL.md](SKILL.md)).

## Why

Hand-translating RTL (the way [spacewire_light](#worked-example-spacewire_light)
was ported from VHDL to Verilog) is error-prone, and simulation alone can't prove
two implementations are identical for *every* input. translateHDL keeps the
faithful-translation discipline that makes designs comparable, and adds a formal
proof on top of the simulation checks.

## Quickstart

```sh
# 1. translate your module following rules/  (see SKILL.md workflow)
# 2. describe the comparison in a manifest (copy templates/parity_manifest.yml)
# 3. run the ladder:
python scripts/parity.py path/to/parity.yml --strict
```

Verdict exit codes: `0` PASS · `1` FAIL (divergence) · `77` BOUNDED
(bounded-equivalent, not fully proven) or INCOMPLETE (a tool was missing).

## The parity ladder

| Layer | Establishes |
| --- | --- |
| L0 interface | ports & params agree |
| L1 lint | both sides clean; Yosys catches multi-driver nets |
| **L2 formal SEC** | **proof** of sequential equivalence per module/config |
| L3a trace | matched deterministic benches emit identical `TRACE` lines |
| L3b waveform | normalized VCDs of observables agree |
| L4 synth | matched cell/wire/mem counts (sanity, not proof) |

**Certainty:** L2 PASS means *formally proven equivalent* — a closed
`equiv_induct` proof is unbounded, not a sample. **L2 BOUNDED** means induction
didn't close but no counterexample was found within `bounded_depth` cycles
(strong evidence, not a full proof — usually an encoding/reachability limit, see
[examples/spwlink](examples/spwlink/parity.yml)). The other layers are the safety
net and the only evidence for code formal can't reach (testbenches,
non-synthesizable constructs). Missing tools yield SKIP, never a false PASS;
`--strict` makes BOUNDED and SKIP failures (use it in CI).

## Repository layout

```
SKILL.md                 skill entry + workflow
rules/                   faithful-translation guides + pitfalls
scripts/                 the parity ladder (parity.py orchestrates)
  parity.py  iface_check.py  lint.py  formal_equiv.py
  compare_traces.py  compare_waveforms.py  synth_compare.py
  manifest.py  languages.py  _common.py
templates/               manifest, eqy config, CI workflow templates
tests/                   pytest self-tests + counter fixture (good/bad/xlang)
examples/                worked example against spacewire_light
.github/workflows/       this repo's own parity CI
```

## Self-tests

```sh
pytest tests/            # proves the harness PASSes equivalent designs
                         # and FAILs a deliberately broken one
```

The `tests/fixtures/counter/` fixture ships an equivalent translation, a
**deliberately broken** one (counts by 2), and a cross-language VHDL/Verilog
pair. The broken case must fail every comparison layer — that's how we know the
harness actually detects divergence instead of rubber-stamping.

## Toolchain

GHDL · Icarus Verilog · Yosys · (optional) eqy + SMT solver. All bundled in the
[OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build) for Linux and
Windows. A simulator-only machine still runs L0/L1(Verilog)/L3; the formal proof
runs in CI ([templates/parity_ci.yml](templates/parity_ci.yml)) or after
installing the suite.

## Worked example: spacewire_light

[examples/spwstream_trace/parity.yml](examples/spwstream_trace/parity.yml)
reproduces spacewire_light's VHDL↔Verilog `streamtest` trace + waveform parity
through the generic harness (expects `spacewire_light` checked out beside this
repo). It demonstrates the simulation layers on a real core; formal SEC for its
record-port modules needs an interface wrapper, described in
[rules/interface_contract.md](rules/interface_contract.md).

## Extending to other languages

Add a `Language` implementation to [scripts/languages.py](scripts/languages.py)
and a `rules/<from>_to_<to>.md` guide; the rest of the ladder is language-neutral.

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Leonardo Capossio - bard0
design - hello@bard0.com.

The `external/spacewire_light` submodule is third-party code under its own
license (LGPL-2.1 / GPL-2.0, © Joris van Rantwijk); the MIT license here covers
only the translateHDL tooling.
