from __future__ import annotations
from sift.sources.base import NormalizedSession
from sift.metrics.base import Metric, MetricResult, estimate_cost, session_cost, usd


class ChildMetric(Metric):
    @property
    def key(self) -> str:
        return "child_metrics"

    @property
    def title(self) -> str:
        return "Subagent & Compaction"

    @property
    def order(self) -> int:
        return 60

    def compute(self, sessions: list[NormalizedSession]) -> dict:
        all_children = []
        compaction_children = []
        for s in sessions:
            for child in s.children:
                all_children.append(child)
                if "acompact" in child.extras.get("subagent_file", ""):
                    compaction_children.append(child)

        child_cost = sum(estimate_cost(c.usage, c.model) for c in all_children)
        compaction_cost = sum(estimate_cost(c.usage, c.model) for c in compaction_children)
        total_cost = sum(session_cost(s) for s in sessions)
        parent_sessions_with_children_support = [s for s in sessions if s.children or s.source == "claude-code"]

        return {
            "child_count": len(all_children),
            "child_cost": child_cost,
            "child_cost_ratio": child_cost / max(total_cost, 0.01),
            "compaction_count": len(compaction_children),
            "compaction_cost": compaction_cost,
            "compaction_rate": len(compaction_children) / max(len(parent_sessions_with_children_support), 1),
        }

    def report(self, data: dict, all_results: dict[str, MetricResult], ctx: dict) -> str:
        children = data
        if children["child_count"] == 0:
            return ""

        L = [f"## {self.title}\n"]
        L.append("| Metric | Value | What it measures |")
        L.append("|--------|-------|------------------|")
        L.append(f"| Subagent sessions | {children['child_count']:,} | Total spawned |")
        L.append(f"| Subagent cost | {usd(children['child_cost'])} | Hidden multiplier |")
        L.append(f"| Subagent cost ratio | {children['child_cost_ratio']:.1%} | % of total cost |")
        L.append(f"| Compaction events | {children['compaction_count']:,} | Context window blown |")
        L.append(f"| Compaction cost | {usd(children['compaction_cost'])} | Summarization overhead |")
        L.append(f"| Compaction rate | {children['compaction_rate']:.1%} | % sessions triggering compaction |")
        L.append("")
        return "\n".join(L)
