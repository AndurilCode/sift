from __future__ import annotations
from sift.sources.base import NormalizedSession
from sift.metrics.base import Metric, MetricResult, estimate_cost, usd


class ModelRoutingMetric(Metric):
    """
    Estimates savings from optimal model routing.

    For each session using an expensive model (Opus), estimates what it
    would have cost with a cheaper adequate model (Sonnet for light tasks,
    Haiku for subagents).  "Light" = fewer than N tool calls or low output.
    """

    @property
    def key(self) -> str:
        return "model_routing"

    @property
    def title(self) -> str:
        return "Model Routing Efficiency"

    @property
    def order(self) -> int:
        return 45

    # Thresholds for "lightweight" sessions
    LIGHT_TOOL_THRESHOLD = 10
    LIGHT_OUTPUT_THRESHOLD = 5000  # output tokens

    def _downgrade_target(self, s: NormalizedSession) -> str | None:
        """Return target model key if session could be downgraded, else None."""
        model = (s.model or "").lower()

        # Subagents → Haiku
        if s.is_child and "haiku" not in model:
            return "claude-haiku-4.5"

        # Opus light sessions → Sonnet
        if "opus" in model:
            if (s.total_tool_calls < self.LIGHT_TOOL_THRESHOLD
                    or s.usage.output_tokens < self.LIGHT_OUTPUT_THRESHOLD):
                return "claude-sonnet-4.6"

        return None

    def _cost_with_model(self, s: NormalizedSession, target_model: str) -> float:
        """Re-estimate cost as if session used target_model."""
        return estimate_cost(s.usage, target_model)

    def compute(self, sessions: list[NormalizedSession]) -> dict:
        # Flatten to include children
        all_sessions = []
        for s in sessions:
            all_sessions.append(s)
            all_sessions.extend(s.children)

        total_cost = sum(estimate_cost(s.usage, s.model) for s in all_sessions)
        downgradeable = []
        potential_savings = 0.0
        by_route = {}  # "opus→sonnet": {count, savings}

        for s in all_sessions:
            target = self._downgrade_target(s)
            if not target:
                continue

            current_cost = estimate_cost(s.usage, s.model)
            target_cost = self._cost_with_model(s, target)
            saving = current_cost - target_cost
            if saving <= 0:
                continue

            route_key = f"{s.model} → {target}"
            if route_key not in by_route:
                by_route[route_key] = {"count": 0, "savings": 0.0, "current_cost": 0.0}
            by_route[route_key]["count"] += 1
            by_route[route_key]["savings"] += saving
            by_route[route_key]["current_cost"] += current_cost

            downgradeable.append(s)
            potential_savings += saving

        optimal_cost = total_cost - potential_savings
        efficiency = optimal_cost / max(total_cost, 0.01)

        return {
            "total_cost": total_cost,
            "optimal_cost": optimal_cost,
            "potential_savings": potential_savings,
            "routing_efficiency": efficiency,
            "downgradeable_sessions": len(downgradeable),
            "total_sessions": len(all_sessions),
            "routes": dict(sorted(by_route.items(), key=lambda x: x[1]["savings"], reverse=True)),
        }

    def report(self, data: dict, all_results: dict[str, MetricResult], ctx: dict) -> str:
        L = [f"## {self.title}\n"]
        L.append("| Metric | Value |")
        L.append("|--------|-------|")
        L.append(f"| Current total cost | {usd(data['total_cost'])} |")
        L.append(f"| Optimal cost (with routing) | {usd(data['optimal_cost'])} |")
        L.append(f"| Potential savings | {usd(data['potential_savings'])} |")
        L.append(f"| Routing efficiency | {data['routing_efficiency']:.1%} (1.0 = already optimal) |")
        L.append(f"| Downgradeable sessions | {data['downgradeable_sessions']:,} / {data['total_sessions']:,} |")
        L.append("")

        if data["routes"]:
            L.append("### Downgrade opportunities\n")
            L.append("| Route | Sessions | Current Cost | Savings |")
            L.append("|-------|----------|-------------|---------|")
            for route, info in data["routes"].items():
                L.append(
                    f"| {route} | {info['count']:,} "
                    f"| {usd(info['current_cost'])} "
                    f"| {usd(info['savings'])} |"
                )
            L.append("")

        return "\n".join(L)
