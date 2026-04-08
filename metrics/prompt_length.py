from __future__ import annotations
from sources.base import NormalizedSession
from metrics.base import Metric, MetricResult, median, percentile


class PromptLengthMetric(Metric):
    """
    Analyzes user prompt sizes to understand specification patterns.

    Long prompts may indicate over-specification (paste-heavy workflows).
    Very short prompts may indicate under-specification (vague requests
    leading to excessive exploration).
    """

    @property
    def key(self) -> str:
        return "prompt_length"

    @property
    def title(self) -> str:
        return "Prompt Length Distribution"

    @property
    def order(self) -> int:
        return 76

    def compute(self, sessions: list[NormalizedSession]) -> dict:
        lengths = []  # char counts per prompt
        session_avg_lengths = []  # avg prompt length per session

        for s in sessions:
            if not s.prompts:
                continue
            sess_lengths = []
            for p in s.prompts:
                text = p.get("text", "")
                if isinstance(text, str) and text.strip():
                    n = len(text)
                    lengths.append(n)
                    sess_lengths.append(n)
            if sess_lengths:
                session_avg_lengths.append(sum(sess_lengths) / len(sess_lengths))

        lengths.sort()
        session_avg_lengths.sort()

        # Buckets
        buckets = {"<50": 0, "50-200": 0, "200-500": 0, "500-2K": 0, "2K-10K": 0, "10K+": 0}
        for n in lengths:
            if n < 50:
                buckets["<50"] += 1
            elif n < 200:
                buckets["50-200"] += 1
            elif n < 500:
                buckets["200-500"] += 1
            elif n < 2000:
                buckets["500-2K"] += 1
            elif n < 10000:
                buckets["2K-10K"] += 1
            else:
                buckets["10K+"] += 1

        return {
            "total_prompts": len(lengths),
            "sessions_with_prompts": len(session_avg_lengths),
            "median_length": median(lengths),
            "avg_length": sum(lengths) / max(len(lengths), 1),
            "p90_length": percentile(lengths, 90),
            "max_length": max(lengths) if lengths else 0,
            "median_session_avg": median(session_avg_lengths),
            "buckets": buckets,
            "short_prompts": buckets["<50"],
            "long_prompts": buckets["10K+"],
        }

    def report(self, data: dict, all_results: dict[str, MetricResult], ctx: dict) -> str:
        L = [f"## {self.title}\n"]
        L.append("| Metric | Value |")
        L.append("|--------|-------|")
        L.append(f"| Total prompts analyzed | {data['total_prompts']:,} |")
        L.append(f"| Median prompt length | {data['median_length']:,.0f} chars |")
        L.append(f"| Average prompt length | {data['avg_length']:,.0f} chars |")
        L.append(f"| P90 prompt length | {data['p90_length']:,.0f} chars |")
        L.append(f"| Max prompt length | {data['max_length']:,.0f} chars |")
        L.append(f"| Median per-session avg | {data['median_session_avg']:,.0f} chars |")
        L.append("")

        L.append("### Distribution\n")
        L.append("| Bucket | Count | % |")
        L.append("|--------|-------|---|")
        total = max(data["total_prompts"], 1)
        for bucket, count in data["buckets"].items():
            L.append(f"| {bucket} | {count:,} | {count/total:.1%} |")
        L.append("")

        if data["short_prompts"] / max(total, 1) > 0.4:
            L.append(f"> **Under-specification risk**: {data['short_prompts']/total:.0%} of prompts "
                     f"are under 50 chars. Short prompts often cause excessive exploration.\n")
        if data["long_prompts"] / max(total, 1) > 0.1:
            L.append(f"> **Over-specification risk**: {data['long_prompts']/total:.0%} of prompts "
                     f"are over 10K chars. Consider using files or CLAUDE.md instead of pasting.\n")

        return "\n".join(L)
