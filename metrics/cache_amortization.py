from __future__ import annotations
from sources.base import NormalizedSession
from metrics.base import Metric, flatten_with_children


class CacheAmortizationMetric(Metric):
    @property
    def key(self) -> str:
        return "cache_amortization"

    @property
    def title(self) -> str:
        return "Cache Amortization"

    def compute(self, sessions: list[NormalizedSession]) -> dict:
        all_flat = flatten_with_children(sessions)
        total_read = sum(s.usage.cache_read_tokens for s in all_flat)
        total_write = sum(s.usage.cache_write_tokens for s in all_flat)
        ratio = total_read / max(total_write, 1)
        return {
            "cache_read_tokens": total_read,
            "cache_write_tokens": total_write,
            "amortization_ratio": ratio,
            "is_net_positive": ratio > 1,
        }
