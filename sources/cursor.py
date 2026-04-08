"""
Cursor editor session parser → NormalizedSession.

Cursor does not log token usage locally. This parser extracts what's available:
- Chat sessions from ~/.cursor/chats/ (SQLite: messages with role/content)
- Code tracking from ~/.cursor/ai-tracking/ai-code-tracking.db (model, conversation, timestamps)
- Commit scoring from the same DB (AI-authored lines, AI percentage)

Token counts are estimated from message content length (~4 chars/token).
"""

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .base import BaseSource, NormalizedSession, TokenUsage

CURSOR_DIR = Path.home() / ".cursor"
CHATS_DIR = CURSOR_DIR / "chats"
TRACKING_DB = CURSOR_DIR / "ai-tracking" / "ai-code-tracking.db"

CHARS_PER_TOKEN = 4  # rough estimate for English text + code

EXPLORATION_TOOLS = {"Read", "Glob", "Grep", "Bash", "Search"}
PRODUCTION_TOOLS = {"Write", "Edit"}


def _epoch_to_iso(epoch_ms: int) -> str:
    """Convert epoch milliseconds to ISO string."""
    if not epoch_ms:
        return ""
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).isoformat()


def _parse_chat_session(session_hash: str, agent_id: str, db_path: Path, source_key: str) -> Optional[NormalizedSession]:
    """Parse a single Cursor chat store.db into a NormalizedSession."""
    try:
        db = sqlite3.connect(str(db_path))
    except Exception:
        return None

    # Read metadata
    meta = {}
    try:
        for key, value in db.execute("SELECT key, value FROM meta").fetchall():
            try:
                decoded = bytes.fromhex(value).decode("utf-8") if isinstance(value, str) else value
                meta[key] = json.loads(decoded) if decoded.startswith("{") else decoded
            except Exception:
                pass
    except Exception:
        pass

    # The first meta entry (key "0") contains session info
    session_meta = meta.get("0", {})
    if isinstance(session_meta, str):
        try:
            session_meta = json.loads(session_meta)
        except Exception:
            session_meta = {}

    session_id = session_meta.get("agentId", agent_id)
    created_at = session_meta.get("createdAt", 0)
    mode = session_meta.get("mode", "")
    name = session_meta.get("name", "")

    # Read message blobs
    prompts = []
    total_content_chars = 0
    output_chars = 0
    input_chars = 0
    roles = defaultdict(int)
    tool_calls_by_name = defaultdict(int)
    tool_sequence = []
    messages = 0

    try:
        for blob_id, data in db.execute("SELECT id, data FROM blobs").fetchall():
            if not isinstance(data, bytes):
                continue
            try:
                obj = json.loads(data.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            role = obj.get("role", "")
            content = obj.get("content", "")
            content_str = str(content)
            content_len = len(content_str)
            total_content_chars += content_len
            roles[role] += 1
            messages += 1

            if role == "assistant":
                output_chars += content_len
            elif role in ("user", "system"):
                input_chars += content_len
            elif role == "tool":
                # Extract tool name from content (list of tool-result dicts)
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict):
                            tool_name = item.get("toolName", "")
                            if tool_name:
                                tool_calls_by_name[tool_name] += 1
                                tool_sequence.append(tool_name)

            if role == "user" and content:
                prompts.append({
                    "text": content[:2000],  # cap prompt storage
                    "timestamp": _epoch_to_iso(created_at),
                })
    except Exception:
        pass

    db.close()

    if messages == 0:
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

    # Estimate tokens from content length
    estimated_input = input_chars // CHARS_PER_TOKEN
    estimated_output = output_chars // CHARS_PER_TOKEN

    return NormalizedSession(
        session_id=session_id,
        source=source_key,
        project="",  # set later from tracking DB or left generic
        timestamp_start=_epoch_to_iso(created_at),
        model="",  # not stored in chat blobs
        usage=TokenUsage(
            input_tokens=estimated_input,
            output_tokens=estimated_output,
        ),
        assistant_messages=roles.get("assistant", 0),
        tool_calls=dict(tool_calls_by_name),
        total_tool_calls=roles.get("tool", 0),
        turns=roles.get("user", 0),
        prompts=prompts,
        summary=name,
        extras={
            "mode": mode,
            "total_messages": messages,
            "roles": dict(roles),
            "estimated_tokens": True,  # flag that tokens are estimated
            "total_content_chars": total_content_chars,
            "turns_before_first_write": turns_before_first_write,
        },
    )


