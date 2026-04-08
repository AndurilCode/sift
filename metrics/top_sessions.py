from __future__ import annotations
from sources.base import NormalizedSession
from metrics.base import Metric, MetricResult, session_cost, usd, tok


class TopSessionsMetric(Metric):
    @property
    def key(self) -> str:
        return "top_sessions"

    @property
    def title(self) -> str:
        return "Most Costly Sessions"

    @property
    def order(self) -> int:
        return 120

    def compute(self, sessions: list[NormalizedSession]) -> dict:
        top = sorted(sessions, key=lambda s: s.total_tokens, reverse=True)[:25]
        # Store session data as dicts for the result, but also stash originals in context
        entries = []
        for s in top:
            cost = session_cost(s)
            entries.append({
                "session_id": s.session_id,
                "source": s.source,
                "project": s.project,
                "model": s.model,
                "total_tokens": s.total_tokens,
                "cost": cost,
                "timestamp_start": s.timestamp_start,
                "input_tokens": s.usage.input_tokens,
                "output_tokens": s.usage.output_tokens,
                "cache_read_tokens": s.usage.cache_read_tokens,
                "cache_write_tokens": s.usage.cache_write_tokens,
                "assistant_messages": s.assistant_messages,
                "total_tool_calls": s.total_tool_calls,
                "children_count": len(s.children),
                "duration_seconds": s.duration_seconds,
                "premium_requests": s.extras.get("premium_requests", 0),
                "lines_added": s.extras.get("lines_added", 0),
                "lines_removed": s.extras.get("lines_removed", 0),
                "summary": s.summary,
                "first_prompt": s.prompts[0]["text"] if s.prompts else "",
            })
        return {"entries": entries}

    def report(self, data: dict, all_results: dict[str, MetricResult], ctx: dict) -> str:
        source_names = ctx.get("source_names", {})
        L = [f"## {self.title}\n"]
        for i, e in enumerate(data["entries"], 1):
            L.append(f"### {i}. {e['project']} — {tok(e['total_tokens'])} tokens ({usd(e['cost'])})")
            L.append(f"- **Source**: {source_names.get(e['source'], e['source'])}")
            L.append(f"- **Session**: `{e['session_id']}`")
            if e["timestamp_start"]:
                L.append(f"- **Started**: {e['timestamp_start'][:19].replace('T', ' ')}")
            if e["model"]:
                L.append(f"- **Model**: {e['model']}")
            L.append(f"- **Tokens**: input={tok(e['input_tokens'])}, output={tok(e['output_tokens'])}, "
                     f"cache_read={tok(e['cache_read_tokens'])}, cache_write={tok(e['cache_write_tokens'])}")
            L.append(f"- **Messages**: {e['assistant_messages']}, Tool calls: {e['total_tool_calls']}, "
                     f"Children: {e['children_count']}")
            if e["duration_seconds"]:
                L.append(f"- **Duration**: {int(e['duration_seconds'] // 60)}m")
            if e["premium_requests"]:
                L.append(f"- **Premium requests**: {e['premium_requests']:,.1f}")
            if e["lines_added"] or e["lines_removed"]:
                L.append(f"- **Code changes**: +{e['lines_added']:,} / -{e['lines_removed']:,} lines")
            if e["summary"]:
                L.append(f"- **Summary**: {e['summary'][:300].replace(chr(10), ' ')}")
            elif e["first_prompt"]:
                L.append(f"- **First prompt**: {e['first_prompt'][:300].replace(chr(10), ' ')}")
            L.append("")
        return "\n".join(L)
