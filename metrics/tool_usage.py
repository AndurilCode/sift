from __future__ import annotations
from collections import defaultdict
from sources.base import NormalizedSession
from metrics.base import Metric, MetricResult


class ToolUsageMetric(Metric):
    @property
    def key(self) -> str:
        return "tool_usage"

    @property
    def title(self) -> str:
        return "Tool Usage"

    @property
    def order(self) -> int:
        return 90

    def compute(self, sessions: list[NormalizedSession]) -> dict:
        tools = defaultdict(lambda: {"calls": 0, "sessions": 0})
        for s in sessions:
            for tool_name, count in s.tool_calls.items():
                tools[tool_name]["calls"] += count
                tools[tool_name]["sessions"] += 1
        return dict(tools)

    def report(self, data: dict, all_results: dict[str, MetricResult], ctx: dict) -> str:
        tools = data
        if not tools:
            return ""

        L = [f"## {self.title}\n"]
        L.append("| Tool | Total Calls | Sessions |")
        L.append("|------|-------------|----------|")
        for name, stats in sorted(tools.items(), key=lambda x: x[1]["calls"], reverse=True)[:25]:
            L.append(f"| {name} | {stats['calls']:,} | {stats['sessions']:,} |")
        L.append("")
        return "\n".join(L)
