from __future__ import annotations
from collections import defaultdict
from sources.base import NormalizedSession
from metrics.base import Metric


class StopReasonDistributionMetric(Metric):
    @property
    def key(self) -> str:
        return "stop_reason_distribution"

    @property
    def title(self) -> str:
        return "Stop Reason Distribution"

    def compute(self, sessions: list[NormalizedSession]) -> dict:
        reasons = defaultdict(int)
        total = 0
        for s in sessions:
            sr = s.extras.get("stop_reasons", {})
            if isinstance(sr, dict):
                for reason, count in sr.items():
                    reasons[reason] += count
                    total += count
        pcts = {k: v / max(total, 1) for k, v in reasons.items()}
        return {"counts": dict(reasons), "percentages": pcts, "total": total}
