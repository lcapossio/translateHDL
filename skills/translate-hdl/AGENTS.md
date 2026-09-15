# AGENTS.md

Entry point when this directory is used on its own (copied into a project,
vendored, or opened directly).

**Read [SKILL.md](SKILL.md).** It is the whole skill: when to use it, the
workflow, the parity ladder, what each verdict means, and links to the
translation rules, manifest template and scripts.

Quick start:

```bash
pip install -r requirements.txt
python scripts/parity.py path/to/parity.yml --strict
```

Two rules that matter more than the rest:

- Auto-translators (`sv2v`, `ghdl --synth`) are checkers and scaffolding only,
  never the shipped output.
- Never present simulation alone, or a BOUNDED result, as a full proof — see
  [rules/proof_discipline.md](rules/proof_discipline.md) before reporting.
