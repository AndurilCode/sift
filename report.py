"""
Unified report generator — single report from all sources.

Uses the metrics registry to compute all metrics and assemble report sections.
Cross-cutting sections (executive summary, cost optimization) are handled here.
"""

from __future__ import annotations
from pathlib import Path
from datetime import datetime

from sources.base import NormalizedSession
from metrics import compute_all, get_all_metrics, session_cost
from metrics.base import MetricResult, usd, tok

OUTPUT_DIR = Path.home() / ".sift"


def generate(sessions: list[NormalizedSession], source_names: dict[str, str], cutoff=None) -> Path:
    """Generate the unified org metrics report. Returns report path."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / "report.md"

    date_range = f"Since {cutoff.strftime('%Y-%m-%d')}" if cutoff else "All time"

    # Compute all metrics at once
    results = compute_all(sessions)

    # Build report context for metric report() methods
    ctx = {
        "source_names": source_names,
        "cutoff": cutoff,
        "sessions": sessions,
    }

    L = []  # report lines
    L.append("# Sift — AI Usage Report")
    L.append(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Range: {date_range}")
    sources_str = ", ".join(f"{v} (`{k}`)" for k, v in source_names.items())
    L.append(f"\nSources: {sources_str}\n")

    # ── Executive Summary (cross-cutting) ──
    L.append(_executive_summary(results))

    # ── Metric-owned sections (ordered) ──
    for m in get_all_metrics():
        if m.order == 0:
            continue
        section = m.report(results[m.key].data, results, ctx)
        if section:
            L.append(section)

    # ── Cost Optimization (cross-cutting) ──
    L.append(_cost_optimization(results, sessions))

    # ── Prompts by Project ──
    _write_prompts(sessions, source_names)

    with open(report_path, "w") as f:
        f.write("\n".join(L))

    print(f"Report: {report_path}")
    return report_path


def _executive_summary(results: dict[str, MetricResult]) -> str:
    eff = results["cost_efficiency"].data
    cache = results["cache_efficiency"].data
    or_data = results["output_ratio"].data
    comparison = results["platform_comparison"].data
    adoption = results["project_adoption"].data

    L = ["## 1. Executive Summary\n"]
    L.append("| Metric | Value |")
    L.append("|--------|-------|")
    L.append(f"| Total estimated cost | {usd(eff['total_cost_usd'])} |")
    L.append(f"| Total sessions | {eff['total_sessions']:,} |")
    L.append(f"| Total output tokens | {tok(eff['total_output_tokens'])} |")
    L.append(f"| Total tool calls | {eff['total_tool_calls']:,} |")
    L.append(f"| Output ratio (net) | {or_data['net']:.2%} |")
    L.append(f"| Output ratio (gross) | {or_data['gross']:.2%} |")
    L.append(f"| Cache hit rate | {cache['cache_hit_rate']:.1%} |")
    L.append(f"| Caching savings | {usd(cache['estimated_savings_usd'])} |")
    L.append(f"| Projects with AI usage | {adoption['total_projects']:,} |")

    outcome = results["session_outcome"].data
    L.append(f"| Success rate (heuristic) | {outcome['success_rate']:.1%} |")
    L.append(f"| Wasted cost (failures) | {usd(outcome['failure_cost'])} |")

    routing = results["model_routing"].data
    if routing["potential_savings"] > 0:
        L.append(f"| Model routing savings | {usd(routing['potential_savings'])} ({routing['routing_efficiency']:.0%} efficient) |")

    total_premium = sum(v.get("premium_requests", 0) for v in comparison.values())
    if total_premium:
        L.append(f"| Premium requests | {total_premium:,.1f} |")
    L.append("")
    return "\n".join(L)


def _cost_optimization(results: dict[str, MetricResult], sessions: list[NormalizedSession]) -> str:
    children = results["child_metrics"].data
    health = results["session_health"].data
    cache = results["cache_efficiency"].data

    L = ["## Cost Optimization Opportunities\n"]
    L.append("| Opportunity | Est. Savings | Action |")
    L.append("|------------|-------------|--------|")

    opus_short = [s for s in sessions if s.model and "opus" in s.model and s.total_tool_calls < 5]
    if opus_short:
        opus_cost = sum(session_cost(s) for s in opus_short)
        L.append(f"| {len(opus_short)} lightweight Opus sessions | {usd(opus_cost * 0.6)} | Switch to Sonnet |")
    if children["child_cost"] > 0:
        L.append(f"| {children['child_count']} subagent sessions | {usd(children['child_cost'] * 0.8)} | CLAUDE_CODE_SUBAGENT_MODEL=haiku |")
    if children["compaction_count"] > 0:
        L.append(f"| {children['compaction_count']} compaction events | {usd(children['compaction_cost'] * 0.5)} | CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=70 |")
    if health["sessions_over_50m"] > 0:
        over50 = [s for s in sessions if s.total_tokens > 50_000_000]
        over50_cost = sum(session_cost(s) for s in over50)
        L.append(f"| {health['sessions_over_50m']} sessions >50M tokens | {usd(over50_cost * 0.3)} | Break sessions earlier, /clear |")
    routing = results["model_routing"].data
    if routing["potential_savings"] > 0:
        L.append(f"| {routing['downgradeable_sessions']} downgradeable sessions | {usd(routing['potential_savings'])} | Route light tasks to cheaper models |")
    retry = results["retry_ratio"].data
    if retry["retry_heavy_sessions"] > 0:
        L.append(f"| {retry['retry_heavy_sessions']} retry-heavy sessions | {usd(retry['retry_cost'] * 0.3)} | Better prompts, break retry loops |")
    L.append(f"| Cache optimization | Saving {usd(cache['estimated_savings_usd'])} | Maintain {cache['cache_hit_rate']:.0%} hit rate |")
    L.append("")
    return "\n".join(L)


def _write_prompts(sessions: list[NormalizedSession], source_names: dict):
    """Write user prompts grouped by project."""
    prompts_dir = OUTPUT_DIR / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    by_project = {}
    for s in sessions:
        if s.project not in by_project:
            by_project[s.project] = []
        for p in s.prompts:
            by_project[s.project].append({
                "session_id": s.session_id,
                "source": s.source,
                "timestamp": p.get("timestamp", ""),
                "text": p.get("text", ""),
            })

    for project_name, prompts in by_project.items():
        if not prompts:
            continue
        prompts.sort(key=lambda x: x["timestamp"] or "")
        safe_name = project_name.replace("/", "_").replace(" ", "_")[:80]
        out_path = prompts_dir / f"{safe_name}.md"

        lines = [f"# Prompts: {project_name}", f"\n{len(prompts)} prompts\n"]
        for i, p in enumerate(prompts, 1):
            ts = p["timestamp"][:19].replace("T", " ") if p["timestamp"] else "?"
            src = source_names.get(p["source"], p["source"])
            lines.append(f"## {i}. [{ts}] {src} `{p['session_id'][:8]}`\n")
            text = p["text"]
            lines.append(str(text) if not isinstance(text, str) else text)
            lines.append("")

        with open(out_path, "w") as f:
            f.write("\n".join(lines))

    print(f"Prompts: {prompts_dir}")
