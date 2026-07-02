# Redis Chat History Cache — Implementation Guide

End-to-end guide for adding a free-tier Redis cluster as the recent chat-history store for the Boiler Agentic RAG chatbot. Covers provider selection, schema, FastAPI integration, eviction, and operational concerns.

---

## 1. Goal & Scope

**Goal:** Persist the last N turns of each chat session in Redis so the agent can use prior context (follow-up questions, "what about chimney?", "expand on step 2") without re-asking the user.

**Non-goals:**
- Long-term analytics storage (use Postgres / Influx for that).
- Vector / semantic search over history (use Chroma).
- Full conversation logging for audit (write to disk separately).

**What lives in Redis:**
- Per-session list of `{role, content, timestamp}` messages.
- Optional per-session summary string once history exceeds N turns.

**What does NOT live in Redis:**
- Tool results (regenerated each turn).
- Sensor data (Influx).
- Vector embeddings (Chroma).

---

## 2. Free-Tier Provider Comparison

| Provider | Free Tier | Persistence | TLS | Notes |
|---|---|---|---|---|
| **Upstash Redis** | 10k commands/day, 256 MB | Yes | Yes | REST + TCP. Best free tier for serverless. Region-pinned. |
| **Redis Cloud (Redis Inc.)** | 30 MB, 30 connections | Yes | Yes | Official Redis. 30 MB tight but fine for chat history. |
| **Render Redis** | 25 MB, 50 connections, **deleted after 90 days** | No | Yes | Easy if already on Render. Ephemeral. |
| **Aiven Redis** | $300 trial credit (~1 month) | Yes | Yes | Not truly free — trial only. |
| **Local Docker Redis** | Unlimited | Optional (AOF/RDB) | No (by default) | Best for dev. Add to `docker-compose.yml`. |

**Recommendation:**
- **Dev:** local Redis container in `docker-compose.yml` (free, fast, no rate limit).
- **Prod free tier:** Upstash (highest free quota, REST fallback if TCP blocked).

---

## 3. Architecture

```
┌─────────────┐    POST /chat        ┌────────────────────┐
│  Frontend   │ ───────────────────▶ │  FastAPI           │
│ (Streamlit) │   {session_id, q}    │  chatbot_api.py    │
└─────────────┘                      └─────────┬──────────┘
                                               │
                          ┌────────────────────┼────────────────────┐
                          │                    │                    │
                          ▼                    ▼                    ▼
                  ┌──────────────┐    ┌────────────────┐   ┌────────────────┐
                  │  Redis       │    │ Orchestrator   │   │ InfluxDB       │
                  │  chat:{sid}  │    │ (Gemini + tools)│  │ (sensors)      │
                  │  LIST<JSON>  │    └────────────────┘   └────────────────┘
                  └──────────────┘
```

**Flow per request:**
1. Client sends `{session_id, question}`.
2. API loads last N messages from Redis (`LRANGE chat:{sid} -N -1`).
3. History prepended to `user_question` before `agent.run_stream(...)`.
4. After answer streamed, API writes `user` turn + `assistant` turn back to Redis (`RPUSH` + `LTRIM` to cap length).
5. TTL refreshed on each write (`EXPIRE chat:{sid} 86400`).

---

## 4. Redis Key Schema

| Key pattern | Type | TTL | Purpose |
|---|---|---|---|
| `chat:{session_id}` | LIST | 24h | Ordered JSON messages, oldest at index 0. |
| `chat:{session_id}:summary` | STRING | 24h | Compressed summary once list exceeds `MAX_TURNS`. |
| `chat:{session_id}:meta` | HASH | 24h | `created_at`, `last_seen`, `turn_count`. |

**Message JSON shape:**

```json
{
  "role": "user" | "assistant",
  "content": "string",
  "timestamp": "2026-06-22T10:34:11Z",
  "tool_count": 0
}
```

**Why LIST not STREAM:**
- We always read tail-N and trim head — perfect fit for `LRANGE` + `LTRIM`.
- Streams are overkill (no consumer groups needed, no exactly-once delivery).
- Free tiers count memory — JSON-encoded list ≈ 100 bytes/turn × 20 turns = ~2 KB/session.

---

## 5. Configuration

### `.env` additions

```bash
REDIS_URL=redis://default:<password>@<host>:<port>
REDIS_TLS=true                 # Upstash + Redis Cloud require TLS
CHAT_HISTORY_MAX_TURNS=20      # last 20 messages kept (10 user + 10 assistant)
CHAT_HISTORY_TTL_SECONDS=86400 # 24h idle expiry
CHAT_SUMMARY_THRESHOLD=20      # summarize once list exceeds this
```

