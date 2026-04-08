"""
Export all metrics and per-session data as a single JSON file.

Designed for ingestion by pipelines, agents, or downstream analysis tools.
The schema is self-describing: every metric includes its key, title, and
computed data dict. Sessions include normalized fields plus computed cost.
"""

from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path

from sift.sources.base import NormalizedSession
from sift.metrics import compute_all, get_all_metrics, session_cost, estimate_cost

OUTPUT_DIR = Path.home() / ".sift"


def _session_record(s: NormalizedSession) -> dict:
    """Flatten a session into a JSON-safe dict with computed fields."""
    cost = session_cost(s)
    child_cost = sum(estimate_cost(c.usage, c.model) for c in s.children)
    tc = s.tool_calls

    return {
        "session_id": s.session_id,
        "source": s.source,
        "project": s.project,
        "date": s.date,
        "timestamp_start": s.timestamp_start,
        "timestamp_end": s.timestamp_end,
        "duration_seconds": s.duration_seconds,
        "model": s.model,
        "cost_usd": round(cost, 4),
        "tokens": {
            "total": s.total_tokens,
            "input": s.usage.input_tokens,
            "output": s.usage.output_tokens,
            "cache_read": s.usage.cache_read_tokens,
            "cache_write": s.usage.cache_write_tokens,
        },
        "activity": {
            "assistant_messages": s.assistant_messages,
            "turns": s.turns,
            "total_tool_calls": s.total_tool_calls,
            "tool_calls": dict(s.tool_calls),
            "edits": tc.get("Edit", 0) + tc.get("edit", 0) + tc.get("replace_string_in_file", 0) + tc.get("multi_replace_string_in_file", 0) + tc.get("replace", 0) + tc.get("apply_patch", 0),
            "writes": tc.get("Write", 0) + tc.get("create", 0) + tc.get("create_file", 0) + tc.get("write_file", 0),
            "reads": tc.get("Read", 0) + tc.get("view", 0) + tc.get("read_file", 0) + tc.get("read_many_files", 0),
        },
        "children": {
            "count": len(s.children),
            "cost_usd": round(child_cost, 4),
        },
        "extras": {
            k: v for k, v in s.extras.items()
            if k not in ("file",)  # skip internal-only fields
        },
    }


def generate(sessions: list[NormalizedSession], source_names: dict[str, str], cutoff=None) -> Path:
    """Generate the JSON export. Returns file path."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    export_path = OUTPUT_DIR / "export.json"

    results = compute_all(sessions)

    # Build metrics section: {key: {title, order, data}}
    metrics = {}
    for m in get_all_metrics():
        r = results[m.key]
        metrics[m.key] = {
            "title": r.title,
            "order": m.order,
            "data": r.data,
        }

    payload = {
        "_schema": "sift-export-v1",
        "_description": "Sift — AI coding assistant usage metrics and per-session data. "
                        "Metrics are pre-computed aggregates. Sessions are raw records "
                        "with normalized fields and computed cost.",
        "generated": datetime.now().isoformat(),
        "range": {
            "cutoff": cutoff.isoformat() if cutoff else None,
            "first_session": min((s.date for s in sessions if s.date), default=None),
            "last_session": max((s.date for s in sessions if s.date), default=None),
        },
        "sources": {k: v for k, v in sorted(source_names.items())},
        "summary": {
            "total_sessions": len(sessions),
            "total_cost_usd": round(sum(session_cost(s) for s in sessions), 2),
            "total_tokens": sum(s.total_tokens for s in sessions),
            "total_tool_calls": sum(s.total_tool_calls for s in sessions),
            "projects": len(set(s.project for s in sessions)),
        },
        "metrics": metrics,
        "sessions": [_session_record(s) for s in sessions],
    }

    with open(export_path, "w") as f:
        json.dump(payload, f, indent=2, default=str)

    print(f"Export: {export_path}")
    return export_path
