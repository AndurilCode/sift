from __future__ import annotations
from sources.base import NormalizedSession
from metrics.base import Metric


class ToolDefinitionOverheadMetric(Metric):
    @property
    def key(self) -> str:
        return "tool_definition_overhead"

    @property
    def title(self) -> str:
        return "Tool Definition Overhead"

    def compute(self, sessions: list[NormalizedSession]) -> dict:
        total_tool_def_tokens = 0
        total_context_tokens = 0
        sessions_measured = 0

        for s in sessions:
            ci = s.extras.get("context_info", {})
            if isinstance(ci, dict) and ci.get("tool_definitions_tokens"):
                total_tool_def_tokens += ci["tool_definitions_tokens"]
                total_context_tokens += ci.get("current_tokens", 0)
                sessions_measured += 1

        return {
            "tool_def_tokens": total_tool_def_tokens,
            "total_context_tokens": total_context_tokens,
            "overhead_ratio": total_tool_def_tokens / max(total_context_tokens, 1),
            "sessions_measured": sessions_measured,
        }
