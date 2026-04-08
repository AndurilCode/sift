from __future__ import annotations
from collections import defaultdict
from sift.sources.base import NormalizedSession
from sift.metrics.base import Metric, MetricResult, session_cost, usd, tok


class ModelMixMetric(Metric):
    @property
    def key(self) -> str:
        return "model_mix"

    @property
    def title(self) -> str:
        return "Model Mix"

    @property
    def order(self) -> int:
        return 40

    def compute(self, sessions: list[NormalizedSession]) -> dict:
        models = defaultdict(lambda: {"sessions": 0, "total_tokens": 0, "output_tokens": 0, "tool_calls": 0, "cost": 0.0})
        for s in sessions:
            m = s.model or "unknown"
            models[m]["sessions"] += 1
            models[m]["total_tokens"] += s.total_tokens
            models[m]["output_tokens"] += s.usage.output_tokens
            models[m]["tool_calls"] += s.total_tool_calls
            models[m]["cost"] += session_cost(s)
        return dict(models)

    def report(self, data: dict, all_results: dict[str, MetricResult], ctx: dict) -> str:
        models = data
        sessions = ctx.get("sessions", [])

        L = [f"## {self.title}\n"]
        L.append("| Model | Sessions | Total Tokens | Output | Est. Cost | Cost % |")
        L.append("|-------|----------|--------------|--------|-----------|--------|")
        total_model_cost = sum(v["cost"] for v in models.values())
        for m, stats in sorted(models.items(), key=lambda x: x[1]["cost"], reverse=True):
            pct = (stats["cost"] / max(total_model_cost, 0.01)) * 100
            L.append(
                f"| {m} | {stats['sessions']:,} "
                f"| {tok(stats['total_tokens'])} "
                f"| {tok(stats['output_tokens'])} "
                f"| {usd(stats['cost'])} "
                f"| {pct:.1f}% |"
            )
        L.append("")

        # Opus misuse alert
        opus_short = [s for s in sessions if s.model and "opus" in s.model and s.total_tool_calls < 5]
        if opus_short:
            opus_cost = sum(session_cost(s) for s in opus_short)
            L.append(f"> **Model tier alert**: {len(opus_short)} Opus sessions with <5 tool calls "
                     f"(est. {usd(opus_cost)}). Consider Sonnet for lightweight tasks.\n")
        return "\n".join(L)
