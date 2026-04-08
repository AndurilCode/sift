from __future__ import annotations
from sift.sources.base import NormalizedSession
from sift.metrics.base import Metric, flatten_with_children


class InputFreshnessMetric(Metric):
    @property
    def key(self) -> str:
        return "input_freshness"

    @property
    def title(self) -> str:
        return "Input Freshness"

    def compute(self, sessions: list[NormalizedSession]) -> dict:
        all_flat = flatten_with_children(sessions)
        total_input = sum(s.usage.input_tokens for s in all_flat)
        total_cache_read = sum(s.usage.cache_read_tokens for s in all_flat)
        total_all = total_input + total_cache_read
        freshness = total_input / max(total_all, 1)
        return {
            "input_tokens": total_input,
            "cache_read_tokens": total_cache_read,
            "freshness_ratio": freshness,
            "is_healthy": freshness < 0.10,
        }
