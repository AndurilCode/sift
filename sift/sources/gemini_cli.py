"""
Gemini CLI session parser → NormalizedSession.

Parses ~/.gemini/tmp/{projectHash}/chats/session-*.json files.
Gemini provides full per-turn token data: input, output, cached, thoughts.
"""

import json
import os
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Optional

from .base import BaseSource, NormalizedSession, TokenUsage, parse_timestamp

GEMINI_DIR = Path.home() / ".gemini" / "tmp"

EXPLORATION_TOOLS = {"read_file", "read_many_files", "list_directory", "glob",
                     "search_file_content", "run_shell_command", "web_fetch",
                     "google_web_search", "codebase_investigator"}
PRODUCTION_TOOLS = {"write_file", "replace"}


def _parse_session(session_path: Path, project_hash: str, source_key: str) -> Optional[NormalizedSession]:
    """Parse a single Gemini CLI session JSON file."""
    try:
        with open(session_path) as f:
            data = json.load(f)
    except Exception:
        return None

    messages = data.get("messages", [])
    if not messages:
        return None

    session_id = data.get("sessionId", session_path.stem)
    timestamp_start = data.get("startTime", "")
    timestamp_end = data.get("lastUpdated", "")

    # Duration
    duration_seconds = None
    ts_s = parse_timestamp(timestamp_start)
    ts_e = parse_timestamp(timestamp_end)
    if ts_s and ts_e:
        duration_seconds = (ts_e - ts_s).total_seconds()

    # Aggregate across messages
    usage = TokenUsage()
    total_thoughts = 0
    tool_calls = defaultdict(int)
    total_tool_calls = 0
    tool_sequence = []
    assistant_messages = 0
    model = ""
    prompts = []
    lines_read = 0
    lines_generated = 0

    for msg in messages:
        msg_type = msg.get("type", "")

        if msg_type == "gemini":
            assistant_messages += 1

            if not model:
                model = msg.get("model", "")

            tokens = msg.get("tokens", {})
            usage.input_tokens += tokens.get("input", 0)
            usage.output_tokens += tokens.get("output", 0)
            usage.cache_read_tokens += tokens.get("cached", 0)
            total_thoughts += tokens.get("thoughts", 0)

            for tc in msg.get("toolCalls", []):
                name = tc.get("name", "unknown")
                tool_calls[name] += 1
                total_tool_calls += 1
                tool_sequence.append(name)

                # Lines read: extract output from read_file/read_many_files results
                if name in ("read_file", "read_many_files"):
                    result_list = tc.get("result", [])
                    if isinstance(result_list, list):
                        for item in result_list:
                            if isinstance(item, dict):
                                out = item.get("functionResponse", {}).get("response", {}).get("output", "")
                                if isinstance(out, str):
                                    lines_read += out.count("\n")

                # Lines generated: extract from write_file content or replace new_string
                if name in ("write_file", "replace"):
                    args = tc.get("args", {})
                    if isinstance(args, dict):
                        content = args.get("content", "") or args.get("new_string", "")
                        if isinstance(content, str):
                            lines_generated += content.count("\n") + 1

        elif msg_type == "user":
            content = msg.get("content", "")
            if content:
                prompts.append({
                    "text": content[:2000],
                    "timestamp": msg.get("timestamp", ""),
                })

    if assistant_messages == 0:
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

    return NormalizedSession(
        session_id=session_id,
        source=source_key,
        project=project_hash,
        timestamp_start=timestamp_start,
        timestamp_end=timestamp_end,
        duration_seconds=duration_seconds,
        model=model,
        usage=usage,
        assistant_messages=assistant_messages,
        tool_calls=dict(tool_calls),
        total_tool_calls=total_tool_calls,
        turns=len(prompts),
        prompts=prompts,
        extras={
            "thinking_tokens": total_thoughts,
            "project_hash": project_hash,
            "turns_before_first_write": turns_before_first_write,
            "lines_read": lines_read,
            "lines_generated": lines_generated,
        },
    )


def _parse_job(args: tuple) -> Optional[NormalizedSession]:
    """Top-level function for multiprocessing (must be picklable)."""
    session_path, project_hash, source_key = args
    return _parse_session(Path(session_path), project_hash, source_key)


class GeminiCLISource(BaseSource):

    @property
    def name(self) -> str:
        return "Gemini CLI"

    @property
    def key(self) -> str:
        return "gemini-cli"

    def available(self) -> bool:
        return GEMINI_DIR.exists()

    def parse_all(self, cutoff: Optional[datetime] = None) -> list[NormalizedSession]:
        cutoff_ts = cutoff.timestamp() if cutoff else 0
        jobs = []

        for project_dir in GEMINI_DIR.iterdir():
            if not project_dir.is_dir():
                continue
            chats_dir = project_dir / "chats"
            if not chats_dir.is_dir():
                continue

            project_hash = project_dir.name

            for session_file in chats_dir.glob("session-*.json"):
                if cutoff_ts and os.path.getmtime(session_file) < cutoff_ts:
                    continue
                jobs.append((str(session_file), project_hash, self.key))

        if not jobs:
            return []

        sessions = []
        workers = min(os.cpu_count() or 4, len(jobs))
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for session in pool.map(_parse_job, jobs):
                if session and session.total_tokens > 0 and self.session_in_range(session, cutoff):
                    sessions.append(session)

        return sessions
