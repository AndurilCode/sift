"""
Metric interface and registry.

Every metric subclass auto-registers on import.  Call ``compute_all()`` to
run every registered metric and get back a keyed dict of results.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from collections import defaultdict
from typing import Any

from sift.sources.base import NormalizedSession, TokenUsage

# ── Cost constants (per million tokens) ──────────────────────────
PRICING = {
    "claude-opus-4-6":    {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-opus-4.6":    {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-sonnet-4-6":  {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-sonnet-4.6":  {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-haiku-4-5":   {"input": 0.80, "output": 4.00, "cache_read": 0.08, "cache_write": 1.00},
    "claude-haiku-4.5":   {"input": 0.80, "output": 4.00, "cache_read": 0.08, "cache_write": 1.00},
    "gpt-5-mini":         {"input": 1.50, "output": 6.00, "cache_read": 0.375, "cache_write": 1.875},
    "gemma4:26b":         {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0},
}
DEFAULT_PRICING = {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75}


# ── Shared utility functions ─────────────────────────────────────

def estimate_cost(usage: TokenUsage, model: str = "") -> float:
    """Estimate cost in USD from normalized TokenUsage."""
    p = PRICING.get(model, DEFAULT_PRICING)
    return (
        usage.input_tokens / 1_000_000 * p["input"]
        + usage.output_tokens / 1_000_000 * p["output"]
        + usage.cache_read_tokens / 1_000_000 * p["cache_read"]
        + usage.cache_write_tokens / 1_000_000 * p["cache_write"]
    )


def session_cost(s: NormalizedSession) -> float:
    """Total cost of a session including its children."""
    cost = estimate_cost(s.usage, s.model)
    for child in s.children:
        cost += estimate_cost(child.usage, child.model)
    return cost


def flatten_with_children(sessions: list[NormalizedSession]) -> list[NormalizedSession]:
    """Flatten sessions + their children into a single list."""
    flat = []
    for s in sessions:
        flat.append(s)
        flat.extend(s.children)
    return flat


def median(lst: list) -> float:
    return lst[len(lst) // 2] if lst else 0


def percentile(lst: list, p: int) -> float:
    return lst[min(int(len(lst) * p / 100), len(lst) - 1)] if lst else 0


# ── Formatting helpers ───────────────────────────────────────────

def usd(amount: float) -> str:
    return f"${amount:,.2f}"


def tok(n: int) -> str:
    return f"{n:,}"


# ── Registry ─────────────────────────────────────────────────────

_REGISTRY: dict[str, type[Metric]] = {}


@dataclass
class MetricResult:
    """Uniform wrapper for any metric's computed output."""
    key: str
    title: str
    data: dict


class Metric(ABC):
    """
    Base class for all metrics.  Subclass, implement the abstract members,
    and the metric auto-registers itself on import.

    order: controls report section ordering.  0 = metric has no report section.
    """

    @property
    @abstractmethod
    def key(self) -> str: ...

    @property
    @abstractmethod
    def title(self) -> str: ...

    @property
    def order(self) -> int:
        """Report section order.  Override to place the section. 0 = hidden."""
        return 0

    @abstractmethod
    def compute(self, sessions: list[NormalizedSession]) -> dict:
        """Run the metric computation.  Returns a plain dict of results."""

    def report(self, data: dict, all_results: dict[str, MetricResult], ctx: dict) -> str:
        """Render a markdown section.  Override to emit report content.
        *ctx* carries source_names, cutoff, sessions, etc.
        """
        return ""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Only register concrete classes (no remaining abstract methods)
        if not getattr(cls, "__abstractmethods__", None):
            # Instantiate once to read the key
            inst = cls()
            _REGISTRY[inst.key] = cls


def get_all_metrics() -> list[Metric]:
    """Return instances of all registered metrics, sorted by order then key."""
    metrics = [cls() for cls in _REGISTRY.values()]
    metrics.sort(key=lambda m: (m.order or 9999, m.key))
    return metrics


def compute_all(sessions: list[NormalizedSession]) -> dict[str, MetricResult]:
    """Compute every registered metric.  Returns {key: MetricResult}."""
    results: dict[str, MetricResult] = {}
    for m in get_all_metrics():
        data = m.compute(sessions)
        results[m.key] = MetricResult(key=m.key, title=m.title, data=data)
    return results