def _parse_tracking_sessions(source_key: str) -> list[NormalizedSession]:
    """Parse ai-code-tracking.db for composer/conversation sessions."""
    if not TRACKING_DB.exists():
        return []

    try:
        db = sqlite3.connect(str(TRACKING_DB))
    except Exception:
        return []

    sessions = []

    # Group code hashes by conversationId
    try:
        rows = db.execute("""
            SELECT conversationId, model,
                   COUNT(*) as code_entries,
                   GROUP_CONCAT(DISTINCT source) as sources,
                   MIN(timestamp) as first_ts,
                   MAX(timestamp) as last_ts
            FROM ai_code_hashes
            WHERE conversationId IS NOT NULL
            GROUP BY conversationId
            ORDER BY first_ts
        """).fetchall()
    except Exception:
        rows = []

    for conv_id, model, code_entries, sources, first_ts, last_ts in rows:
        duration = (last_ts - first_ts) / 1000 if first_ts and last_ts else None

        sessions.append(NormalizedSession(
            session_id=conv_id,
            source=source_key,
            project="",
            timestamp_start=_epoch_to_iso(first_ts),
            timestamp_end=_epoch_to_iso(last_ts),
            duration_seconds=duration,
            model=model or "",
            usage=TokenUsage(),  # no token data available
            assistant_messages=code_entries,
            turns=1,
            extras={
                "code_entries": code_entries,
                "sources": sources,
                "estimated_tokens": False,
                "from_tracking_db": True,
            },
        ))

    # Load commit scoring data as extras on sessions
    commit_stats = {"total_commits": 0, "ai_lines_added": 0, "human_lines_added": 0}
    try:
        for row in db.execute("""
            SELECT composerLinesAdded, composerLinesDeleted,
                   tabLinesAdded, tabLinesDeleted,
                   humanLinesAdded, humanLinesDeleted,
                   v2AiPercentage
            FROM scored_commits
            WHERE composerLinesAdded IS NOT NULL
        """).fetchall():
            commit_stats["total_commits"] += 1
            commit_stats["ai_lines_added"] += (row[0] or 0) + (row[2] or 0)
            commit_stats["human_lines_added"] += (row[4] or 0)
    except Exception:
        pass

    db.close()

    # Attach commit stats to all sessions as shared context
    for s in sessions:
        s.extras["commit_stats"] = commit_stats

    return sessions


class CursorSource(BaseSource):

    @property
    def name(self) -> str:
        return "Cursor"

    @property
    def key(self) -> str:
        return "cursor"

    def available(self) -> bool:
        return CURSOR_DIR.exists() and (CHATS_DIR.exists() or TRACKING_DB.exists())

    def parse_all(self, cutoff: Optional[datetime] = None) -> list[NormalizedSession]:
        sessions = []
        seen_ids = set()

        # 1. Parse chat stores
        if CHATS_DIR.exists():
            for session_hash_dir in sorted(CHATS_DIR.iterdir()):
                if not session_hash_dir.is_dir():
                    continue
                for agent_dir in sorted(session_hash_dir.iterdir()):
                    db_path = agent_dir / "store.db"
                    if not db_path.exists():
                        continue
                    session = _parse_chat_session(
                        session_hash_dir.name, agent_dir.name, db_path, self.key
                    )
                    if session and self.session_in_range(session, cutoff):
                        sessions.append(session)
                        seen_ids.add(session.session_id)

        # 2. Parse tracking DB conversations (skip if already found via chat)
        for session in _parse_tracking_sessions(self.key):
            if session.session_id not in seen_ids and self.session_in_range(session, cutoff):
                sessions.append(session)

        return sessions
