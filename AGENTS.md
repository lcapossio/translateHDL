# AGENTS.md

Instructions for coding agents working in this repository, and the entry point
for using the skill it ships.

## What this repo is

`translateHDL` translates RTL between hardware description languages (VHDL
to/from Verilog-2001) **and proves the translation equivalent** to the original.
The proof — not the translated file — is the deliverable.

The portable skill lives in [`skills/translate-hdl/`](skills/translate-hdl/).
It is plain Markdown plus Python and depends on no particular agent runtime.

## Using the skill

**Read [`skills/translate-hdl/SKILL.md`](skills/translate-hdl/SKILL.md) first.**
It is the entry point: workflow, the parity ladder, verdict meanings, and links
to everything else. Use it whenever the task is to translate, port, convert or
rewrite an HDL design from one language to another, or to verify that an
existing translation matches the original.

Two rules that matter more than the rest:

- Auto-translators (`sv2v`, `ghdl --synth`) are checkers and scaffolding only,
  never the shipped output. Translations are authored to be human-readable.
- Never present simulation alone, or a BOUNDED result, as a full proof. Read
  [`rules/proof_discipline.md`](skills/translate-hdl/rules/proof_discipline.md)
  before reporting any verdict.

## Working on the repo

All commands run from `skills/translate-hdl/`:

```bash
pip install -r requirements.txt
ruff check scripts tests        # lint gate; rules are pinned in ruff.toml
pytest tests -q                 # harness self-tests
python scripts/parity.py tests/fixtures/counter/parity_good.yml --strict
```

- **Python only** for scripting. No hardcoded or absolute paths in source.
- Everything must be OS-agnostic and run from a clean checkout.
- External tools are found on `PATH` (overridable per tool by environment
  variable, e.g. `YOSYS=yowasp-yosys`). A missing tool must yield SKIP, never a
  false PASS.
- Run the linter before building; fix lint errors rather than working around
  them.
- Don't commit build artifacts or one-off scripts.
- Source file headers carry author and current year.

## The honesty rule

This project's entire value is that a verdict means what it says. A layer that
did not run reports SKIP or N/A; a bounded result reports BOUNDED; only a closed
unbounded proof reports PASS. Verdicts are decided by parsing tool *output*, not
exit codes, because some tool builds exit 0 on failure. Any change that could
let an unproven design report PASS is a defect, however convenient.
