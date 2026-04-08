"""Claude Code session parser → NormalizedSession."""

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from .base import BaseSource, NormalizedSession, TokenUsage, parse_timestamp

PROJECTS_DIR = Path.home() / ".claude" / "projects"


def _extract_text_content(content):
    """Extract text from message content (string or list)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts).strip()
    return ""


def _is_human_prompt(msg_obj):
    """Check if this is a human-originated prompt (not tool result)."""
    content = msg_obj.get("message", {}).get("content", "")
    if isinstance(content, list):
        types = [i.get("type") for i in content if isinstance(i, dict)]
        if types and all(t == "tool_result" for t in types):
            return False
    return True


def _get_project_name(project_dir_name: str) -> str:
    name = re.sub(r'^-?Users-[^-]+-', '', project_dir_name)
    return name or project_dir_name


def _parse_session(jsonl_path: Path, source_key: str, is_child: bool = False) -> Optional[NormalizedSession]:
    """Parse a single JSONL session file into a NormalizedSession."""
    usage = TokenUsage()
    prompts = []
    agent_id = None
    session_id = None
    timestamp_start = None
    timestamp_end = None
    git_branch = None
    cwd = None
    children = []

    model = None
    tool_calls = defaultdict(int)
    assistant_messages = 0
    stop_reasons = defaultdict(int)
    service_tier = None
    speed = None

    # Track tool call order for "turns before first write" metric
    EXPLORATION_TOOLS = {"Read", "Bash", "Grep", "Glob", "Agent", "ToolSearch", "WebSearch", "WebFetch"}
    PRODUCTION_TOOLS = {"Edit", "Write", "NotebookEdit"}
    tool_call_sequence = []  # ordered list of tool names

    # Line-level tracking
    lines_read = 0
    lines_written = 0
    lines_edited_add = 0
    lines_edited_del = 0
    tool_use_ids = {}  # id -> tool name (to match tool_result back to Read)

    try:
        with open(jsonl_path) as f:
            lines = f.readlines()
    except Exception:
        return None

    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_type = obj.get("type")
        ts = obj.get("timestamp")
        if ts:
            if not timestamp_start:
                timestamp_start = ts
            timestamp_end = ts

        if not agent_id:
            agent_id = obj.get("agentId")
        if not session_id:
            session_id = obj.get("sessionId")
        if not git_branch:
            git_branch = obj.get("gitBranch")
        if not cwd:
            cwd = obj.get("cwd")

        if msg_type == "assistant":
            msg = obj.get("message", {})
            assistant_messages += 1

            u = msg.get("usage", {})
            usage.input_tokens += u.get("input_tokens", 0)
            usage.output_tokens += u.get("output_tokens", 0)
            usage.cache_write_tokens += u.get("cache_creation_input_tokens", 0)
            usage.cache_read_tokens += u.get("cache_read_input_tokens", 0)

            if msg.get("model"):
                model = msg["model"]
            if u.get("service_tier"):
                service_tier = u["service_tier"]
            if u.get("speed"):
                speed = u["speed"]

            sr = msg.get("stop_reason")
            if sr:
                stop_reasons[sr] += 1

            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        name = block.get("name", "unknown")
                        tool_calls[name] += 1
                        tool_call_sequence.append(name)
                        tool_use_ids[block.get("id", "")] = name
                        inp = block.get("input", {})
                        if isinstance(inp, dict):
                            if name == "Write":
                                lines_written += inp.get("content", "").count("\n") + 1
                            elif name == "Edit":
                                lines_edited_add += inp.get("new_string", "").count("\n") + 1
                                lines_edited_del += inp.get("old_string", "").count("\n") + 1

        elif msg_type == "user":
            user_type = obj.get("userType", "")
            is_sidechain = obj.get("isSidechain", False)
            content = obj.get("message", {}).get("content", "")

            # Count lines from Read tool results
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        tid = block.get("tool_use_id", "")
                        if tool_use_ids.get(tid) == "Read":
                            c = block.get("content", "")
                            if isinstance(c, list):
                                c = "\n".join(str(x) for x in c)
                            if isinstance(c, str):
                                lines_read += c.count("\n")

            text = _extract_text_content(content)

            if text and not is_sidechain and _is_human_prompt(obj) and user_type != "tool":
                prompts.append({
                    "text": text,
                    "timestamp": obj.get("timestamp"),
                    "entrypoint": obj.get("entrypoint", ""),
                })

    # Parse subagent sessions
    session_dir = jsonl_path.parent / jsonl_path.stem
    if session_dir.is_dir():
        subagents_dir = session_dir / "subagents"
        if subagents_dir.is_dir():
            for sub_file in subagents_dir.glob("*.jsonl"):
                child = _parse_session(sub_file, source_key + "-subagent", is_child=True)
                if child:
                    child.extras["subagent_file"] = sub_file.name
                    children.append(child)

    if assistant_messages == 0:
        return None

    # Compute turns before first write
    turns_before_first_write = None
    exploration_count = 0
    for tool_name in tool_call_sequence:
        if tool_name in PRODUCTION_TOOLS:
            turns_before_first_write = exploration_count
            break
        if tool_name in EXPLORATION_TOOLS:
            exploration_count += 1
    # If no production tool was ever called, count is None (never wrote)
    # If first call was a write, count is 0

    # Duration
    duration_seconds = None
    if timestamp_start and timestamp_end:
        ts_s = parse_timestamp(timestamp_start)
        ts_e = parse_timestamp(timestamp_end)
        if ts_s and ts_e:
            duration_seconds = (ts_e - ts_s).total_seconds()

    child_source = source_key + "-subagent" if is_child else source_key

    return NormalizedSession(
        session_id=session_id or jsonl_path.stem,
        source=child_source,
        project="",  # set by caller
        branch=git_branch or "",
        cwd=cwd or "",
        timestamp_start=timestamp_start or "",
        timestamp_end=timestamp_end or "",
        duration_seconds=duration_seconds,
        model=model or "",
        usage=usage,
        assistant_messages=assistant_messages,
        tool_calls=dict(tool_calls),
        total_tool_calls=sum(tool_calls.values()),
        turns=assistant_messages,  # each assistant message is a turn in CC
        prompts=prompts,
        children=children,
        extras={
            "agent_id": agent_id,
            "file": str(jsonl_path),
            "stop_reasons": dict(stop_reasons),
            "service_tier": service_tier,
            "speed": speed,
            "turns_before_first_write": turns_before_first_write,
            "lines_read": lines_read,
            "lines_generated": lines_written + lines_edited_add - lines_edited_del,
            "lines_written": lines_written,
            "lines_edited_add": lines_edited_add,
            "lines_edited_del": lines_edited_del,
        },
    )


class ClaudeCodeSource(BaseSource):

    @property
    def name(self) -> str:
        return "Claude Code"

    @property
    def key(self) -> str:
        return "claude-code"

    def available(self) -> bool:
        return PROJECTS_DIR.exists()

    def parse_all(self, cutoff: Optional[datetime] = None) -> list[NormalizedSession]:
        sessions = []

        for project_dir in sorted(PROJECTS_DIR.iterdir()):
            if not project_dir.is_dir():
                continue
            project_name = _get_project_name(project_dir.name)

            for jsonl_file in sorted(project_dir.glob("*.jsonl")):
                session = _parse_session(jsonl_file, self.key)
                if session and session.total_tokens > 0 and self.session_in_range(session, cutoff):
                    session.project = project_name
                    # propagate project to children
                    for child in session.children:
                        child.project = project_name
                    sessions.append(session)

        return sessions
