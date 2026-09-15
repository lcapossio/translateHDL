# translateHDL

Translate RTL between hardware description languages **and prove the translation
is equivalent to the original.**

VHDL ↔ Verilog-2001 today, architected for more languages. The translation is
authored to be faithful and human-readable; equivalence is established by a
layered **parity ladder** whose centerpiece is **formal sequential equivalence
checking** (Yosys / eqy). A translation that can't be proven equivalent isn't
done.

This repo is both a standalone toolset and a portable **agent skill**: plain
Markdown plus Python, tied to no particular agent runtime. Entry point:
[skills/translate-hdl/SKILL.md](skills/translate-hdl/SKILL.md).

## Index

- [Install](#install)
- [Why](#why)
- [Quickstart](#quickstart)
- [Features](#features)
- [The parity ladder](#the-parity-ladder)
- [Repository layout](#repository-layout)
- [Self-tests](#self-tests)
- [Toolchain](#toolchain)
- [Worked example: spacewire_light](#worked-example-spacewire_light)
- [Extending to other languages](#extending-to-other-languages)
- [Author](#author)
- [License](#license)

## Install

The skill is [`skills/translate-hdl/`](skills/translate-hdl/) — self-contained
Markdown and Python with no runtime-specific code. Any agent that can read a
directory can use it; the rest is packaging.

**Any agent, no install.** Clone the repo and point the agent at
[skills/translate-hdl/SKILL.md](skills/translate-hdl/SKILL.md), or copy
`skills/translate-hdl/` into your own project. [AGENTS.md](AGENTS.md) at the repo
root is picked up automatically by agents that follow that convention, and a
second [AGENTS.md](skills/translate-hdl/AGENTS.md) sits inside the skill so the
directory also works vendored on its own.

**As a plugin.** Manifests for one-command install live in `.claude-plugin/`:

```sh
/plugin marketplace add lcapossio/translateHDL
/plugin install translate-hdl@translatehdl
```

**Standalone, no agent at all.** The parity ladder is just Python — see
[Quickstart](#quickstart). The skill text tells an agent how to use the ladder;
it isn't required to run it.

## Features

- **VHDL ↔ Verilog-2001** translation guidance (faithful, state-preserving;
  pluggable to more languages via a small registry).
- **Layered parity ladder**: interface check, lint, **formal sequential
  equivalence (Yosys)**, deterministic trace compare, normalized VCD waveform
  compare, synth-stat sanity.
- **Optional property verification (L2b)**: prove stated properties (PSL for
  VHDL, immediate SV assertions for Verilog) on *each side* — unbounded
  (`sat -tempinduct`) or bounded. Says what SEC cannot: *which* side broke the
  contract. A contract result, deliberately kept out of the equivalence verdict.
- **Honest verdicts**: PASS (full unbounded proof) / FAIL / **BOUNDED**
  (bounded-equivalent, proof limitation) / INCOMPLETE (tool missing) / **N/A**
  (an optional layer nothing was configured for — never counted as evidence).
  Decided by parsing tool *output*, not exit codes.
- **Record-port support** via a golden-side wrapper (proven on spwlink).
- **Optional cocotb driver**: one Python testbench drives BOTH sims (GHDL + Icarus)
  for L3 — stimulus identical by construction (kills mirrored-bench drift).
- **Tool-skip aware** (exit `77`), `--strict` for CI, manifest-driven, OS-agnostic.
- **GitHub Actions CI** running the full ladder on OSS CAD Suite.

## Why

Hand-translating RTL (the way [spacewire_light](#worked-example-spacewire_light)
was ported from VHDL to Verilog) is error-prone, and simulation alone can't prove
two implementations are identical for *every* input. translateHDL keeps the
faithful-translation discipline that makes designs comparable, and adds a formal
proof on top of the simulation checks.

## Quickstart

```sh
cd skills/translate-hdl                   # the self-contained skill bundle
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
| **L2b properties** *(optional)* | **proof** that stated properties hold on each side — a contract claim, not an equivalence claim |
| L3a trace | matched deterministic benches emit identical `TRACE` lines |
| L3b waveform | normalized VCDs of observables agree |
| L4 synth | matched cell/wire/mem counts (sanity, not proof) |

**Certainty:** L2 PASS means *formally proven equivalent* — a closed
`equiv_induct` proof is unbounded, not a sample. **L2 BOUNDED** means induction
didn't close but no counterexample was found within `bounded_depth` cycles
(strong evidence, not a full proof — usually an encoding/reachability limit, see
[skills/translate-hdl/examples/spwlink](skills/translate-hdl/examples/spwlink/parity.yml)). The other layers are the safety
net and the only evidence for code formal can't reach (testbenches,
non-synthesizable constructs). Missing tools yield SKIP, never a false PASS;
`--strict` makes BOUNDED and SKIP failures (use it in CI).

**L2b (optional)** answers a different question from the rest of the ladder.
Every other layer asks *"is the candidate the same as the golden?"*; L2b asks
*"does this side satisfy its stated contract?"* — so a property result is
**never folded into the equivalence verdict**. Two sides can satisfy the same
weak contract and still differ, and a golden can violate a contract while being
perfectly equivalent to its candidate. What L2b adds is **localization**: SEC
reports a divergence, properties report *who* broke the contract. It also still
returns an unbounded result when SEC stalls at BOUNDED because the two sides
encode state differently.

Properties are written in each side's own language — PSL for VHDL, immediate
`assert`/`$past` for Verilog — and attached through a harness module wrapping
the unmodified DUT. Cross-language use means **two** harnesses; nothing proves
they state the same contract, so review them together.

The hazard this layer guards against is proving *nothing* and reporting success
(an unread property file, PSL outside GHDL's subset, a `<side>_top` with no
properties under it — a solver proves an empty conjunction happily). So every
module must declare `expect_asserts`, and the count of assert cells in the
prepared design is checked against it: **a mismatch is FAIL, never a pass**.
`single_clock: true` is likewise required — `sat` advances one global clock
step, so multi-clock and async designs are out of scope rather than silently
mis-modelled. `mode: prove` is unbounded, `mode: bmc` is BOUNDED, a missing
tool or an inconclusive/timed-out solver is SKIP, and a manifest with no
`properties:` section is **N/A** — never PASS. See
[templates/parity_manifest.yml](skills/translate-hdl/templates/parity_manifest.yml).

## Repository layout

The **`skills/translate-hdl/`** directory is the self-contained, portable skill
bundle — everything needed to run the skill lives inside it, and it can be
copied into another project as-is. The repo root only adds packaging manifests,
CI, license, README, and the spacewire_light submodule used by the examples.

```
AGENTS.md                       repo-root agent entry point
.claude-plugin/                 packaging manifests (plugin + marketplace)
.github/workflows/              this repo's parity CI
external/spacewire_light/       submodule used by the worked examples
LICENSE  README.md
skills/translate-hdl/           the skill bundle (portable):
  SKILL.md                        skill entry + workflow
  AGENTS.md                       pointer, for use vendored on its own
  requirements.txt                python deps (pyyaml, pytest, ruff)
  ruff.toml                       pinned lint rule set
  rules/                          translation guides, pitfalls, proof discipline
  scripts/                        the parity ladder (parity.py orchestrates)
    parity.py iface_check.py lint.py formal_equiv.py properties.py
    compare_traces.py compare_waveforms.py synth_compare.py
    manifest.py languages.py _common.py
  templates/                      manifest, eqy config, CI workflow templates
  tests/                          pytest self-tests + counter fixture
  examples/                       worked examples (against spacewire_light)
```

## Self-tests

From a clean checkout (Python 3.12+):

```sh
cd skills/translate-hdl
pip install -r requirements.txt
pytest tests/            # proves the harness PASSes equivalent designs
                         # and FAILs a deliberately broken one
ruff check scripts tests # python lint (also run in CI)
```

The `tests/fixtures/counter/` fixture ships an equivalent translation, a
**deliberately broken** one (counts by 2), and a cross-language VHDL/Verilog
pair. The broken case must fail every comparison layer — that's how we know the
harness actually detects divergence instead of rubber-stamping.

## Toolchain

GHDL · Icarus Verilog · Yosys (with ghdl-yosys-plugin for VHDL/PSL properties) ·
(optional) eqy + SMT solver. All bundled in the
[OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build) for Linux and
Windows. A simulator-only machine still runs L0/L1(Verilog)/L3; the formal proof
runs in CI ([skills/translate-hdl/templates/parity_ci.yml](skills/translate-hdl/templates/parity_ci.yml)) or after
installing the suite.

## Worked example: spacewire_light

spacewire_light is included as a submodule under `external/` — fetch it with:

```sh
git submodule update --init
```

Real-module results (see [skills/translate-hdl/examples/](skills/translate-hdl/examples/README.md)):
- **`syncdff`** — fully **formally proven** VHDL ≡ Verilog ([examples/syncdff](skills/translate-hdl/examples/syncdff/parity.yml)).
- **`spwlink`** — record ports proven via a golden-side wrapper; induction proves
  42/49 cells, a 40-cycle bounded miter finds no counterexample → **BOUNDED**
  ([examples/spwlink](skills/translate-hdl/examples/spwlink/parity.yml)).
- **`spwstream_trace`** — deterministic trace + normalized VCD waveform parity
  ([examples/spwstream_trace](skills/translate-hdl/examples/spwstream_trace/parity.yml)).

## Extending to other languages

Add a `Language` implementation to [skills/translate-hdl/scripts/languages.py](skills/translate-hdl/scripts/languages.py)
and a `rules/<from>_to_<to>.md` guide; the rest of the ladder is language-neutral.

## Author

Leonardo Capossio — [bard0 design](https://www.bard0.com) — hello@bard0.com

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Leonardo Capossio - bard0
design - hello@bard0.com.

The `external/spacewire_light` submodule is third-party code under its own
license (LGPL-2.1 / GPL-2.0, © Joris van Rantwijk); the MIT license here covers
only the translateHDL tooling.
