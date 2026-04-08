"""
Normalized session schema and base source interface.

All source parsers produce NormalizedSession dicts. Analysis and reporting
operate exclusively on this schema, making it trivial to add new sources.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Optional


SINCE_DAYS = int(os.environ.get("SINCE_DAYS", "0")) or None
SINCE_DATE = os.environ.get("SINCE_DATE")


def get_cutoff() -> Optional[datetime]:
    """Return a UTC-aware datetime cutoff, or None for all time."""
    if SINCE_DATE:
        return datetime.fromisoformat(SINCE_DATE).replace(tzinfo=timezone.utc)
    if SINCE_DAYS:
        return datetime.now(timezone.utc) - timedelta(days=SINCE_DAYS)
    return None


def parse_timestamp(ts_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO timestamp string to datetime."""
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class TokenUsage:
    """Normalized token usage — common across all sources."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total(self) -> int:
        return (self.input_tokens + self.output_tokens
                + self.cache_read_tokens + self.cache_write_tokens)

    def __iadd__(self, other: TokenUsage) -> TokenUsage:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens
        return self


@dataclass
class NormalizedSession:
    """Universal session record produced by every source parser."""

    # ── Identity ──
    session_id: str = ""
    source: str = ""          # e.g. "claude-code", "copilot-cli"
    project: str = ""
    repository: str = ""
    branch: str = ""
    cwd: str = ""

    # ── Timing ──
    timestamp_start: str = ""
    timestamp_end: str = ""
    duration_seconds: Optional[float] = None

    # ── Model ──
    model: str = ""

    # ── Token usage (normalized) ──
    usage: TokenUsage = field(default_factory=TokenUsage)

    # ── Activity ──
    assistant_messages: int = 0
    tool_calls: dict = field(default_factory=dict)   # tool_name → count
    total_tool_calls: int = 0
    turns: int = 0

    # ── User prompts ──
    prompts: list = field(default_factory=list)       # [{text, timestamp, ...}]
    summary: str = ""

    # ── Children (subagents, nested sessions) ──
    children: list = field(default_factory=list)       # List[NormalizedSession]

    # ── Source-specific extras (preserves anything unique) ──
    extras: dict = field(default_factory=dict)
    # Common extras:
    #   premium_requests: float          (copilot)
    #   lines_added / lines_removed: int (copilot)
    #   api_duration_ms: int             (copilot)
    #   context_info: dict               (copilot)
    #   model_metrics: dict              (copilot)
    #   stop_reasons: dict               (claude-code)
    #   service_tier: str                (claude-code)
    #   speed: str                       (claude-code)
    #   subagent_file: str               (claude-code subagent)

    @property
    def total_tokens(self) -> int:
        return self.usage.total

    @property
    def date(self) -> str:
        """YYYY-MM-DD from timestamp_start."""
        if self.timestamp_start:
            return self.timestamp_start[:10]
        return ""

    @property
    def is_child(self) -> bool:
        return self.source.endswith("-subagent")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["total_tokens"] = self.total_tokens
        d["date"] = self.date
        return d


class BaseSource(ABC):
    """Interface every source parser must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable source name, e.g. 'Claude Code'."""

    @property
    @abstractmethod
    def key(self) -> str:
        """Machine key used in source field, e.g. 'claude-code'."""

    @abstractmethod
    def available(self) -> bool:
        """Return True if this source's data directory exists."""

    @abstractmethod
    def parse_all(self, cutoff: Optional[datetime] = None) -> list[NormalizedSession]:
        """Parse all sessions, optionally filtered by cutoff date.
        Returns a flat list — children are nested inside parent sessions,
        NOT returned as separate top-level entries."""

    def session_in_range(self, session: NormalizedSession, cutoff: Optional[datetime]) -> bool:
        if not cutoff or not session.timestamp_start:
            return True
        ts = parse_timestamp(session.timestamp_start)
        return ts >= cutoff if ts else True
