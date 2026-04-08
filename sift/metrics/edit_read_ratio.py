from __future__ import annotations
from sift.sources.base import NormalizedSession
from sift.metrics.base import Metric, MetricResult


class EditReadRatioMetric(Metric):
    @property
    def key(self) -> str:
        return "edit_read_ratio"

    @property
    def title(self) -> str:
        return "Productivity Indicators"

    @property
    def order(self) -> int:
        return 70

    def compute(self, sessions: list[NormalizedSession]) -> dict:
        EDIT_NAMES = {"Edit", "edit", "replace_string_in_file", "multi_replace_string_in_file", "replace", "apply_patch"}
        WRITE_NAMES = {"Write", "create", "create_file", "write_file"}
        READ_NAMES = {"Read", "view", "read_file", "read_many_files"}
        edits = reads = writes = 0
        for s in sessions:
            tc = s.tool_calls
            edits += sum(tc.get(n, 0) for n in EDIT_NAMES)
            writes += sum(tc.get(n, 0) for n in WRITE_NAMES)
            reads += sum(tc.get(n, 0) for n in READ_NAMES)
        production = edits + writes
        return {
            "edits": edits, "reads": reads, "writes": writes,
            "edit_read_ratio": production / max(reads, 1),
            "production_calls": production,
            "exploration_calls": reads,
        }

    def report(self, data: dict, all_results: dict[str, MetricResult], ctx: dict) -> str:
        er = data
        if er["reads"] == 0 and er["edits"] == 0:
            return ""

        stw = all_results["start_to_write_ratio"].data
        lr = all_results["lines_ratio"].data

        L = [f"## {self.title}\n"]
        L.append("| Metric | Value | What it measures |")
        L.append("|--------|-------|------------------|")
        L.append(f"| Edit calls | {er['edits']:,} | Code modifications |")
        L.append(f"| Write calls | {er['writes']:,} | New file creation |")
        L.append(f"| Read calls | {er['reads']:,} | Code exploration |")
        L.append(f"| Edit+Write / Read ratio | {er['edit_read_ratio']:.2f} | >1 producing, <1 exploring |")
        if stw["sessions_measured"] > 0:
            L.append(f"| Avg turns before first write | {stw['avg_turns_before_write']:.1f} | Exploration before production |")
            L.append(f"| Median turns before first write | {stw['median_turns_before_write']} | Typical ramp-up |")
            L.append(f"| P90 turns before first write | {stw['p90_turns_before_write']} | Slow-start threshold |")
            L.append(f"| Sessions that never wrote | {stw['sessions_never_wrote']:,} | Exploration-only sessions |")
            L.append(f"| Sessions wrote immediately | {stw['sessions_wrote_first']:,} | Zero ramp-up |")
        if lr["sessions_with_data"] > 0:
            L.append(f"| Lines read | {lr['total_lines_read']:,} | Total lines consumed from files |")
            L.append(f"| Lines generated (net) | {lr['total_lines_generated']:,} | Net lines produced (Write + Edit delta) |")
            L.append(f"| Read/Generated ratio | {lr['read_to_generated_ratio']:.1f}x | Lines read per line generated |")
            L.append(f"| Median Read/Generated | {lr['median_ratio']:.1f}x | Typical session ratio ({lr['sessions_with_ratio']} sessions) |")
        L.append("")
        return "\n".join(L)
