from __future__ import annotations
from sources.base import NormalizedSession
from metrics.base import Metric, MetricResult, tok


class ContextEfficiencyMetric(Metric):
    """Composite report section pulling from output_ratio, context_accumulation,
    cache_amortization, input_freshness, tool_definition_overhead, stop_reason_distribution."""

    @property
    def key(self) -> str:
        return "context_efficiency"

    @property
    def title(self) -> str:
        return "Context Efficiency"

    @property
    def order(self) -> int:
        return 55

    def compute(self, sessions: list[NormalizedSession]) -> dict:
        # No unique data — this metric aggregates others for reporting
        return {}

    def report(self, data: dict, all_results: dict[str, MetricResult], ctx: dict) -> str:
        or_data = all_results["output_ratio"].data
        or_net = or_data["net"]
        or_gross = or_data["gross"]
        ctx_accum = all_results["context_accumulation"].data
        ca = all_results["cache_amortization"].data
        freshness = all_results["input_freshness"].data
        tool_overhead = all_results["tool_definition_overhead"].data
        stop_reasons = all_results["stop_reason_distribution"].data

        L = [f"## {self.title}\n"]
        L.append("| Metric | Value | What it measures |")
        L.append("|--------|-------|------------------|")
        L.append(f"| Output ratio (net) | {or_net:.2%} | Output vs fresh input |")
        L.append(f"| Output ratio (gross) | {or_gross:.2%} | Output vs all tokens incl. cache |")
        L.append(f"| Context accumulation rate | {tok(int(ctx_accum['avg_tokens_per_message']))} tok/msg | Avg context consumed per assistant turn |")
        L.append(f"| Median accumulation rate | {tok(int(ctx_accum['median_tokens_per_message']))} tok/msg | Typical per-turn context cost |")
        L.append(f"| Cache write amortization | {ca['amortization_ratio']:.1f}x | Cache reads per write (>1 = profitable) |")
        L.append(f"| Input freshness | {freshness['freshness_ratio']:.1%} | Uncached input ratio (<10% = stable prompts) |")
        if tool_overhead["sessions_measured"] > 0:
            L.append(f"| Tool definition overhead | {tool_overhead['overhead_ratio']:.1%} | Context consumed by tool schemas ({tool_overhead['sessions_measured']} sessions) |")
        if stop_reasons["total"] > 0:
            parts = []
            for reason, pct in sorted(stop_reasons["percentages"].items(), key=lambda x: x[1], reverse=True):
                parts.append(f"{reason}={pct:.0%}")
            L.append(f"| Stop reasons | {', '.join(parts)} | end_turn=normal, tool_use=agentic, max_tokens=truncated |")
        L.append("")
        return "\n".join(L)