### `assistant/config.py` additions

```python
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_TLS = os.getenv("REDIS_TLS", "false").lower() == "true"
CHAT_HISTORY_MAX_TURNS = int(os.getenv("CHAT_HISTORY_MAX_TURNS", "20"))
CHAT_HISTORY_TTL_SECONDS = int(os.getenv("CHAT_HISTORY_TTL_SECONDS", "86400"))
CHAT_SUMMARY_THRESHOLD = int(os.getenv("CHAT_SUMMARY_THRESHOLD", "20"))
```

### `requirements.txt`

```
redis>=5.0.0
```

### `docker-compose.yml` (local dev)

```yaml
services:
  redis:
    image: redis:7-alpine
    container_name: boiler-redis
    ports:
      - "6379:6379"
    command: ["redis-server", "--appendonly", "yes", "--maxmemory", "64mb", "--maxmemory-policy", "allkeys-lru"]
    volumes:
      - redis-data:/data
    restart: unless-stopped

volumes:
  redis-data:
```

---

## 6. Cache Module — `assistant/cache/chat_cache.py`

Single responsibility: read/write per-session message history.

```python
"""Redis-backed chat history cache."""
import json
import time
from datetime import datetime, UTC
from typing import Optional

import redis

from assistant.config import (
    REDIS_URL,
    REDIS_TLS,
    CHAT_HISTORY_MAX_TURNS,
    CHAT_HISTORY_TTL_SECONDS,
)


class ChatCache:
    def __init__(self):
        self.client = redis.from_url(
            REDIS_URL,
            decode_responses=True,
            ssl=REDIS_TLS,
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
            health_check_interval=30,
        )
        try:
            self.client.ping()
            print(f"✅ Redis connected: {REDIS_URL.split('@')[-1]}")
        except redis.RedisError as e:
            print(f"⚠️  Redis unreachable: {e}. Falling back to no-cache mode.")
            self.client = None

    # ── Keys ────────────────────────────────────────────────────────────
    @staticmethod
    def _list_key(session_id: str) -> str:
        return f"chat:{session_id}"

    @staticmethod
    def _summary_key(session_id: str) -> str:
        return f"chat:{session_id}:summary"

    @staticmethod
    def _meta_key(session_id: str) -> str:
        return f"chat:{session_id}:meta"

    # ── Public API ──────────────────────────────────────────────────────
    def get_history(self, session_id: str, last_n: Optional[int] = None) -> list[dict]:
        """Returns oldest-first list of message dicts. Empty list if no cache."""
        if not self.client:
            return []
        n = last_n or CHAT_HISTORY_MAX_TURNS
        try:
            raw = self.client.lrange(self._list_key(session_id), -n, -1)
            return [json.loads(r) for r in raw]
        except redis.RedisError as e:
            print(f"⚠️  Redis read failed: {e}")
            return []

    def get_summary(self, session_id: str) -> Optional[str]:
        if not self.client:
            return None
        try:
            return self.client.get(self._summary_key(session_id))
        except redis.RedisError:
            return None

    def append_turn(self, session_id: str, role: str, content: str, tool_count: int = 0) -> None:
        """Append one message. Auto-trims to MAX_TURNS. Refreshes TTL."""
        if not self.client:
            return
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(UTC).isoformat(),
            "tool_count": tool_count,
        }
        key = self._list_key(session_id)
        try:
            pipe = self.client.pipeline(transaction=True)
            pipe.rpush(key, json.dumps(msg))
            pipe.ltrim(key, -CHAT_HISTORY_MAX_TURNS, -1)
            pipe.expire(key, CHAT_HISTORY_TTL_SECONDS)
            pipe.hset(
                self._meta_key(session_id),
                mapping={"last_seen": str(int(time.time()))},
            )
            pipe.hincrby(self._meta_key(session_id), "turn_count", 1)
            pipe.expire(self._meta_key(session_id), CHAT_HISTORY_TTL_SECONDS)
            pipe.execute()
        except redis.RedisError as e:
            print(f"⚠️  Redis write failed: {e}")

    def set_summary(self, session_id: str, summary: str) -> None:
        if not self.client:
            return
        try:
            self.client.set(
                self._summary_key(session_id),
                summary,
                ex=CHAT_HISTORY_TTL_SECONDS,
            )
        except redis.RedisError:
            pass

    def clear(self, session_id: str) -> None:
        if not self.client:
            return
        try:
            self.client.delete(
                self._list_key(session_id),
                self._summary_key(session_id),
                self._meta_key(session_id),
            )
        except redis.RedisError:
            pass


chat_cache = ChatCache()
```

