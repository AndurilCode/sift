---
name: sift
description: Sift through AI coding assistant usage across platforms — cost, efficiency, cache, productivity, and session health metrics with actionable insights
user-invocable: true
---

# Sift

Sift through usage data across all AI coding tools (Claude Code, Copilot CLI, VS Code Copilot, Cursor, Gemini CLI, Codex CLI). Produces metrics, reports, a dashboard, and a machine-readable JSON export.

## Running Sift

The binary is bundled as a zipapp. All commands use `${CLAUDE_PLUGIN_ROOT}`:

```bash
# Full analysis (all time, all sources)
python3 ${CLAUDE_PLUGIN_ROOT}/skills/usage-analysis/analyzer.pyz

# Scoped analysis
python3 ${CLAUDE_PLUGIN_ROOT}/skills/usage-analysis/analyzer.pyz --days 7
python3 ${CLAUDE_PLUGIN_ROOT}/skills/usage-analysis/analyzer.pyz --days 30 --source claude-code
python3 ${CLAUDE_PLUGIN_ROOT}/skills/usage-analysis/analyzer.pyz --project my-repo

# Discover available sources and projects
python3 ${CLAUDE_PLUGIN_ROOT}/skills/usage-analysis/analyzer.pyz --list
```

Always start with `--list` if the user hasn't specified a scope, to understand what data is available.

## Output Artifacts

All outputs go to `~/.sift/`:

| File | Purpose |
|------|---------|
| `export.json` | **Primary artifact** — machine-readable, all metrics + per-session data |
| `report.md` | Human-readable markdown report |
| `dashboard.html` | Interactive HTML dashboard (open in browser) |
| `prompts/` | User prompts grouped by project |

## Working with export.json

After running the analyzer, read `~/.sift/export.json` for programmatic analysis. Structure:

```
{
  _schema: "sift-export-v1"
  summary: { total_sessions, total_cost_usd, total_tokens, total_tool_calls, projects }
  metrics: {
    <key>: { title, order, data: { ... } }
  }
  sessions: [
    { session_id, source, project, date, model, cost_usd, tokens: {...}, activity: {...}, extras: {...} }
  ]
}
```

### Key Metrics to Examine

| Metric Key | What It Tells You |
|------------|-------------------|
| `cost_efficiency` | Total spend, cost per session/action/output token |
| `session_outcome` | Heuristic success vs failure rate, wasted cost |
| `retry_ratio` | Token waste from debug loops and retries |
| `model_routing` | Savings available from routing light tasks to cheaper models |
| `cache_efficiency` | Cache hit rate, amortization, savings from caching |
| `session_health` | Median/P90/max session sizes, bloat index |
| `duration_trend` | Are sessions getting longer over time? |
| `prompt_length` | Under/over-specification patterns in user prompts |
| `daily_burn` | Daily cost trend with 7-day rolling average |
| `platform_comparison` | Per-source cost and session breakdown |

## Interpreting Results

When presenting findings to the user, focus on:

1. **Cost drivers** — What's expensive and why? Check `platform_comparison`, `model_mix`, `top_sessions`.
2. **Waste** — Sessions that failed (`session_outcome.failure`), retry-heavy sessions (`retry_ratio`), bloated sessions (`session_health.sessions_over_50m`).
3. **Optimization opportunities** — Model routing savings (`model_routing.potential_savings`), cache improvement (`cache_efficiency`), compaction events (`child_metrics.compaction_count`).
4. **Trends** — Is spend growing (`daily_burn`)? Are sessions getting longer (`duration_trend`)? Is adoption increasing (`project_adoption`)?
5. **Prompt quality** — Short prompts cause exploration waste, long prompts waste context (`prompt_length`).

Offer the dashboard (`open ~/.sift/dashboard.html`) for interactive exploration.

## Prerequisites

- Python 3.10+
- `pyyaml` (for Copilot CLI source parsing)
