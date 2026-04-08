from __future__ import annotations
from sources.base import NormalizedSession
from metrics.base import Metric, MetricResult, session_cost, usd, tok


class CostEfficiencyMetric(Metric):
    @property
    def key(self) -> str:
        return "cost_efficiency"

    @property
    def title(self) -> str:
        return "Cost Efficiency"

    @property
    def order(self) -> int:
        return 30

    def compute(self, sessions: list[NormalizedSession]) -> dict:
        total_cost = 0.0
        total_output = 0
        total_tools = 0
        n = 0

        for s in sessions:
            cost = session_cost(s)
            total_cost += cost
            total_output += s.usage.output_tokens
            total_tools += s.total_tool_calls
            n += 1

        return {
            "total_cost_usd": total_cost,
            "total_sessions": n,
            "total_output_tokens": total_output,
            "total_tool_calls": total_tools,
            "cost_per_session": total_cost / max(n, 1),
            "output_per_session": total_output / max(n, 1),
            "tools_per_session": total_tools / max(n, 1),
            "cost_per_1k_output": (total_cost / max(total_output, 1)) * 1000,
            "cost_per_tool_call": total_cost / max(total_tools, 1),
        }

    def report(self, data: dict, all_results: dict[str, MetricResult], ctx: dict) -> str:
        eff = data
        cppa = all_results["cost_per_productive_action"].data
        cpm = all_results["cost_per_minute"].data
        or_data = all_results["output_ratio"].data
        health = all_results["session_health"].data
        or_net = or_data["net"]
        or_gross = or_data["gross"]

        L = [f"## {self.title}\n"]
        L.append("| Metric | Value | What it measures |")
        L.append("|--------|-------|------------------|")
        L.append(f"| Cost per session | {usd(eff['cost_per_session'])} | Unit economics |")
        L.append(f"| Cost per 1K output tokens | {usd(eff['cost_per_1k_output'])} | Generation efficiency |")
        L.append(f"| Cost per tool call | {usd(eff['cost_per_tool_call'])} | Action efficiency |")
        L.append(f"| Cost per productive action | {usd(cppa['cost_per_action'])} | Cost per Edit/Write ({cppa['productive_actions']:,} actions) |")
        if cpm["sessions_measured"] > 0:
            L.append(f"| Cost per minute | {usd(cpm['avg_cost_per_minute'])} | Time-normalized spend (median {usd(cpm['median_cost_per_minute'])}) |")
        L.append(f"| Output tokens/session | {tok(int(eff['output_per_session']))} | Productivity proxy |")
        L.append(f"| Tool calls/session | {eff['tools_per_session']:.1f} | Session depth |")
        L.append(f"| Output ratio (net) | {or_net:.2%} | Output vs fresh input (excl. cache reads) |")
        L.append(f"| Output ratio (gross) | {or_gross:.2%} | Output vs all tokens (incl. cache replay) |")
        L.append(f"| Tokens per tool call | {tok(int(health['tokens_per_tool_call']))} | Context cost per action |")
        L.append("")
        return "\n".join(L)
