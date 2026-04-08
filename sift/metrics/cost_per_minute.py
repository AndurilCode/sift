from __future__ import annotations
from sift.sources.base import NormalizedSession
from sift.metrics.base import Metric, session_cost


class CostPerMinuteMetric(Metric):
    @property
    def key(self) -> str:
        return "cost_per_minute"

    @property
    def title(self) -> str:
        return "Cost per Minute"

    def compute(self, sessions: list[NormalizedSession]) -> dict:
        total_cost = 0.0
        total_minutes = 0.0
        sessions_with_duration = 0
        per_session = []

        for s in sessions:
            cost = session_cost(s)
            dur = s.duration_seconds
            if not dur or dur <= 0:
                dur_ms = s.extras.get("api_duration_ms", 0)
                if dur_ms:
                    dur = dur_ms / 1000
            if dur and dur > 0:
                total_cost += cost
                total_minutes += dur / 60
                sessions_with_duration += 1
                per_session.append(cost / (dur / 60))

        per_session.sort()
        median_cpm = per_session[len(per_session) // 2] if per_session else 0

        return {
            "total_cost": total_cost,
            "total_minutes": total_minutes,
            "avg_cost_per_minute": total_cost / max(total_minutes, 0.01),
            "median_cost_per_minute": median_cpm,
            "sessions_measured": sessions_with_duration,
        }
