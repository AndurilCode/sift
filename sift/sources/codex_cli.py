"""
OpenAI Codex CLI session parser → NormalizedSession.

Parses ~/.codex/state_5.sqlite (threads table) for session metadata and
total token usage. Enriches with rollout JSONL data for tool calls,
prompts, and model info.

Token data: session-level total only (no per-turn breakdown).
"""

import json
import os
import sqlite3
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .base import BaseSource, NormalizedSession, TokenUsage

CODEX_DIR = Path.home() / ".codex"
HISTORY_FILE = CODEX_DIR / "history.jsonl"


def _find_state_db() -> Optional[Path]:
    """Find the latest Codex state DB (schema version may vary)."""
    candidates = sorted(CODEX_DIR.glob("state_*.sqlite"), reverse=True)
    return candidates[0] if candidates else None

EXPLORATION_TOOLS = {"exec_command", "write_stdin", "request_user_input"}
PRODUCTION_TOOLS = {"apply_patch"}


def _epoch_to_iso(epoch_secs) -> str:
    """Convert epoch seconds to ISO string."""
    if not epoch_secs:
        return ""
    try:
        return datetime.fromtimestamp(int(epoch_secs), tz=timezone.utc).isoformat()
    except (ValueError, OSError):
        return ""


def _parse_rollout(rollout_path: str) -> dict:
    """Parse a rollout JSONL file for prompts, tool calls, and model."""
    result = {
        "prompts": [],
        "tool_calls": defaultdict(int),
        "total_tool_calls": 0,
        "model": "",
        "assistant_messages": 0,
        "turns": 0,
        "tool_sequence": [],
        "lines_read": 0,
        "lines_generated": 0,
    }

    if not rollout_path or not Path(rollout_path).exists():
        return result

    try:
        with open(rollout_path) as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = obj.get("type", "")
                payload = obj.get("payload", {})
                timestamp = obj.get("timestamp", "")

                if event_type == "turn_context":
                    if not result["model"]:
                        result["model"] = payload.get("model", "")

                elif event_type == "response_item":
                    rt = payload.get("type", "")
                    role = payload.get("role", "")

                    if rt == "message" and role == "user":
                        content = payload.get("content", [])
                        text_parts = []
                        for c in content:
                            if isinstance(c, dict) and c.get("type") == "input_text":
                                text_parts.append(c.get("text", ""))
                        text = "\n".join(text_parts).strip()
                        if text:
                            result["prompts"].append({
                                "text": text[:2000],
                                "timestamp": timestamp,
                            })
                            result["turns"] += 1

                    elif rt == "message" and role == "assistant":
                        result["assistant_messages"] += 1

                    elif rt in ("function_call", "custom_tool_call"):
                        name = payload.get("name", "unknown")
                        result["tool_calls"][name] += 1
                        result["total_tool_calls"] += 1
                        result["tool_sequence"].append(name)
                        # Count generated lines from apply_patch (unified diff + lines)
                        if name == "apply_patch":
                            args = payload.get("arguments", "")
                            if isinstance(args, str):
                                for ln in args.split("\n"):
                                    if ln.startswith("+") and not ln.startswith("+++"):
                                        result["lines_generated"] += 1

                    elif rt == "function_call_output":
                        # Count lines from tool output (read results)
                        out = payload.get("output", "")
                        if isinstance(out, str) and len(out) > 50:
                            result["lines_read"] += out.count("\n")

    except Exception:
        pass

    return result


class CodexCLISource(BaseSource):

    @property
    def name(self) -> str:
        return "Codex CLI"

    @property
    def key(self) -> str:
        return "codex-cli"

    def available(self) -> bool:
        return _find_state_db() is not None

    def parse_all(self, cutoff: Optional[datetime] = None) -> list[NormalizedSession]:
        state_db = _find_state_db()
        if not state_db:
            return []
        try:
            db = sqlite3.connect(str(state_db))
        except Exception:
            return []

        try:
            rows = db.execute("""
                SELECT id, tokens_used, model, source, cwd, created_at, updated_at,
                       rollout_path, first_user_message, model_provider,
                       git_branch, git_origin_url, cli_version,
                       approval_mode, sandbox_policy, reasoning_effort
                FROM threads
                WHERE tokens_used > 0
                ORDER BY created_at
            """).fetchall()
        except Exception:
            db.close()
            return []

        db.close()

        # Pre-filter by cutoff using created_at epoch
        cutoff_epoch = cutoff.timestamp() if cutoff else 0
        if cutoff_epoch:
            rows = [r for r in rows if r[5] and float(r[5]) >= cutoff_epoch]

        # Parse rollouts in parallel (the expensive part)
        rollout_paths = [r[7] for r in rows]
        workers = min(os.cpu_count() or 4, max(len(rollout_paths), 1))
        with ProcessPoolExecutor(max_workers=workers) as pool:
            rollouts = list(pool.map(_parse_rollout, rollout_paths))

        sessions = []
        for row, rollout in zip(rows, rollouts):
            (thread_id, tokens_used, model, source, cwd, created_at, updated_at,
             rollout_path, first_user_message, model_provider,
             git_branch, git_origin_url, cli_version,
             approval_mode, sandbox_policy, reasoning_effort) = row

            timestamp_start = _epoch_to_iso(created_at)
            timestamp_end = _epoch_to_iso(updated_at)

            duration_seconds = None
            if created_at and updated_at:
                try:
                    duration_seconds = float(updated_at) - float(created_at)
                except (ValueError, TypeError):
                    pass

            project = Path(cwd).name if cwd else ""

            turns_before_first_write = None
            exploration_count = 0
            for tool_name in rollout["tool_sequence"]:
                if tool_name in PRODUCTION_TOOLS:
                    turns_before_first_write = exploration_count
                    break
                if tool_name in EXPLORATION_TOOLS:
                    exploration_count += 1

            final_model = rollout["model"] or model or ""
            usage = TokenUsage(input_tokens=tokens_used)

            session = NormalizedSession(
                session_id=thread_id,
                source=self.key,
                project=project,
                branch=git_branch or "",
                cwd=cwd or "",
                timestamp_start=timestamp_start,
                timestamp_end=timestamp_end,
                duration_seconds=duration_seconds,
                model=final_model,
                usage=usage,
                assistant_messages=rollout["assistant_messages"],
                tool_calls=dict(rollout["tool_calls"]),
                total_tool_calls=rollout["total_tool_calls"],
                turns=rollout["turns"],
                prompts=rollout["prompts"] or ([{
                    "text": first_user_message[:2000],
                    "timestamp": timestamp_start,
                }] if first_user_message else []),
                extras={
                    "source_app": source,
                    "model_provider": model_provider,
                    "cli_version": cli_version,
                    "approval_mode": approval_mode,
                    "reasoning_effort": reasoning_effort,
                    "rollout_path": rollout_path,
                    "turns_before_first_write": turns_before_first_write,
                    "lines_read": rollout["lines_read"],
                    "lines_generated": rollout["lines_generated"],
                },
            )

            if self.session_in_range(session, cutoff):
                sessions.append(session)

        return sessions