**Design notes:**
- Single-process singleton — Redis connection is cheap and thread-safe.
- Fails open: if Redis is down, returns `[]` and continues. Chat works without history rather than 500-ing.
- Pipeline groups RPUSH + LTRIM + EXPIRE atomically — no race on truncation.
- Uses `socket_timeout=2s` so a dead Redis can't hang chat requests.

---

## 7. Orchestrator Integration

Pass history into `agent.run_stream(...)`. Cleanest way: change signature to accept an optional `history` list and format it into the user prompt.

### `assistant/agent/orchestrator.py` — modify `run_stream`

```python
def run_stream(self, user_question: str, history: list[dict] | None = None, summary: str | None = None):
    ...
    history_block = ""
    if summary:
        history_block += f"=== PRIOR CONVERSATION SUMMARY ===\n{summary}\n\n"
    if history:
        lines = ["=== RECENT MESSAGES (oldest first) ==="]
        for m in history:
            tag = "USER" if m["role"] == "user" else "ASSISTANT"
            lines.append(f"[{tag}] {m['content']}")
        lines.append("=== END HISTORY ===\n")
        history_block += "\n".join(lines) + "\n\n"

    enriched_question = chronos_block + history_block + user_question
    messages = [Content(role="user", parts=[Part.from_text(enriched_question)])]
    ...
```

**Why prepend to user turn, not multi-turn `Content` history:**
- Gemini multi-turn with function-calling needs the **full tool-call/tool-result chain** for each prior turn, which we don't store. Storing only `{user, assistant}` text in Redis is enough for context but breaks Gemini's function-call schema if replayed as model turns.
- Prepending as text avoids that mismatch. Token cost is identical.

---

## 8. API Wiring — `api/chatbot_api.py`

### Request model

```python
class ChatRequest(BaseModel):
    session_id: str           # client-generated UUID per chat tab
    question: str
    use_history: bool = True  # client can opt out
```

### Streaming endpoint

```python
from assistant.cache.chat_cache import chat_cache

@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    history = chat_cache.get_history(req.session_id) if req.use_history else []
    summary = chat_cache.get_summary(req.session_id) if req.use_history else None

    # Save user turn BEFORE inference — recoverable if model fails
    chat_cache.append_turn(req.session_id, "user", req.question)

    final_answer = {"text": "", "tool_count": 0}

    def event_stream():
        for ev in agent.run_stream(req.question, history=history, summary=summary):
            if ev["type"] == "answer_chunk":
                final_answer["text"] += ev["text"]
            elif ev["type"] == "tool_end":
                final_answer["tool_count"] += 1
            yield f"data: {json.dumps(ev)}\n\n"

        # Save assistant turn after streaming completes
        if final_answer["text"]:
            chat_cache.append_turn(
                req.session_id,
                "assistant",
                final_answer["text"],
                tool_count=final_answer["tool_count"],
            )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.delete("/chat/{session_id}")
def clear_chat(session_id: str):
    chat_cache.clear(session_id)
    return {"ok": True}
```

---

## 9. Summarization (When History > N Turns)

Once history exceeds `CHAT_SUMMARY_THRESHOLD`, compress old turns to a one-paragraph summary and keep only the most recent N raw turns.

### `assistant/cache/summarizer.py`

```python
from vertexai.generative_models import GenerativeModel
from assistant.config import CHAT_SUMMARY_THRESHOLD

_summarizer = GenerativeModel("gemini-2.5-flash")

SUMMARY_PROMPT = """Summarize the following boiler chatbot conversation into 3-5 bullets.
Preserve: sensor names mentioned, fault codes, user's stated concern, key decisions made.
Drop: pleasantries, tool result tables, redundant restatements.

CONVERSATION:
{conversation}

SUMMARY:"""


def summarize(messages: list[dict]) -> str:
    convo = "\n".join(f"[{m['role'].upper()}] {m['content']}" for m in messages)
    resp = _summarizer.generate_content(SUMMARY_PROMPT.format(conversation=convo))
    return resp.text.strip()


def maybe_compress(session_id: str, cache) -> None:
    history = cache.get_history(session_id, last_n=1000)
    if len(history) < CHAT_SUMMARY_THRESHOLD:
        return
    old = history[:-CHAT_HISTORY_MAX_TURNS]
    summary = summarize(old)
    cache.set_summary(session_id, summary)
    # Optional: trim list to only recent N (LTRIM does this on append anyway)
```

