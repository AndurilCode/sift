from __future__ import annotations
from sources.base import NormalizedSession
from metrics.base import Metric, flatten_with_children


class OutputRatioMetric(Metric):
    @property
    def key(self) -> str:
        return "output_ratio"

    @property
    def title(self) -> str:
        return "Output Ratio"

    def compute(self, sessions: list[NormalizedSession]) -> dict:
        all_flat = flatten_with_children(sessions)
        total_output = sum(s.usage.output_tokens for s in all_flat)
        total_all = sum(s.total_tokens for s in all_flat)
        total_fresh = sum(s.usage.input_tokens + s.usage.output_tokens + s.usage.cache_write_tokens for s in all_flat)
        return {
            "gross": total_output / max(total_all, 1),
            "net": total_output / max(total_fresh, 1),
        }
