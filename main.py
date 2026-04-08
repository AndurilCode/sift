#!/usr/bin/env python3
"""
AI Coding Assistant Usage Analyzer — unified entry point.

Discovers all available sources, parses sessions into a normalized schema,
runs analysis, and generates a single unified report.

Usage:
    python3 main.py                          # all time, all sources
    python3 main.py --list                   # list sources and projects
    python3 main.py --list --days 30         # list projects from last 30 days
    python3 main.py --days 7                 # last 7 days
    python3 main.py --since 2026-03-01       # since date
    python3 main.py --source claude-code     # single source
    python3 main.py --source claude-code --source copilot-cli
    python3 main.py --project my-repo        # filter by project (substring)
    python3 main.py --days 30 --source claude-code --project my-repo
"""

import argparse
from sources import ALL_SOURCES
from sources.base import get_cutoff
from metrics import compute_all
from metrics.base import usd, tok
import report
import dashboard


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Analyze AI coding assistant usage across tools.",
    )
    p.add_argument(
        "--list", action="store_true",
        help="List available sources and discovered projects, then exit.",
    )
    date_group = p.add_mutually_exclusive_group()
    date_group.add_argument(
        "--days", type=int, metavar="N",
        help="Analyze the last N days",
    )
    date_group.add_argument(
        "--since", type=str, metavar="DATE",
        help="Analyze since date (ISO format, e.g. 2026-03-01)",
    )
    p.add_argument(
        "--source", action="append", metavar="KEY",
        help="Include only these sources (e.g. claude-code, copilot-cli). Repeatable.",
    )
    p.add_argument(
        "--project", action="append", metavar="NAME",
        help="Include only sessions whose project contains NAME (case-insensitive). Repeatable.",
    )
    return p.parse_args()


def filter_sessions(sessions, *, projects=None):
    """Filter sessions by project name substring (case-insensitive)."""
    if not projects:
        return sessions
    lowers = [p.lower() for p in projects]
    return [s for s in sessions if any(p in s.project.lower() for p in lowers)]


def list_sources_and_projects(cutoff=None):
    """Print available sources and all discovered projects."""
    from collections import defaultdict

    print("\nSources:")
    print(f"  {'Key':<20} {'Name':<25} {'Available'}")
    print(f"  {'-'*60}")
    available_keys = []
    for SourceClass in ALL_SOURCES:
        source = SourceClass()
        avail = source.available()
        mark = "yes" if avail else "no"
        print(f"  {source.key:<20} {source.name:<25} {mark}")
        if avail:
            available_keys.append(source.key)

    # Parse sessions to discover projects
    all_sessions = []
    source_names = {}
    for SourceClass in ALL_SOURCES:
        source = SourceClass()
        if not source.available():
            continue
        sessions = source.parse_all(cutoff)
        all_sessions.extend(sessions)
        source_names[source.key] = source.name

    projects = defaultdict(lambda: {"sessions": 0, "sources": set()})
    for s in all_sessions:
        name = s.project or "(no project)"
        projects[name]["sessions"] += 1
        projects[name]["sources"].add(s.source)

    print(f"\nProjects ({len(projects)}):")
    print(f"  {'Project':<40} {'Sessions':>10} {'Sources'}")
    print(f"  {'-'*75}")
    for name, info in sorted(projects.items(), key=lambda x: x[1]["sessions"], reverse=True):
        srcs = ", ".join(sorted(info["sources"]))
        display = name if len(name) <= 38 else name[:35] + "..."
        print(f"  {display:<40} {info['sessions']:>10,} {srcs}")

    print("\nUse --source KEY and --project NAME to filter.\n")


def main():
    args = parse_args()
    cutoff = get_cutoff(since_days=args.days, since_date=args.since)

    if args.list:
        list_sources_and_projects(cutoff)
        return

    source_filter = set(args.source) if args.source else None

    all_sessions = []
    source_names = {}

    for SourceClass in ALL_SOURCES:
        source = SourceClass()

        # Skip sources not in filter
        if source_filter and source.key not in source_filter:
            continue

        if not source.available():
            print(f"  {source.name}: not found, skipping")
            continue

        print(f"Parsing {source.name}...")
        sessions = source.parse_all(cutoff)
        print(f"  {len(sessions)} sessions")
        all_sessions.extend(sessions)
        source_names[source.key] = source.name

    # Apply project filter
    all_sessions = filter_sessions(all_sessions, projects=args.project)

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