Call `maybe_compress(session_id, chat_cache)` from a background task after each `/chat/stream` request, OR run it on a cron every 5 min for active sessions.

---

## 10. Eviction & Memory Budget

Free-tier limits force discipline:

| Tier | Budget | Sessions @ 2 KB each |
|---|---|---|
| Upstash 256 MB | 256 MB | ~131,000 |
| Redis Cloud 30 MB | 30 MB | ~15,000 |
| Render 25 MB | 25 MB | ~12,500 |

**Eviction layers (apply all three):**
1. **TTL** — `EXPIRE chat:{sid} 86400` on every write. Idle sessions auto-die in 24h.
2. **List trim** — `LTRIM` to `MAX_TURNS` on every append. Per-session memory bounded.
3. **Server policy** — `maxmemory-policy allkeys-lru` (free-tier providers usually default to this). Worst-case the oldest sessions evict first.

**Monitoring:**
```python
@app.get("/health/redis")
def redis_health():
    if not chat_cache.client:
        return {"status": "down"}
    info = chat_cache.client.info("memory")
    return {
        "status": "up",
        "used_memory_human": info.get("used_memory_human"),
        "maxmemory_human": info.get("maxmemory_human"),
        "active_sessions": len(chat_cache.client.keys("chat:*:meta")),
    }
```

(`KEYS` is OK at low scale. Switch to `SCAN` if active_sessions > 10k.)

---

## 11. Security

- **Never log `REDIS_URL`** in plain text — it contains the password. Mask before printing.
- **TLS on for any non-localhost** Redis. Upstash/Redis-Cloud force this.
- **Session IDs must be client-generated UUIDs**, not sequential. Sequential IDs let one user read another's history via `chat:1`, `chat:2`, ...
- **Treat history as untrusted** when prepending to the prompt — same prompt-injection rules apply.
- **Do NOT cache tool results** in Redis. They include live sensor data that may be sensitive and they regenerate cheaply.

---

## 12. Frontend Changes (Streamlit)

`streamlit_app.py` needs:

```python
import uuid

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

# Per request
payload = {
    "session_id": st.session_state.session_id,
    "question": user_input,
    "use_history": True,
}

# Clear button
if st.button("🗑 Clear chat"):
    requests.delete(f"{API_URL}/chat/{st.session_state.session_id}")
    st.session_state.messages = []
    st.session_state.session_id = str(uuid.uuid4())
```

---

## 13. Testing Checklist

- [ ] `redis-cli -u $REDIS_URL ping` returns `PONG` from app host.
- [ ] First chat turn → `LLEN chat:{sid}` returns `2` (user + assistant).
- [ ] Send 25 turns → `LLEN` stays at `CHAT_HISTORY_MAX_TURNS`.
- [ ] Wait 24h+ → key disappears (`EXISTS chat:{sid}` returns `0`).
- [ ] Kill Redis → `/chat/stream` still returns answer (degraded, no history).
- [ ] Follow-up question references prior turn correctly ("expand on step 2").
- [ ] `DELETE /chat/{sid}` clears all three keys.

---

## 14. Rollout Order

1. Add Redis to `docker-compose.yml`, run locally.
2. Add `redis` to `requirements.txt`, install.
3. Create `assistant/cache/chat_cache.py`, init at API startup, verify `/health/redis`.
4. Modify orchestrator `run_stream` to accept history/summary kwargs.
5. Wire `chat_cache.get_history` + `append_turn` into `/chat/stream`.
6. Update Streamlit frontend to send `session_id`.
7. Add `summarizer.maybe_compress` background call.
8. Provision Upstash (or chosen provider), set `REDIS_URL` in prod env.
9. Smoke test follow-up questions.
10. Monitor `/health/redis` memory usage for one week.

---

## 15. Future Extensions

- **Per-user namespacing:** `chat:{user_id}:{session_id}` once auth lands.
- **Semantic recall:** embed each turn, store vector in Chroma, retrieve top-K relevant prior turns instead of last-N. Useful when sessions get long.
- **Tool-result caching:** Redis SETEX of `tool:{tool_name}:{args_hash}` for 30s — cuts Influx load on repeated "what's current temp" queries.
- **Cross-session knowledge:** aggregate frequently-asked questions for analytics (separate key namespace).
