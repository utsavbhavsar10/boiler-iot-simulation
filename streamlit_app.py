"""
Streamlit UI for the Boiler Agentic RAG system — ChatGPT/Claude-style.

Talks to the FastAPI service at API_URL:
  GET  /health        — service health
  GET  /status        — live sensor readings + recent faults
  POST /chat          — non-streaming chat
  POST /chat/stream   — Server-Sent Events stream

Run alongside uvicorn:
    streamlit run streamlit_app.py
"""
import os
import json
import time
from datetime import datetime

import requests
import streamlit as st

API_URL = os.getenv("BOILER_API_URL", "http://localhost:8000")
REQUEST_TIMEOUT = 120

st.set_page_config(
    page_title="Boiler AI",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Styling ──────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    /* App background */
    .stApp {
        background: linear-gradient(180deg, #0f1115 0%, #14171d 100%);
    }
    /* Main content width */
    .block-container {
        max-width: 880px;
        padding-top: 1.2rem;
        padding-bottom: 6rem;
    }
    /* Chat bubbles */
    [data-testid="stChatMessage"] {
        background: transparent !important;
        border: none !important;
        padding: 0.4rem 0 !important;
    }
    [data-testid="stChatMessage"] [data-testid="stChatMessageContent"] {
        background: #1c2027;
        border: 1px solid #262b34;
        border-radius: 14px;
        padding: 14px 18px;
        color: #e6e8ec;
        line-height: 1.55;
        font-size: 15px;
    }
    /* User bubble distinct */
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"])
        [data-testid="stChatMessageContent"] {
        background: #2b6cb0;
        border-color: #2b6cb0;
        color: #fff;
    }
    /* Tool-call card */
    .tool-card {
        background: #161a21;
        border: 1px solid #2a2f3a;
        border-left: 3px solid #f59e0b;
        border-radius: 10px;
        padding: 10px 14px;
        margin: 6px 0;
        font-family: ui-monospace, "SF Mono", Menlo, monospace;
        font-size: 13px;
        color: #cbd5e1;
    }
    .tool-card.done { border-left-color: #10b981; }
    .tool-card .tname { color: #f59e0b; font-weight: 600; }
    .tool-card.done .tname { color: #10b981; }
    .tool-card .targs { color: #94a3b8; font-size: 12px; }
    .tool-card pre {
        background: #0d1015; color: #cbd5e1;
        padding: 8px 10px; border-radius: 6px;
        margin: 8px 0 0 0; font-size: 12px;
        white-space: pre-wrap; word-break: break-word;
        max-height: 180px; overflow-y: auto;
    }
    .status-pill {
        display: inline-block;
        background: #1f2530; color: #94a3b8;
        padding: 4px 10px; border-radius: 999px;
        font-size: 12px; margin: 4px 0;
    }
    .status-pill .dot {
        display: inline-block; width: 8px; height: 8px;
        background: #f59e0b; border-radius: 50%;
        margin-right: 6px; animation: pulse 1.2s infinite;
    }
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50%      { opacity: 0.35; }
    }
    /* Chat input */
    [data-testid="stChatInput"] {
        background: #1c2027;
        border: 1px solid #2a2f3a;
        border-radius: 14px;
    }
    /* Hide footer */
    footer { visibility: hidden; }
    /* Sidebar */
    [data-testid="stSidebar"] {
        background: #0c0e12;
        border-right: 1px solid #1d2129;
    }
    .small-muted { color: #7a8190; font-size: 12px; }
    .meta-bar {
        color: #7a8190; font-size: 12px; margin-top: 4px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

TOOL_LABEL = {
    "fetch_realtime_sensors": ("📡", "Reading live sensors"),
    "get_fault_history":      ("📜", "Checking recent faults"),
    "predict_trend":          ("📈", "Predicting trend (Chronos AI)"),
    "search_knowledge_base":  ("📚", "Searching knowledge base"),
    "get_chronos_forecast":   ("🧠", "Running Chronos probabilistic forecast"),
}

# ── Sidebar ──────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🔥 Boiler AI")
    st.caption("Fine-tuned Gemini · Agentic RAG")

    api_url = st.text_input("API URL", value=API_URL, label_visibility="collapsed")

    # API Health
    try:
        h = requests.get(f"{api_url}/health", timeout=3).json()
        st.markdown(
            f"<span class='status-pill' style='background:#0f3a2a;color:#34d399'>"
            f"● online · {h.get('timestamp','')[11:19]}</span>",
            unsafe_allow_html=True,
        )
    except Exception:
        st.markdown(
            "<span class='status-pill' style='background:#3a1414;color:#f87171'>"
            "● offline</span>",
            unsafe_allow_html=True,
        )

    # Chronos Forecast Health
    try:
        ch = requests.get(f"{api_url}/health/chronos", timeout=3).json()
        c_status = ch.get("status", "unknown")
        c_sensors = ch.get("sensors_forecasted", 0)
        c_total   = ch.get("sensors_total", 0)
        c_warn    = ch.get("sensors_with_warnings", 0)
        c_crit    = ch.get("sensors_with_critical", 0)
        c_age     = ch.get("cache_age_seconds")
        age_str   = f"{int(c_age)}s ago" if c_age is not None else "—"

        if c_status == "healthy":
            badge_style = "background:#0f3a2a;color:#34d399"
            badge_text  = f"🧠 Chronos ✅ {c_sensors}/{c_total} sensors · {age_str}"
        elif c_status == "warming_up":
            badge_style = "background:#2a2200;color:#fbbf24"
            badge_text  = "🧠 Chronos ⏳ warming up…"
        else:
            badge_style = "background:#3a1414;color:#f87171"
            badge_text  = f"🧠 Chronos ⚠️ stale ({age_str})"

        st.markdown(
            f"<span class='status-pill' style='{badge_style}'>{badge_text}</span>",
            unsafe_allow_html=True,
        )
        if c_crit > 0:
            st.markdown(
                f"<span class='status-pill' style='background:#3a1414;color:#f87171'>"
                f"🚨 {c_crit} sensor(s) approaching CRITICAL</span>",
                unsafe_allow_html=True,
            )
        elif c_warn > 0:
            st.markdown(
                f"<span class='status-pill' style='background:#2a1f00;color:#fbbf24'>"
                f"⚠️ {c_warn} sensor(s) approaching WARNING</span>",
                unsafe_allow_html=True,
            )
    except Exception:
        st.markdown(
            "<span class='status-pill' style='background:#1f2530;color:#7a8190'>"
            "🧠 Chronos: unavailable</span>",
            unsafe_allow_html=True,
        )

    st.divider()
    nav = st.radio("View", ["💬 Chat", "📊 Live Status"], label_visibility="collapsed")
    st.divider()

    if st.button("🧹 New chat", use_container_width=True):
        st.session_state.history = []
        st.rerun()

    st.markdown(
        "<div class='small-muted'>Devices<br>"
        "• BOILER_001 (boiler + turbine)<br>"
        "• CHIMNEY_001 (flue + draft)</div>",
        unsafe_allow_html=True,
    )

# ── State ────────────────────────────────────────────────────────────
if "history" not in st.session_state:
    st.session_state.history = []


def render_tool_card(step: dict, done: bool = True) -> str:
    icon, label = TOOL_LABEL.get(step["tool"], ("🛠", step["tool"]))
    klass = "tool-card done" if done else "tool-card"
    args  = step.get("args", {})
    args_str = ", ".join(f"{k}={v}" for k, v in args.items()) or "—"
    preview = step.get("result_preview", "")
    body = ""
    if done and preview:
        body = f"<pre>{preview}</pre>"
    return (
        f"<div class='{klass}'>"
        f"<span class='tname'>{icon} {label}</span>"
        f"<div class='targs'>{args_str}</div>"
        f"{body}"
        f"</div>"
    )


def render_history():
    for turn in st.session_state.history:
        with st.chat_message("user"):
            st.markdown(turn["question"])
        with st.chat_message("assistant", avatar="🔥"):
            if turn.get("steps"):
                with st.expander(
                    f"🛠 Used {turn['total_steps']} tool(s) · {turn['latency_ms']} ms",
                    expanded=False,
                ):
                    for s in turn["steps"]:
                        st.markdown(render_tool_card(s, done=True), unsafe_allow_html=True)
            st.markdown(turn["answer"])


def stream_chat(question: str):
    """POST to /chat/stream and yield parsed SSE events."""
    with requests.post(
        f"{api_url}/chat/stream",
        json={"question": question, "session_id": "streamlit"},
        stream=True,
        timeout=REQUEST_TIMEOUT,
    ) as r:
        r.raise_for_status()
        for raw in r.iter_lines(decode_unicode=True):
            if not raw:
                continue
            if raw.startswith("data:"):
                payload = raw[5:].strip()
                if not payload:
                    continue
                try:
                    yield json.loads(payload)
                except json.JSONDecodeError:
                    continue


# ── Live Status view ─────────────────────────────────────────────────
if nav == "📊 Live Status":
    st.markdown("## 📊 Live Status")
    auto_refresh = st.toggle("Auto-refresh", value=True)
    refresh_secs = st.slider("Every (s)", 2, 30, 5, disabled=not auto_refresh)
    placeholder  = st.empty()

    try:
        r = requests.get(f"{api_url}/status", timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        placeholder.error(f"Could not reach {api_url}/status — {e}")
        st.stop()

    sensors_text = str(data.get("sensors", ""))
    faults_text  = str(data.get("faults", ""))
    ts           = data.get("timestamp", "")

    critical = "CRITICAL" in sensors_text or "CRITICAL" in faults_text
    warning  = ("WARNING" in sensors_text or "WARNING" in faults_text
                or "OUT_OF_RANGE" in sensors_text)

    with placeholder.container():
        c1, c2, c3 = st.columns(3)
        if critical:   c1.error("🚨 CRITICAL")
        elif warning:  c1.warning("⚠️ WARNING")
        else:          c1.success("✅ NORMAL")
        c2.metric("Last update", ts[11:19] if ts else "—")
        c3.metric("Polled", datetime.now().strftime("%H:%M:%S"))

        left, right = st.columns(2)
        with left:
            st.markdown("**Sensors**")
            st.code(sensors_text, language="text")
        with right:
            st.markdown("**Recent faults (last 60 min)**")
            st.code(faults_text, language="text")

    if auto_refresh:
        time.sleep(refresh_secs)
        st.rerun()
    st.stop()

# ── Chat view ────────────────────────────────────────────────────────
st.markdown("## 💬 Ask Boiler-AI")
st.caption("Diagnoses faults, predicts trends, and Chronos AI forecasts upcoming sensor breaches.")

# Empty state
if not st.session_state.history:
    st.markdown(
        """
        <div style='text-align:center;color:#7a8190;padding:30px 0;'>
            <div style='font-size:42px;margin-bottom:8px;'>🔥</div>
            <div style='font-size:18px;color:#cbd5e1;margin-bottom:14px;'>
                How can I help with the boiler today?
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns(2)
    suggestions = [
        "Is the boiler safe right now?",
        "Why might feedwater pressure be low?",
        "Will any sensor breach a critical threshold in the next 30 minutes?",
        "Predict if flue gas temperature will breach the limit.",
        "Is anything about to fail? Scan all sensors.",
        "Show me recent faults and their causes.",
    ]
    clicked = None
    for i, sug in enumerate(suggestions):
        if cols[i % 2].button(sug, use_container_width=True, key=f"sug_{i}"):
            clicked = sug
    if clicked:
        st.session_state["_pending_q"] = clicked
        st.rerun()

render_history()

# Input — accept either typed or pending suggestion
typed_q = st.chat_input("Ask about the boiler, faults, or trends…")
q = typed_q or st.session_state.pop("_pending_q", None)

if q:
    # Render user message immediately
    with st.chat_message("user"):
        st.markdown(q)

    # Assistant turn with live updates
    with st.chat_message("assistant", avatar="🔥"):
        status_slot = st.empty()
        tools_slot  = st.empty()
        answer_slot = st.empty()

        steps: list[dict] = []
        live_step: dict | None = None
        answer_text = ""
        meta = {"total_steps": 0, "latency_ms": 0}

        def repaint_tools():
            html = ""
            for s in steps:
                html += render_tool_card(s, done=True)
            if live_step is not None:
                html += render_tool_card(live_step, done=False)
            tools_slot.markdown(html, unsafe_allow_html=True)

        try:
            for evt in stream_chat(q):
                t = evt.get("type")

                if t == "status":
                    status_slot.markdown(
                        f"<div class='status-pill'><span class='dot'></span>"
                        f"{evt.get('message','Working…')}</div>",
                        unsafe_allow_html=True,
                    )

                elif t == "tool_start":
                    live_step = {
                        "step": evt["step"],
                        "tool": evt["tool"],
                        "args": evt.get("args", {}),
                        "result_preview": "",
                    }
                    status_slot.markdown(
                        f"<div class='status-pill'><span class='dot'></span>"
                        f"Calling <b>{evt['tool']}</b>…</div>",
                        unsafe_allow_html=True,
                    )
                    repaint_tools()

                elif t == "tool_end":
                    if live_step and live_step["tool"] == evt["tool"]:
                        live_step["result_preview"] = evt.get("result_preview", "")
                        steps.append(live_step)
                        live_step = None
                    repaint_tools()

                elif t == "answer_chunk":
                    status_slot.empty()
                    answer_text += evt.get("text", "")
                    answer_slot.markdown(answer_text + " ▌")

                elif t == "done":
                    meta["total_steps"] = evt.get("total_steps", len(steps))
                    meta["latency_ms"]  = evt.get("latency_ms", 0)
                    if not answer_text:
                        answer_text = evt.get("answer", "")
                    answer_slot.markdown(answer_text)
                    status_slot.empty()
                    if steps:
                        tools_slot.empty()
                        with tools_slot.container():
                            with st.expander(
                                f"🛠 Used {meta['total_steps']} tool(s) · "
                                f"{meta['latency_ms']} ms",
                                expanded=False,
                            ):
                                for s in steps:
                                    st.markdown(render_tool_card(s, done=True),
                                                unsafe_allow_html=True)
                    break

                elif t == "error":
                    status_slot.error(evt.get("message", "Unknown error"))
                    break

        except requests.exceptions.RequestException as e:
            status_slot.error(f"Connection error: {e}")
            st.stop()

    st.session_state.history.append({
        "question":    q,
        "answer":      answer_text or "(no answer)",
        "steps":       steps,
        "total_steps": meta["total_steps"],
        "latency_ms":  meta["latency_ms"],
    })
