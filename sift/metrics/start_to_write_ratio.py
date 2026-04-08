from __future__ import annotations
from sift.sources.base import NormalizedSession
from sift.metrics.base import Metric, median, percentile


class StartToWriteRatioMetric(Metric):
    @property
    def key(self) -> str:
        return "start_to_write_ratio"

    @property
    def title(self) -> str:
        return "Start to Write Ratio"

    def compute(self, sessions: list[NormalizedSession]) -> dict:
        values = []
        never_wrote = 0
        wrote_first = 0

        for s in sessions:
            tbfw = s.extras.get("turns_before_first_write")
            if tbfw is None:
                if s.total_tool_calls > 0:
                    never_wrote += 1
            else:
                values.append(tbfw)
                if tbfw == 0:
                    wrote_first += 1

        values.sort()
        n = len(values)

        return {
            "sessions_measured": n,
            "sessions_never_wrote": never_wrote,
            "sessions_wrote_first": wrote_first,
            "avg_turns_before_write": sum(values) / max(n, 1),
            "median_turns_before_write": median(values),
            "p90_turns_before_write": percentile(values, 90),
            "max_turns_before_write": max(values) if values else 0,
        }
