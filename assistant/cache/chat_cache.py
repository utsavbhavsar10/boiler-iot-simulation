"""
assistant/cache/chat_cache.py
──────────────────────────────
Redis-backed per-session chat history cache.

Key schema:
  chat:{session_id}          LIST<JSON>   — ordered messages (oldest→newest)
  chat:{session_id}:summary  STRING       — compressed summary (optional)
  chat:{session_id}:meta     HASH         — last_seen, turn_count

Design:
  - Falls open: if Redis is unreachable, returns [] / None without raising.
  - Thread-safe: uses Redis MULTI/EXEC pipeline for RPUSH + LTRIM + EXPIRE.
  - Memory-safe: LTRIM caps every list at CHAT_HISTORY_MAX_TURNS per write.
  - TTL: 24h idle expiry — EXPIRE is refreshed on every append.

Usage:
    from assistant.cache.chat_cache import chat_cache
    history = chat_cache.get_history(session_id)
    chat_cache.append_turn(session_id, "user", "Is the boiler safe?")
    chat_cache.append_turn(session_id, "assistant", "Yes — all sensors normal.", tool_count=1)
    chat_cache.clear(session_id)
"""
import json
import time
from datetime import datetime, UTC
from typing import Optional

from assistant.config import (
    REDIS_URL,
    REDIS_TLS,
    CHAT_HISTORY_MAX_TURNS,
    CHAT_HISTORY_TTL_SECONDS,
)

try:
    import redis as _redis_lib
    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False


class ChatCache:
    """
    Per-session Redis chat history store.

    Public API:
        get_history(session_id, last_n?) → list[dict]
        get_summary(session_id)          → str | None
        append_turn(session_id, role, content, tool_count?)
        set_summary(session_id, summary)
        clear(session_id)
    """

    def __init__(self) -> None:
        self.client: Optional[object] = None

        if not _REDIS_AVAILABLE:
            print(
                "⚠️  redis package not installed — chat history disabled. "
                "Run: pip install redis>=5.0.0"
            )
            return

        try:
            url = REDIS_URL
            if REDIS_TLS and url.startswith("redis://"):
                url = "rediss://" + url[len("redis://"):]
            self.client = _redis_lib.from_url(
                url,
                decode_responses=True,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
                health_check_interval=30,
            )
            self.client.ping()
            host_part = REDIS_URL.split("@")[-1] if "@" in REDIS_URL else REDIS_URL
            print(f"✅ Redis connected: {host_part}")
        except Exception as exc:
            print(
                f"⚠️  Redis unreachable ({exc}) — chat history disabled. "
                f"Chat will work without conversation memory."
            )
            self.client = None

    # ── Key helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _list_key(sid: str) -> str:
        return f"chat:{sid}"

    @staticmethod
    def _summary_key(sid: str) -> str:
        return f"chat:{sid}:summary"

    @staticmethod
    def _meta_key(sid: str) -> str:
        return f"chat:{sid}:meta"

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_history(
        self,
        session_id: str,
        last_n: Optional[int] = None,
    ) -> list[dict]:
        """
        Return the last `last_n` messages (oldest first) for `session_id`.
        Returns [] if Redis is down or the session has no history.
        """
        if not self.client:
            return []
        n = last_n or CHAT_HISTORY_MAX_TURNS
        try:
            raw = self.client.lrange(self._list_key(session_id), -n, -1)
            return [json.loads(r) for r in raw]
        except Exception as exc:
            print(f"⚠️  Redis read failed: {exc}")
            return []

    def get_summary(self, session_id: str) -> Optional[str]:
        """Return the stored conversation summary, or None."""
        if not self.client:
            return None
        try:
            return self.client.get(self._summary_key(session_id))
        except Exception:
            return None

    def append_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_count: int = 0,
    ) -> None:
        """
        Append one message to the session history.
        Atomically: RPUSH + LTRIM (cap at MAX_TURNS) + EXPIRE (24h TTL).
        Silently skips if Redis is down.
        """
        if not self.client:
            return
        msg = json.dumps({
            "role":       role,
            "content":    content,
            "timestamp":  datetime.now(UTC).isoformat(),
            "tool_count": tool_count,
        })
        key      = self._list_key(session_id)
        meta_key = self._meta_key(session_id)
        try:
            pipe = self.client.pipeline(transaction=True)
            pipe.rpush(key, msg)
            pipe.ltrim(key, -CHAT_HISTORY_MAX_TURNS, -1)
            pipe.expire(key, CHAT_HISTORY_TTL_SECONDS)
            pipe.hset(meta_key, mapping={"last_seen": str(int(time.time()))})
            pipe.hincrby(meta_key, "turn_count", 1)
            pipe.expire(meta_key, CHAT_HISTORY_TTL_SECONDS)
            pipe.execute()
        except Exception as exc:
            print(f"⚠️  Redis write failed: {exc}")

    def set_summary(self, session_id: str, summary: str) -> None:
        """Store a compressed summary string with the same 24h TTL."""
        if not self.client:
            return
        try:
            self.client.set(
                self._summary_key(session_id),
                summary,
                ex=CHAT_HISTORY_TTL_SECONDS,
            )
        except Exception as exc:
            print(f"⚠️  Redis summary write failed: {exc}")

    def clear(self, session_id: str) -> None:
        """Delete all keys for a session (list, summary, meta)."""
        if not self.client:
            return
        try:
            self.client.delete(
                self._list_key(session_id),
                self._summary_key(session_id),
                self._meta_key(session_id),
            )
        except Exception as exc:
            print(f"⚠️  Redis clear failed: {exc}")

    def memory_info(self) -> dict:
        """Return Redis memory stats for /health/redis endpoint."""
        if not self.client:
            return {"status": "down", "message": "Redis not connected"}
        try:
            info = self.client.info("memory")
            return {
                "status":           "up",
                "used_memory_human": info.get("used_memory_human", "N/A"),
                "maxmemory_human":   info.get("maxmemory_human", "N/A"),
                "active_sessions":   len(self.client.keys("chat:*:meta")),
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}


# ── Module-level singleton ─────────────────────────────────────────────────────
# Instantiated once at import time. Thread-safe for concurrent requests.
chat_cache: ChatCache = ChatCache()
