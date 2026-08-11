# Rules Constitution — Every Rule Must Have Enforcement

## The Meta-Rule

Every rule in `.claude/rules/` MUST be enforced by a machine — hook, CI stage, agent, or Semgrep rule. A rule with no enforcement is a suggestion. Suggestions are ignored under pressure. In banking software, pressure is constant.

When writing a new rules file: create the enforcement mechanism first, then the rule. See `.claude/reference/enforcement-map.md` for the full per-file enforcement reference.

## AI Session Enforcement (Claude Code)

Claude MUST:
- Refuse to write a new `.claude/rules/*.md` file without specifying what enforces it
- Refuse code that violates any rule even if not asked to check
- Never write `os.environ.get()` — always `config_service`
- Never write `SELECT *` on PII tables — even in examples
- Never write a hardcoded threshold — write `config_service.get("...")` instead
- Flag violations immediately when spotted, even while working on something else
