from __future__ import annotations
from collections import defaultdict
from sources.base import NormalizedSession
from metrics.base import Metric, MetricResult, session_cost, usd


class ProjectAdoptionMetric(Metric):
    @property
    def key(self) -> str:
        return "project_adoption"

    @property
    def title(self) -> str:
        return "Project Adoption"

    @property
    def order(self) -> int:
        return 110

    def compute(self, sessions: list[NormalizedSession]) -> dict:
        projects = defaultdict(lambda: {
            "source": "", "sessions": 0, "cost": 0.0, "first_seen": "", "last_seen": "",
        })
        for s in sessions:
            p = projects[s.project]
            p["source"] = s.source
            p["sessions"] += 1
            p["cost"] += session_cost(s)
            ts = s.timestamp_start
            if ts and (not p["first_seen"] or ts < p["first_seen"]):
                p["first_seen"] = ts
            if ts and (not p["last_seen"] or ts > p["last_seen"]):
                p["last_seen"] = ts

        total = len(projects)
        multi = sum(1 for p in projects.values() if p["sessions"] > 1)

        return {
            "total_projects": total,
            "multi_session_projects": multi,
            "single_session_projects": total - multi,
            "adoption_depth_ratio": multi / max(total, 1),
            "projects": dict(projects),
        }

    def report(self, data: dict, all_results: dict[str, MetricResult], ctx: dict) -> str:
        adoption = data
        source_names = ctx.get("source_names", {})

        L = [f"## {self.title}\n"]
        L.append("| Metric | Value |")
        L.append("|--------|-------|")
        L.append(f"| Total projects | {adoption['total_projects']:,} |")
        L.append(f"| Multi-session (sustained) | {adoption['multi_session_projects']:,} |")
        L.append(f"| Single-session (one-off) | {adoption['single_session_projects']:,} |")
        L.append(f"| Adoption depth ratio | {adoption['adoption_depth_ratio']:.1%} |")
        L.append("")

        L.append("### Top Projects by Cost\n")
        L.append("| Project | Source | Sessions | Est. Cost | First Seen | Last Seen |")
        L.append("|---------|--------|----------|-----------|------------|-----------|")
        sorted_projects = sorted(adoption["projects"].items(), key=lambda x: x[1]["cost"], reverse=True)
        for name, info in sorted_projects[:30]:
            first = info["first_seen"][:10] if info["first_seen"] else "?"
            last = info["last_seen"][:10] if info["last_seen"] else "?"
            L.append(
                f"| {name} | {source_names.get(info['source'], info['source'])} | {info['sessions']} "
                f"| {usd(info['cost'])} | {first} | {last} |"
            )
        L.append("")
        return "\n".join(L)
