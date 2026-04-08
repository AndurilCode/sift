from __future__ import annotations
from sources.base import NormalizedSession
from metrics.base import Metric, MetricResult, flatten_with_children, usd, tok


class CacheEfficiencyMetric(Metric):
    @property
    def key(self) -> str:
        return "cache_efficiency"

    @property
    def title(self) -> str:
        return "Cache Efficiency"

    @property
    def order(self) -> int:
        return 50

    def compute(self, sessions: list[NormalizedSession]) -> dict:
        all_flat = flatten_with_children(sessions)
        total_uncached = sum(s.usage.input_tokens for s in all_flat)
        total_cache_read = sum(s.usage.cache_read_tokens for s in all_flat)
        total_cache_write = sum(s.usage.cache_write_tokens for s in all_flat)
        total_all_input = total_uncached + total_cache_read + total_cache_write
        hit_rate = total_cache_read / max(total_all_input, 1)
        saved = (total_cache_read / 1_000_000) * (3.00 - 0.30)

        return {
            "total_all_input": total_all_input,
            "total_uncached": total_uncached,
            "total_cache_read": total_cache_read,
            "total_cache_write": total_cache_write,
            "cache_hit_rate": hit_rate,
            "estimated_savings_usd": saved,
        }

    def report(self, data: dict, all_results: dict[str, MetricResult], ctx: dict) -> str:
        cache = data
        ca = all_results["cache_amortization"].data
        freshness = all_results["input_freshness"].data

        L = [f"## {self.title}\n"]
        L.append("| Metric | Value |")
        L.append("|--------|-------|")
        L.append(f"| Total input (all types) | {tok(cache['total_all_input'])} |")
        L.append(f"| Uncached input | {tok(cache['total_uncached'])} |")
        L.append(f"| Cache reads (hits) | {tok(cache['total_cache_read'])} |")
        L.append(f"| Cache writes | {tok(cache['total_cache_write'])} |")
        L.append(f"| Cache hit rate | {cache['cache_hit_rate']:.1%} |")
        L.append(f"| Cache write amortization | {ca['amortization_ratio']:.1f}x | {'Net positive' if ca['is_net_positive'] else 'Net negative — writes > reads'} |")
        L.append(f"| Input freshness ratio | {freshness['freshness_ratio']:.1%} | {'Healthy' if freshness['is_healthy'] else 'High — poor cache utilization'} (<10% target) |")
        L.append(f"| Estimated savings | {usd(cache['estimated_savings_usd'])} |")
        L.append("")
        return "\n".join(L)
