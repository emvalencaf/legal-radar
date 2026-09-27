# CLAUDE.md

@AGENTS.md

Before committing, branching or opening a PR, follow [CONTRIBUTING.md](CONTRIBUTING.md).

## Status line budget

When the user pays per token, the status line shows spend against a budget
(default `$ 100`). To change it, run `scripts/set-budget.sh <usd>` (this project,
stored in the git-ignored `.claude/budget`) or `scripts/set-budget.sh <usd> --global`
(all projects). Use `--show` to see the budget in effect and `--clear` to remove
it. `CLAUDE_BUDGET_USD` overrides both. See [README.md](README.md#status-line-budget).

## Agent skills

### Issue tracker

Issues live as GitHub issues in `emvalencaf/legal-radar` (via `gh`). See `docs/agents/issue-tracker.md`.

### Triage labels

Default canonical labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
