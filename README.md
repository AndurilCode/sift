# Sift

Cross-platform usage analytics for AI coding tools. Sifts through local session data, computes 27 metrics, and generates reports, an interactive dashboard, and a machine-readable JSON export.

## Install as Claude Code Plugin

```bash
# Add the marketplace
/plugin marketplace add AndurilCode/sift

# Install the plugin
/plugin install sift@sift
```

Then use `/sift` in any conversation to analyze your AI usage.

## Standalone Usage

```bash
# All time, all sources
python3 -m sift

# Last 7 days
python3 -m sift --days 7

# Since a specific date
python3 -m sift --since 2026-03-01

# Filter by source
python3 -m sift --source claude-code
python3 -m sift --source claude-code --source copilot-cli

# Filter by project (substring, case-insensitive)
python3 -m sift --project my-repo

# Combine filters
python3 -m sift --days 30 --source claude-code --project my-repo

# List available sources and projects
python3 -m sift --list
python3 -m sift --list --days 30
```

## Supported Sources

| Source | Data Location |
|--------|--------------|
| Claude Code | `~/.claude/projects/` |
| Copilot CLI | `~/.copilot/session-state/` |
| VS Code Copilot Chat | `~/Library/Application Support/Code/User/workspaceStorage/` |
| Cursor | `~/.cursor/chats/` + `~/.cursor/ai-tracking/` |
| Gemini CLI | `~/.gemini/tmp/` |
| Codex CLI | `~/.codex/state_*.sqlite` |

## Output

All artifacts are written to `~/.sift/`:

| File | Description |
|------|-------------|
| `report.md` | Full markdown report with all metric sections |
| `dashboard.html` | Interactive HTML dashboard with filters and charts |
| `export.json` | Machine-readable JSON with all metrics and per-session data |
| `prompts/` | User prompts grouped by project |

## Metrics

| Category | Metrics |
|----------|---------|
| Cost | Total cost, cost/session, cost/action, cost/minute, daily burn, platform comparison |
| Cache & Context | Cache hit rate, amortization, input freshness, context accumulation, tool definition overhead |
| Output | Output ratio (net/gross), stop reason distribution, model mix |
| Productivity | Edit/read ratio, turns before first write, lines ratio, prompt length distribution |
| Health | Session health (median/P90/bloat), session outcome (success/failure), retry ratio, duration trend |
| Adoption | Project adoption, top sessions, model routing efficiency |

## Development

Build the plugin (first run also configures git hooks for auto-rebuild on commit):

```bash
bash build_plugin.sh
```

After this, any commit that touches `.py` files will automatically rebuild `analyzer.pyz` and bump the plugin version.

## Requirements

- Python 3.10+
- `pyyaml` (for Copilot CLI parsing)

No other dependencies. The dashboard uses Chart.js via CDN.
