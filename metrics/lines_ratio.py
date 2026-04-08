from __future__ import annotations
from sources.base import NormalizedSession
from metrics.base import Metric, median


class LinesRatioMetric(Metric):
    @property
    def key(self) -> str:
        return "lines_ratio"

    @property
    def title(self) -> str:
        return "Lines Ratio"

    def compute(self, sessions: list[NormalizedSession]) -> dict:
        total_read = 0
        total_generated = 0
        sessions_with_data = 0
        ratios = []

        for s in sessions:
            lr = s.extras.get("lines_read", 0)
            lg = s.extras.get("lines_generated", 0)
            if not lg:
                lg = s.extras.get("lines_added", 0)
            if lr or lg:
                sessions_with_data += 1
                total_read += lr
                total_generated += lg
                if lg > 0 and lr > 0:
                    ratios.append(lr / lg)

        ratios.sort()

        return {
            "total_lines_read": total_read,
            "total_lines_generated": total_generated,
            "read_to_generated_ratio": total_read / max(total_generated, 1),
            "median_ratio": median(ratios),
            "sessions_with_data": sessions_with_data,
            "sessions_with_ratio": len(ratios),
        }
