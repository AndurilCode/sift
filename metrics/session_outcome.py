from __future__ import annotations
from sources.base import NormalizedSession
from metrics.base import Metric, MetricResult, session_cost, usd


class SessionOutcomeMetric(Metric):
    """
    Heuristic success/failure classification for sessions.

    Success signals: session ends with Edit/Write, commit, PR creation, or
    test passing.  Failure signals: max_tokens hit, compaction triggered,
    excessive retries, or zero productive actions despite many tool calls.
    """

    @property
    def key(self) -> str:
        return "session_outcome"

    @property
    def title(self) -> str:
        return "Session Outcome"

    @property
    def order(self) -> int:
        return 85

    # Tool names that count as productive output
    _PRODUCTIVE = {
        "Edit", "Write", "edit", "write", "create", "create_file",
        "write_file", "replace_string_in_file", "multi_replace_string_in_file",
        "replace", "apply_patch", "NotebookEdit",
    }

    # Tool names suggesting a successful commit / PR
    _COMMIT_TOOLS = {"Bash"}  # commit/PR happen via Bash

    def _classify(self, s: NormalizedSession) -> str:
        """Return 'success', 'failure', or 'inconclusive'."""
        tc = s.tool_calls
        stop = s.extras.get("stop_reasons", {})
        productive = sum(tc.get(t, 0) for t in self._PRODUCTIVE)
        total_tools = s.total_tool_calls

        # Hard failure: max_tokens dominated
        max_tok_count = stop.get("max_tokens", 0)
        total_stops = sum(stop.values()) if stop else 0
        if total_stops > 0 and max_tok_count / total_stops > 0.3:
            return "failure"

        # Hard failure: compaction child present (context blowup)
        compactions = sum(
            1 for c in s.children
            if "acompact" in c.extras.get("subagent_file", "")
        )
        if compactions > 0 and productive == 0:
            return "failure"

        # Failure: many tool calls but zero productive actions
        if total_tools >= 10 and productive == 0:
            return "failure"

        # Success: had productive actions
        if productive > 0:
            return "success"

        # Inconclusive: too few signals
        if total_tools < 3:
            return "inconclusive"

        return "inconclusive"

    def compute(self, sessions: list[NormalizedSession]) -> dict:
        outcomes = {"success": [], "failure": [], "inconclusive": []}
        for s in sessions:
            cat = self._classify(s)
            outcomes[cat].append(s)

        n = len(sessions)
        success_n = len(outcomes["success"])
        failure_n = len(outcomes["failure"])
        incon_n = len(outcomes["inconclusive"])

        success_cost = sum(session_cost(s) for s in outcomes["success"])
        failure_cost = sum(session_cost(s) for s in outcomes["failure"])

        return {
            "total": n,
            "success": success_n,
            "failure": failure_n,
            "inconclusive": incon_n,
            "success_rate": success_n / max(n, 1),
            "failure_rate": failure_n / max(n, 1),
            "success_cost": success_cost,
            "failure_cost": failure_cost,
            "wasted_cost_ratio": failure_cost / max(success_cost + failure_cost, 0.01),
        }

    def report(self, data: dict, all_results: dict[str, MetricResult], ctx: dict) -> str:
        L = [f"## {self.title}\n"]
        L.append("| Outcome | Sessions | % | Est. Cost |")
        L.append("|---------|----------|---|-----------|")
        for cat in ("success", "failure", "inconclusive"):
            n = data[cat]
            pct = n / max(data["total"], 1) * 100
            cost = data.get(f"{cat}_cost", 0)
            cost_str = usd(cost) if cost else "—"
            L.append(f"| {cat.capitalize()} | {n:,} | {pct:.1f}% | {cost_str} |")
        L.append("")
        if data["failure"] > 0:
            L.append(
                f"> **Waste alert**: {data['failure']:,} sessions classified as failures "
                f"({usd(data['failure_cost'])}). "
                f"Wasted cost ratio: {data['wasted_cost_ratio']:.1%} of classifiable spend.\n"
            )
        return "\n".join(L)
