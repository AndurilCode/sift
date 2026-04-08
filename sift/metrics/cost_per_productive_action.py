from __future__ import annotations
from sift.sources.base import NormalizedSession
from sift.metrics.base import Metric, session_cost


class CostPerProductiveActionMetric(Metric):
    @property
    def key(self) -> str:
        return "cost_per_productive_action"

    @property
    def title(self) -> str:
        return "Cost per Productive Action"

    def compute(self, sessions: list[NormalizedSession]) -> dict:
        EDIT_NAMES = {"Edit", "edit", "replace_string_in_file", "multi_replace_string_in_file", "replace", "apply_patch"}
        WRITE_NAMES = {"Write", "create", "create_file", "write_file"}
        edits = writes = 0
        for s in sessions:
            tc = s.tool_calls
            edits += sum(tc.get(n, 0) for n in EDIT_NAMES)
            writes += sum(tc.get(n, 0) for n in WRITE_NAMES)
        productive = edits + writes
        total_cost = sum(session_cost(s) for s in sessions)
        return {
            "total_cost": total_cost,
            "productive_actions": productive,
            "cost_per_action": total_cost / max(productive, 1),
            "edits": edits,
            "writes": writes,
        }
