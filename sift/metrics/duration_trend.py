from __future__ import annotations
from collections import defaultdict
from sift.sources.base import NormalizedSession
from sift.metrics.base import Metric, MetricResult, median, usd


class DurationTrendMetric(Metric):
    """
    Tracks session duration over time — are sessions getting longer or shorter?

    Groups sessions by date, computes daily median duration and token count,
    plus 7-day rolling averages. Helps detect context bloat creep.
    """

    @property
    def key(self) -> str:
        return "duration_trend"

    @property
    def title(self) -> str:
        return "Session Duration Trend"

    @property
    def order(self) -> int:
        return 105

    def compute(self, sessions: list[NormalizedSession], window: int = 7) -> dict:
        daily_dur = defaultdict(list)
        daily_tok = defaultdict(list)

        for s in sessions:
            date = s.date
            if not date:
                continue
            if s.duration_seconds and s.duration_seconds > 0:
                daily_dur[date].append(s.duration_seconds / 60)  # minutes
            if s.total_tokens > 0:
                daily_tok[date].append(s.total_tokens)

        dates = sorted(set(daily_dur.keys()) | set(daily_tok.keys()))
        entries = []

        for i, date in enumerate(dates):
            dur_vals = daily_dur.get(date, [])
            tok_vals = daily_tok.get(date, [])

            # Rolling window
            window_dates = dates[max(0, i - window + 1):i + 1]
            all_dur = []
            all_tok = []
            for wd in window_dates:
                all_dur.extend(daily_dur.get(wd, []))
                all_tok.extend(daily_tok.get(wd, []))
            all_dur.sort()
            all_tok.sort()

            entries.append({
                "date": date,
                "sessions": len(dur_vals) + len([d for d in daily_tok.get(date, []) if date not in daily_dur]),
                "median_duration_min": median(sorted(dur_vals)) if dur_vals else None,
                "median_tokens": median(sorted(tok_vals)) if tok_vals else None,
                "rolling_median_dur": median(all_dur) if all_dur else None,
                "rolling_median_tok": median(all_tok) if all_tok else None,
            })

        # Overall trend: compare first half vs second half medians
        all_durs = []
        for s in sessions:
            if s.duration_seconds and s.duration_seconds > 0:
                all_durs.append(s.duration_seconds / 60)
        all_durs.sort()

        all_toks = sorted(s.total_tokens for s in sessions if s.total_tokens > 0)

        mid = len(all_durs) // 2
        first_half_dur = median(all_durs[:mid]) if mid > 0 else 0
        second_half_dur = median(all_durs[mid:]) if mid > 0 else 0

        mid_t = len(all_toks) // 2
        first_half_tok = median(all_toks[:mid_t]) if mid_t > 0 else 0
        second_half_tok = median(all_toks[mid_t:]) if mid_t > 0 else 0

        return {
            "entries": entries,
            "overall_median_dur": median(all_durs) if all_durs else 0,
            "first_half_median_dur": first_half_dur,
            "second_half_median_dur": second_half_dur,
            "dur_trend_pct": (second_half_dur - first_half_dur) / max(first_half_dur, 0.01),
            "overall_median_tok": median(all_toks) if all_toks else 0,
            "first_half_median_tok": first_half_tok,
            "second_half_median_tok": second_half_tok,
            "tok_trend_pct": (second_half_tok - first_half_tok) / max(first_half_tok, 1),
            "sessions_with_duration": len(all_durs),
        }

    def report(self, data: dict, all_results: dict[str, MetricResult], ctx: dict) -> str:
        L = [f"## {self.title}\n"]
        L.append("| Metric | Value |")
        L.append("|--------|-------|")
        L.append(f"| Sessions with duration | {data['sessions_with_duration']:,} |")
        if data["overall_median_dur"]:
            L.append(f"| Overall median duration | {data['overall_median_dur']:.1f} min |")
            L.append(f"| First half median | {data['first_half_median_dur']:.1f} min |")
            L.append(f"| Second half median | {data['second_half_median_dur']:.1f} min |")
            direction = "longer" if data["dur_trend_pct"] > 0 else "shorter"
            L.append(f"| Duration trend | {data['dur_trend_pct']:+.1%} ({direction}) |")
        if data["overall_median_tok"]:
            L.append(f"| Median tokens (1st half) | {data['first_half_median_tok']:,.0f} |")
            L.append(f"| Median tokens (2nd half) | {data['second_half_median_tok']:,.0f} |")
            tok_dir = "growing" if data["tok_trend_pct"] > 0 else "shrinking"
            L.append(f"| Token trend | {data['tok_trend_pct']:+.1%} ({tok_dir}) |")
        L.append("")

        if data["dur_trend_pct"] > 0.2:
            L.append(f"> **Trend alert**: Sessions are getting {data['dur_trend_pct']:.0%} longer. "
                     f"Check for context bloat or scope creep.\n")
        return "\n".join(L)
