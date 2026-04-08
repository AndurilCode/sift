from __future__ import annotations
from sift.sources.base import NormalizedSession
from sift.metrics.base import Metric, MetricResult, median, percentile, tok


class SessionHealthMetric(Metric):
    @property
    def key(self) -> str:
        return "session_health"

    @property
    def title(self) -> str:
        return "Session Health"

    @property
    def order(self) -> int:
        return 80

    def compute(self, sessions: list[NormalizedSession]) -> dict:
        tokens = sorted(s.total_tokens for s in sessions if s.total_tokens > 0)
        durations = sorted(
            s.duration_seconds for s in sessions
            if s.duration_seconds and s.duration_seconds > 0
        )

        med = median(tokens)
        total_tools = sum(s.total_tool_calls for s in sessions)
        total_tokens = sum(s.total_tokens for s in sessions)

        return {
            "session_count": len(sessions),
            "median_tokens": med,
            "p90_tokens": percentile(tokens, 90),
            "p99_tokens": percentile(tokens, 99),
            "max_tokens": max(tokens) if tokens else 0,
            "bloat_index": (max(tokens) / max(med, 1)) if tokens else 0,
            "sessions_over_50m": sum(1 for t in tokens if t > 50_000_000),
            "median_duration_min": median(durations) / 60 if durations else 0,
            "p90_duration_min": percentile(durations, 90) / 60 if durations else 0,
            "tokens_per_tool_call": total_tokens / max(total_tools, 1),
        }

    def report(self, data: dict, all_results: dict[str, MetricResult], ctx: dict) -> str:
        health = data
        L = [f"## {self.title}\n"]
        L.append("| Metric | Value | What it measures |")
        L.append("|--------|-------|------------------|")
        L.append(f"| Median tokens/session | {tok(health['median_tokens'])} | Typical size |")
        L.append(f"| P90 tokens/session | {tok(health['p90_tokens'])} | Heavy threshold |")
        L.append(f"| P99 tokens/session | {tok(health['p99_tokens'])} | Outlier threshold |")
        L.append(f"| Max tokens | {tok(health['max_tokens'])} | Costliest session |")
        L.append(f"| Bloat index | {health['bloat_index']:.0f}x | Max / median skew |")
        L.append(f"| Sessions >50M tokens | {health['sessions_over_50m']} | Runaway count |")
        if health["median_duration_min"] > 0:
            L.append(f"| Median duration | {health['median_duration_min']:.1f} min | Typical length |")
            L.append(f"| P90 duration | {health['p90_duration_min']:.1f} min | Long session threshold |")
        L.append("")
        return "\n".join(L)
