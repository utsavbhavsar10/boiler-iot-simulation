# Boiler-AI Frontend

Next.js 14 (App Router) · TypeScript · Tailwind · Recharts.

## Run

```bash
cd Frontend
npm install
cp .env.local.example .env.local   # edit if backend not on :8000
npm run dev
```

Open http://localhost:3000.

Backend FastAPI must be running on `NEXT_PUBLIC_API_BASE` (default `http://localhost:8000`).
Start it from project root:

```bash
uvicorn api.chatbot_api:app --reload --port 8000
```

## Pages

- `/`     — realtime dashboard (sensor cards, trend charts, faults, auto-refresh every 3s)
- `/chat` — agentic assistant (streams tool calls + answer via `/chat/stream`)

## Backend endpoints used

- `GET  /health`       → connectivity badge
- `GET  /status`       → sensors + faults snapshot
- `POST /chat/stream`  → SSE: `status`, `tool_start`, `tool_end`, `answer_chunk`, `done`, `error`
