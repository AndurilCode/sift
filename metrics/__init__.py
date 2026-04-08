"""
Metric registry — auto-imports all metric modules so they self-register.

Usage:
    from metrics import compute_all, get_all_metrics
    results = compute_all(sessions)  # {key: MetricResult}
"""

from metrics.base import (
    Metric,
    MetricResult,
    compute_all,
    get_all_metrics,
    # Shared utilities re-exported for convenience
    estimate_cost,
    session_cost,
    flatten_with_children,
    PRICING,
    DEFAULT_PRICING,
    usd,
    tok,
)

# Import every metric module so subclasses register themselves.
from metrics import (  # noqa: F401
    cache_amortization,
    cache_efficiency,
    child_metrics,
    context_accumulation,
    context_efficiency,
    cost_efficiency,
    cost_per_minute,
    cost_per_productive_action,
    daily_burn,
    edit_read_ratio,
    input_freshness,
    lines_ratio,
    model_mix,
    output_ratio,
    platform_comparison,
    project_adoption,
    session_health,
    start_to_write_ratio,
    stop_reason_distribution,
    tool_definition_overhead,
    tool_usage,
    top_sessions,
)

__all__ = [
    "Metric",
    "MetricResult",
    "compute_all",
    "get_all_metrics",
    "estimate_cost",
    "session_cost",
    "flatten_with_children",
    "PRICING",
    "DEFAULT_PRICING",
    "usd",
    "tok",
]
