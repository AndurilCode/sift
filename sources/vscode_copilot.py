"""VS Code Copilot Chat session parser → NormalizedSession."""

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

from .base import BaseSource, NormalizedSession, TokenUsage

WORKSPACES_DIR = Path.home() / "Library" / "Application Support" / "Code" / "User" / "workspaceStorage"

EXPLORATION_TOOLS = {"read_file", "grep_search", "list_dir", "file_search", "semantic_search",
                     "run_in_terminal", "get_terminal_output", "get_errors", "fetch_webpage",
                     "github_repo", "manage_todo_list"}
PRODUCTION_TOOLS = {"replace_string_in_file", "multi_replace_string_in_file", "create_file",
                    "create_directory", "edit_notebook_file", "apply_patch"}


def _get_workspace_project(workspace_dir: Path) -> str:
    """Extract project name from workspace.json."""
    ws_json = workspace_dir / "workspace.json"
    if not ws_json.exists():
        return workspace_dir.name[:8]
    try:
        with open(ws_json) as f:
            data = json.load(f)
        folder = data.get("folder", "")
        if folder:
            path = unquote(urlparse(folder).path)
            return Path(path).name
        return workspace_dir.name[:8]
    except Exception:
        return workspace_dir.name[:8]


def _parse_session(session_path: Path, source_key: str, project: str) -> Optional[NormalizedSession]:
    """Parse a single VS Code Copilot Chat session JSON file."""
    try:
        with open(session_path) as f:
            data = json.load(f)
    except Exception:
        return None

    requests = data.get("requests", [])
    if not requests:
        return None

    session_id = data.get("sessionId", session_path.stem)
    creation_date = data.get("creationDate")
    last_message_date = data.get("lastMessageDate")

    # Convert epoch ms to ISO string
    timestamp_start = ""
    timestamp_end = ""
    if creation_date:
        timestamp_start = datetime.fromtimestamp(creation_date / 1000, tz=timezone.utc).isoformat()
    if last_message_date:
        timestamp_end = datetime.fromtimestamp(last_message_date / 1000, tz=timezone.utc).isoformat()

    duration_seconds = None
    if creation_date and last_message_date:
        duration_seconds = (last_message_date - creation_date) / 1000

    # Aggregate across requests
    thinking_tokens = 0
    total_elapsed_ms = 0
    models_used = defaultdict(int)
    tool_calls_total = 0
    tool_calls_by_name = defaultdict(int)
    tool_sequence = []
    prompts = []

    for req in requests:
        model = req.get("modelId", "")
        if model:
            models_used[model] += 1

        # User prompt
        msg = req.get("message", {})
        text = msg.get("text", "")
        if text:
            req_ts = req.get("timestamp")
            ts_str = ""
            if req_ts:
                ts_str = datetime.fromtimestamp(req_ts / 1000, tz=timezone.utc).isoformat()
            prompts.append({
                "text": text,
                "timestamp": ts_str,
                "model": model,
            })

        # Result: timings and token data
        result = req.get("result", {})
        timings = result.get("timings", {})
        total_elapsed_ms += timings.get("totalElapsed", 0)

        metadata = result.get("metadata", {})
        rounds = metadata.get("toolCallRounds", [])
        for rnd in rounds:
            # Tool calls
            tc = rnd.get("toolCalls", [])
            for t in tc:
                if isinstance(t, dict):
                    name = t.get("name", "unknown")
                    tool_calls_by_name[name] += 1
                    tool_sequence.append(name)
            tool_calls_total += len(tc)

            # Thinking tokens (only available for some models)
            thinking = rnd.get("thinking", {})
            if isinstance(thinking, dict):
                thinking_tokens += thinking.get("tokens", 0)

    if not prompts:
        return None

    # Compute turns before first write
    turns_before_first_write = None
    exploration_count = 0
    for tool_name in tool_sequence:
        if tool_name in PRODUCTION_TOOLS:
            turns_before_first_write = exploration_count
            break
        if tool_name in EXPLORATION_TOOLS:
            exploration_count += 1

    # Primary model = most used
    model = max(models_used, key=models_used.get) if models_used else ""

    # Token usage — limited: only thinking tokens available, no input/output breakdown
    # We store thinking tokens as output_tokens since that's the closest analogy
    usage = TokenUsage(output_tokens=thinking_tokens)

    return NormalizedSession(
        session_id=session_id,
        source=source_key,
        project=project,
        timestamp_start=timestamp_start,
        timestamp_end=timestamp_end,
        duration_seconds=duration_seconds,
        model=model,
        usage=usage,
        assistant_messages=len(requests),
        tool_calls=dict(tool_calls_by_name),
        total_tool_calls=tool_calls_total,
        turns=len(requests),
        prompts=prompts,
        summary=data.get("customTitle", ""),
        extras={
            "thinking_tokens": thinking_tokens,
            "total_elapsed_ms": total_elapsed_ms,
            "models_used": dict(models_used),
            "request_count": len(requests),
            "initial_location": data.get("initialLocation", ""),
            "turns_before_first_write": turns_before_first_write,
        },
    )


class VSCodeCopilotSource(BaseSource):

    @property
    def name(self) -> str:
        return "VS Code Copilot Chat"

    @property
    def key(self) -> str:
        return "vscode-copilot"

    def available(self) -> bool:
        return WORKSPACES_DIR.exists()

    def parse_all(self, cutoff: Optional[datetime] = None) -> list[NormalizedSession]:
        sessions = []

        for workspace_dir in sorted(WORKSPACES_DIR.iterdir()):
            if not workspace_dir.is_dir():
                continue
            chat_dir = workspace_dir / "chatSessions"
            if not chat_dir.is_dir():
                continue

            project = _get_workspace_project(workspace_dir)

            for session_file in sorted(chat_dir.glob("*.json")):
                session = _parse_session(session_file, self.key, project)
                if session and self.session_in_range(session, cutoff):
                    sessions.append(session)

        return sessions
