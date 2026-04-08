#!/usr/bin/env python3
"""
AI Coding Assistant Usage Analyzer — unified entry point.

Discovers all available sources, parses sessions into a normalized schema,
runs analysis, and generates a single unified report.

Usage:
    python3 main.py                       # all time
    SINCE_DAYS=7 python3 main.py          # last 7 days
    SINCE_DATE=2026-03-01 python3 main.py # since date
"""

from sources import ALL_SOURCES
from sources.base import get_cutoff
from metrics import compute_all
from metrics.base import usd, tok
import report
import dashboard


def main():
    cutoff = get_cutoff()
    all_sessions = []
    source_names = {}

    for SourceClass in ALL_SOURCES:
        source = SourceClass()
        if not source.available():
            print(f"  {source.name}: not found, skipping")
            continue

        print(f"Parsing {source.name}...")
        sessions = source.parse_all(cutoff)
        print(f"  {len(sessions)} sessions")
        all_sessions.extend(sessions)
        source_names[source.key] = source.name

    if not all_sessions:
        print("No sessions found.")
        return

    # Compute all metrics at once
    results = compute_all(all_sessions)
    eff = results["cost_efficiency"].data
    cache = results["cache_efficiency"].data
    out_ratio = results["output_ratio"].data
    children = results["child_metrics"].data
    er = results["edit_read_ratio"].data
    health = results["session_health"].data
    comparison = results["platform_comparison"].data

    print("\n" + "=" * 70)
    print("  AI CODING ASSISTANT — UNIFIED METRICS")
    print("=" * 70)

    print(f"\n  Total estimated cost:     {usd(eff['total_cost_usd'])}")
    print(f"  Total sessions:           {eff['total_sessions']:,}")
    print(f"  Output tokens generated:  {tok(eff['total_output_tokens'])}")
    print(f"  Output ratio (net):       {out_ratio['net']:.2%}")
    print(f"  Output ratio (gross):     {out_ratio['gross']:.2%}")
    print(f"  Cache hit rate:           {cache['cache_hit_rate']:.1%}")
    print(f"  Savings from caching:     {usd(cache['estimated_savings_usd'])}")

    total_premium = sum(v.get("premium_requests", 0) for v in comparison.values())
    if total_premium:
        print(f"  Premium requests:         {total_premium:,.1f}")

    print(f"\n  {'Source':<20} {'Sessions':>10} {'Cost':>12} {'Avg/Session':>14}")
    print(f"  {'-'*58}")
    for key in sorted(comparison):
        c = comparison[key]
        print(f"  {source_names.get(key, key):<20} {c['sessions']:>10,} {usd(c['total_cost']):>12} {usd(c['avg_cost_per_session']):>14}")

    print("\n  Cost efficiency:")
    print(f"    Per session:           {usd(eff['cost_per_session'])}")
    print(f"    Per 1K output tokens:  {usd(eff['cost_per_1k_output'])}")
    print(f"    Per tool call:         {usd(eff['cost_per_tool_call'])}")

    print("\n  Session health:")
    print(f"    Median tokens:         {tok(health['median_tokens'])}")
    print(f"    Bloat index:           {health['bloat_index']:.0f}x (max/median)")
    print(f"    Sessions >50M tokens:  {health['sessions_over_50m']}")

    if er["reads"] > 0 or er["edits"] > 0:
        print("\n  Productivity:")
        print(f"    Edit+Write/Read ratio: {er['edit_read_ratio']:.2f}")

    if children["child_count"] > 0:
        print(f"    Subagent cost ratio:   {children['child_cost_ratio']:.1%}")
        print(f"    Compaction rate:       {children['compaction_rate']:.1%}")

    print("")

    # Generate report + dashboard
    report.generate(all_sessions, source_names, cutoff)
    dashboard.generate(all_sessions, source_names, cutoff)


if __name__ == "__main__":
    main()
