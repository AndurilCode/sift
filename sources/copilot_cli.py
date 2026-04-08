"""Copilot CLI session parser → NormalizedSession."""

import json
import yaml
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from .base import BaseSource, NormalizedSession, TokenUsage, parse_timestamp

SESSION_DIR = Path.home() / ".copilot" / "session-state"

EXPLORATION_TOOLS = {"bash", "view", "glob", "report_intent", "skill", "task_complete"}
PRODUCTION_TOOLS = {"create", "edit"}


def _parse_workspace(session_dir: Path) -> dict:
    ws_path = session_dir / "workspace.yaml"
    if not ws_path.exists():
        return {}
    try:
        with open(ws_path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _parse_session(session_dir: Path, source_key: str) -> Optional[NormalizedSession]:
    """Parse a single Copilot CLI session directory."""
    events_path = session_dir / "events.jsonl"
    if not events_path.exists():
        return None

    workspace = _parse_workspace(session_dir)
    session_id = session_dir.name

    msg_output_tokens = 0
    assistant_messages = 0
    tool_calls_total = 0
    tool_calls_by_name = defaultdict(int)
    tool_sequence = []
    turns = 0
    prompts = []
    timestamp_start = None
    timestamp_end = None
    model = None
    mode = None
    shutdown_data = None

    try:
        with open(events_path) as f:
            lines = f.readlines()
    except Exception:
        return None

    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        event_type = obj.get("type", "")
        ts = obj.get("timestamp")
        data = obj.get("data", {})

        if ts:
            if not timestamp_start:
                timestamp_start = ts
            timestamp_end = ts

        if event_type == "session.model_change":
            model = data.get("newModel")
        elif event_type == "session.mode_changed":
            mode = data.get("newMode")
        elif event_type == "assistant.turn_start":
            turns += 1
        elif event_type == "assistant.message":
            assistant_messages += 1
            msg_output_tokens += data.get("outputTokens", 0)
            for tr in data.get("toolRequests", []):
                name = tr.get("name", "unknown")
                tool_calls_by_name[name] += 1
                tool_calls_total += 1
                tool_sequence.append(name)
        elif event_type == "user.message":
            content = data.get("content", "")
            if content:
                prompts.append({
                    "text": content,
                    "timestamp": ts,
                    "mode": data.get("agentMode", ""),
                })
        elif event_type == "session.shutdown":
            shutdown_data = data

    if assistant_messages == 0:
        return None

    # Extract token data from shutdown event (authoritative)
    usage = TokenUsage()
    model_metrics = {}
    context_info = {}

    if shutdown_data:
        mm = shutdown_data.get("modelMetrics", {})
        for model_name, metrics in mm.items():
            u = metrics.get("usage", {})
            model_metrics[model_name] = {
                "requests": metrics.get("requests", {}).get("count", 0),
                "cost": metrics.get("requests", {}).get("cost", 0),
                "input_tokens": u.get("inputTokens", 0),
                "output_tokens": u.get("outputTokens", 0),
                "cache_read_tokens": u.get("cacheReadTokens", 0),
                "cache_write_tokens": u.get("cacheWriteTokens", 0),
            }
            usage.input_tokens += u.get("inputTokens", 0)
            usage.output_tokens += u.get("outputTokens", 0)
            usage.cache_read_tokens += u.get("cacheReadTokens", 0)
            usage.cache_write_tokens += u.get("cacheWriteTokens", 0)

        context_info = {
            "current_tokens": shutdown_data.get("currentTokens", 0),
            "system_tokens": shutdown_data.get("systemTokens", 0),
            "conversation_tokens": shutdown_data.get("conversationTokens", 0),
            "tool_definitions_tokens": shutdown_data.get("toolDefinitionsTokens", 0),
        }

    has_shutdown = bool(shutdown_data and usage.input_tokens + usage.output_tokens > 0)

    # If no shutdown data, fall back to per-message output tokens
    if not has_shutdown:
        usage = TokenUsage(output_tokens=msg_output_tokens)

    # Duration
    duration_seconds = None
    if timestamp_start and timestamp_end:
        ts_s = parse_timestamp(timestamp_start)
        ts_e = parse_timestamp(timestamp_end)
        if ts_s and ts_e:
            duration_seconds = (ts_e - ts_s).total_seconds()

    # Project name
    repository = workspace.get("repository", "")
    cwd = workspace.get("cwd", "")
    project_name = repository or (Path(cwd).name if cwd else session_id[:8])

    code_changes = shutdown_data.get("codeChanges", {}) if shutdown_data else {}

    # Compute turns before first write
    turns_before_first_write = None
    exploration_count = 0
    for tool_name in tool_sequence:
        if tool_name in PRODUCTION_TOOLS:
            turns_before_first_write = exploration_count
            break
        if tool_name in EXPLORATION_TOOLS:
            exploration_count += 1

    return NormalizedSession(
        session_id=session_id,
        source=source_key,
        project=project_name,
        repository=repository,
        branch=workspace.get("branch", ""),
        cwd=cwd,
        timestamp_start=timestamp_start or "",
        timestamp_end=timestamp_end or "",
        duration_seconds=duration_seconds,
        model=shutdown_data.get("currentModel", model or "") if shutdown_data else (model or ""),
        usage=usage,
        assistant_messages=assistant_messages,
        tool_calls=dict(tool_calls_by_name),
        total_tool_calls=tool_calls_total,
        turns=turns,
        prompts=prompts,
        summary=workspace.get("summary", ""),
        extras={
            "has_shutdown": has_shutdown,
            "model_metrics": model_metrics,
            "context_info": context_info,
            "mode": mode,
            "premium_requests": shutdown_data.get("totalPremiumRequests", 0) if shutdown_data else 0,
            "api_duration_ms": shutdown_data.get("totalApiDurationMs", 0) if shutdown_data else 0,
            "lines_added": code_changes.get("linesAdded", 0),
            "lines_removed": code_changes.get("linesRemoved", 0),
            "turns_before_first_write": turns_before_first_write,
        },
    )


class CopilotCLISource(BaseSource):

    @property
    def name(self) -> str:
        return "Copilot CLI"

    @property
    def key(self) -> str:
        return "copilot-cli"

    def available(self) -> bool:
        return SESSION_DIR.exists()

    def parse_all(self, cutoff: Optional[datetime] = None) -> list[NormalizedSession]:
        sessions = []

        for session_dir in sorted(SESSION_DIR.iterdir()):
            if not session_dir.is_dir():
                continue
            session = _parse_session(session_dir, self.key)
            if session and self.session_in_range(session, cutoff):
                sessions.append(session)

        return sessions
