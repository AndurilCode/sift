from __future__ import annotations
from sift.sources.base import NormalizedSession
from sift.metrics.base import Metric


class ContextAccumulationMetric(Metric):
    @property
    def key(self) -> str:
        return "context_accumulation"

    @property
    def title(self) -> str:
        return "Context Accumulation"

    def compute(self, sessions: list[NormalizedSession]) -> dict:
        total_tokens = 0
        total_messages = 0
        rates = []

        for s in sessions:
            if s.assistant_messages > 0 and s.total_tokens > 0:
                rate = s.total_tokens / s.assistant_messages
                rates.append(rate)
                total_tokens += s.total_tokens
                total_messages += s.assistant_messages

        rates.sort()
        median_rate = rates[len(rates) // 2] if rates else 0

        return {
            "avg_tokens_per_message": total_tokens / max(total_messages, 1),
            "median_tokens_per_message": median_rate,
            "total_messages": total_messages,
        }
