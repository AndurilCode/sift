from __future__ import annotations
from collections import defaultdict
from sources.base import NormalizedSession
from metrics.base import Metric, MetricResult, session_cost, usd


class DailyBurnMetric(Metric):
    @property
    def key(self) -> str:
        return "daily_burn"

    @property
    def title(self) -> str:
        return "Daily Burn Rate"

    @property
    def order(self) -> int:
        return 100

    def compute(self, sessions: list[NormalizedSession], window: int = 7) -> dict:
        daily_cost = defaultdict(float)
        daily_sessions = defaultdict(lambda: defaultdict(int))
        daily_premium = defaultdict(float)

        for s in sessions:
            date = s.date
            if not date:
                continue
            daily_cost[date] += session_cost(s)
            daily_sessions[date][s.source] += 1
            daily_premium[date] += s.extras.get("premium_requests", 0)

        dates = sorted(daily_cost.keys())
        entries = []
        for i, date in enumerate(dates):
            window_dates = dates[max(0, i - window + 1):i + 1]
            rolling_avg = sum(daily_cost[d] for d in window_dates) / len(window_dates)
            entries.append({
                "date": date,
                "cost": daily_cost[date],
                "rolling_avg": rolling_avg,
                "premium_requests": daily_premium[date],
                "sessions_by_source": dict(daily_sessions[date]),
            })
        return {"entries": entries}

    def report(self, data: dict, all_results: dict[str, MetricResult], ctx: dict) -> str:
        burn = data["entries"]
        source_names = ctx.get("source_names", {})
        comparison = all_results["platform_comparison"].data

        L = [f"## {self.title} (7-day rolling avg)\n"]
        source_keys = sorted(comparison.keys())
        src_headers = " | ".join(source_names.get(k, k) for k in source_keys)
        L.append(f"| Date | Cost | 7d Avg | {src_headers} | Premium |")
        L.append("|------|------|--------|" + "|".join("---" for _ in source_keys) + "|---------|")
        for entry in burn:
            src_cols = " | ".join(str(entry["sessions_by_source"].get(k, 0)) for k in source_keys)
            prem = f"{entry['premium_requests']:,.1f}" if entry["premium_requests"] else ""
            L.append(
                f"| {entry['date']} | {usd(entry['cost'])} | {usd(entry['rolling_avg'])} "
                f"| {src_cols} | {prem} |"
            )
        L.append("")
        return "\n".join(L)
