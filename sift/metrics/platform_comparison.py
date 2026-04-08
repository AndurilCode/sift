from __future__ import annotations
from collections import defaultdict
from sift.sources.base import NormalizedSession
from sift.metrics.base import Metric, MetricResult, estimate_cost, flatten_with_children, usd, tok


class PlatformComparisonMetric(Metric):
    @property
    def key(self) -> str:
        return "platform_comparison"

    @property
    def title(self) -> str:
        return "Platform Comparison"

    @property
    def order(self) -> int:
        return 20

    def compute(self, sessions: list[NormalizedSession]) -> dict:
        by_source = defaultdict(list)
        for s in sessions:
            by_source[s.source].append(s)

        result = {}
        for source, source_sessions in sorted(by_source.items()):
            all_with_children = flatten_with_children(source_sessions)
            total_cost = sum(estimate_cost(s.usage, s.model) for s in all_with_children)
            total_tokens = sum(s.total_tokens for s in all_with_children)
            total_output = sum(s.usage.output_tokens for s in all_with_children)
            total_tools = sum(s.total_tool_calls for s in source_sessions)
            total_premium = sum(s.extras.get("premium_requests", 0) for s in source_sessions)
            n = len(source_sessions)
            result[source] = {
                "sessions": n,
                "total_tokens": total_tokens,
                "total_output": total_output,
                "total_cost": total_cost,
                "avg_tokens_per_session": total_tokens // max(n, 1),
                "avg_cost_per_session": total_cost / max(n, 1),
                "total_tool_calls": total_tools,
                "premium_requests": total_premium,
            }
        return result

    def report(self, data: dict, all_results: dict[str, MetricResult], ctx: dict) -> str:
        comparison = data
        source_names = ctx.get("source_names", {})
        if not comparison:
            return ""

        L = [f"## {self.title}\n"]
        headers = ["Metric"] + [source_names.get(k, k) for k in sorted(comparison)]
        L.append("| " + " | ".join(headers) + " |")
        L.append("|" + "|".join("---" for _ in headers) + "|")

        rows = [
            ("Sessions", lambda v: f"{v['sessions']:,}"),
            ("Total tokens", lambda v: tok(v['total_tokens'])),
            ("Output tokens", lambda v: tok(v['total_output'])),
            ("Estimated cost", lambda v: usd(v['total_cost'])),
            ("Avg tokens/session", lambda v: tok(v['avg_tokens_per_session'])),
            ("Avg cost/session", lambda v: usd(v['avg_cost_per_session'])),
            ("Tool calls", lambda v: f"{v['total_tool_calls']:,}"),
            ("Premium requests", lambda v: f"{v['premium_requests']:,.1f}" if v['premium_requests'] else "—"),
        ]
        for label, fmt in rows:
            cells = [label] + [fmt(comparison[k]) for k in sorted(comparison)]
            L.append("| " + " | ".join(cells) + " |")
        L.append("")
        return "\n".join(L)
