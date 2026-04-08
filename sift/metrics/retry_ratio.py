from __future__ import annotations
from collections import defaultdict
from sift.sources.base import NormalizedSession
from sift.metrics.base import Metric, MetricResult, session_cost, usd, tok


class RetryRatioMetric(Metric):
    """
    Measures token waste from repeated/retried tool calls within sessions.

    A "retry" is detected when the same tool is called consecutively
    (same tool name appears back-to-back in the tool_calls sequence).
    Since we only have aggregated tool_calls counts, we approximate using
    sessions where a single tool dominates (>60% of calls) as retry-heavy.
    """

    @property
    def key(self) -> str:
        return "retry_ratio"

    @property
    def title(self) -> str:
        return "Retry & Waste Ratio"

    @property
    def order(self) -> int:
        return 75

    def compute(self, sessions: list[NormalizedSession]) -> dict:
        retry_heavy = []
        normal = []
        tool_dominance = defaultdict(int)

        for s in sessions:
            tc = s.tool_calls
            total = s.total_tool_calls
            if total < 5:
                continue

            # Find most-called tool and its share
            if not tc:
                continue
            top_tool = max(tc, key=tc.get)
            top_count = tc[top_tool]
            dominance = top_count / total

            tool_dominance[top_tool] += 1

            # Bash-heavy sessions often indicate retry/debug loops
            bash_count = tc.get("Bash", 0) + tc.get("bash", 0) + tc.get("BashOutput", 0)
            bash_ratio = bash_count / total

            if dominance > 0.6 or bash_ratio > 0.5:
                retry_heavy.append(s)
            else:
                normal.append(s)

        retry_cost = sum(session_cost(s) for s in retry_heavy)
        total_cost = sum(session_cost(s) for s in retry_heavy + normal)
        retry_tokens = sum(s.total_tokens for s in retry_heavy)

        # Top tools in retry-heavy sessions
        retry_tools = defaultdict(int)
        for s in retry_heavy:
            for tool, count in s.tool_calls.items():
                retry_tools[tool] += count
        top_retry_tools = sorted(retry_tools.items(), key=lambda x: x[1], reverse=True)[:5]

        return {
            "retry_heavy_sessions": len(retry_heavy),
            "normal_sessions": len(normal),
            "total_measured": len(retry_heavy) + len(normal),
            "retry_ratio": len(retry_heavy) / max(len(retry_heavy) + len(normal), 1),
            "retry_cost": retry_cost,
            "retry_tokens": retry_tokens,
            "waste_cost_ratio": retry_cost / max(total_cost, 0.01),
            "top_retry_tools": top_retry_tools,
        }

    def report(self, data: dict, all_results: dict[str, MetricResult], ctx: dict) -> str:
        L = [f"## {self.title}\n"]
        L.append("Sessions with dominant single-tool or bash-heavy patterns "
                 "(likely retries/debug loops):\n")
        L.append("| Metric | Value |")
        L.append("|--------|-------|")
        L.append(f"| Retry-heavy sessions | {data['retry_heavy_sessions']:,} / {data['total_measured']:,} "
                 f"({data['retry_ratio']:.1%}) |")
        L.append(f"| Cost in retry-heavy | {usd(data['retry_cost'])} ({data['waste_cost_ratio']:.1%} of measured) |")
        L.append(f"| Tokens in retry-heavy | {tok(data['retry_tokens'])} |")
        L.append("")

        if data["top_retry_tools"]:
            L.append("Top tools in retry-heavy sessions:\n")
            L.append("| Tool | Calls |")
            L.append("|------|-------|")
            for tool, count in data["top_retry_tools"]:
                L.append(f"| {tool} | {count:,} |")
            L.append("")

        return "\n".join(L)
