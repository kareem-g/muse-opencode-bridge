#!/usr/bin/env python3
"""OpenAI-compatible bridge that exposes a muse.ai personal agent (via muse-cli) as a model.

Run:
    python bridge.py            # serves on 127.0.0.1:18765
    MUSE_BRIDGE_PORT=9000 python bridge.py

Then point OpenCode (or any OpenAI client) at http://127.0.0.1:<port>/v1
with model id "muse-chat".
"""
import hashlib
import json
import os
import re
import subprocess
import time
from typing import Any, Dict, List

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import JSONResponse, StreamingResponse
    import uvicorn
except ImportError as e:  # pragma: no cover
    raise SystemExit(
        "Missing dependency: %s\nInstall with: python3 -m pip install fastapi uvicorn" % e
    )

PORT = int(os.environ.get("MUSE_BRIDGE_PORT", "18765"))
HOST = os.environ.get("MUSE_BRIDGE_HOST", "127.0.0.1")
MODEL_ID = os.environ.get("MUSE_BRIDGE_MODEL", "muse-chat")
MUSE_WAIT = os.environ.get("MUSE_BRIDGE_WAIT", "120")
MUSE_CLI = os.environ.get("MUSE_CLI_BIN", "muse-cli")

STATE_DIR = os.path.expanduser(os.environ.get("MUSE_BRIDGE_STATE_DIR", "~/.config/muse-opencode-bridge"))
STATE_FILE = os.path.join(STATE_DIR, "sessions.json")


def _load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _first_user_text(messages: List[Dict[str, Any]]) -> str:
    for m in messages or []:
        if m.get("role") == "user":
            return _collect_text(m.get("content")).strip()
    return ""


def get_or_create_thread(messages: List[Dict[str, Any]]) -> str:
    key_src = _first_user_text(messages)
    if not key_src:
        key_src = json.dumps(messages[:1], sort_keys=True)
    key = hashlib.sha256(key_src.encode()).hexdigest()[:16]

    state = _load_state()
    if key in state:
        return state[key]

    title = " ".join(key_src.split())[:60] or "opencode session"
    try:
        proc = subprocess.run(
            [MUSE_CLI, "session-start", "--title", title],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="muse-cli session-start timed out")
    if proc.returncode != 0:
        raise HTTPException(status_code=502, detail=proc.stderr.strip() or proc.stdout.strip())
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="invalid JSON from muse-cli: " + proc.stdout[:500])
    sid = data.get("session_id")
    if not sid:
        raise HTTPException(status_code=502, detail="no session_id from muse-cli")
    state[key] = sid
    _save_state(state)
    return sid


app = FastAPI(title="muse-opencode-bridge")


def _read_local_path(path: str) -> str:
    path = path.rstrip(".,:;)")
    try:
        if os.path.isdir(path):
            entries = sorted(os.listdir(path))[:80]
            return "Directory listing for %s:\n%s" % (path, "\n".join(entries))
        if os.path.isfile(path):
            with open(path, "r", errors="replace") as f:
                data = f.read(30000)
            return "Contents of %s:\n%s" % (path, data)
    except Exception:
        return ""
    return ""


def _augment_with_local_files(text: str) -> str:
    candidates = set()
    for m in re.finditer(r"@(/[^\s\"'`]+)", text):
        candidates.add(m.group(1))
    for m in re.finditer(r"(?<!\w)(/[A-Za-z0-9_.\-/]{4,})", text):
        candidates.add(m.group(1))
    extras = []
    for c in candidates:
        p = c.rstrip(".,:;)")
        if os.path.exists(p):
            r = _read_local_path(p)
            if r:
                extras.append(r)
    if extras:
        return (
            text
            + "\n\n--- pasted file contents (do not check the filesystem; use only the text below) ---\n"
            + "\n\n".join(extras)
        )
    return text


def _collect_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict):
                if isinstance(p.get("text"), str):
                    parts.append(p["text"])
                elif p.get("type") in ("text", "input_text", "output_text"):
                    t = p.get("text") or p.get("content")
                    if isinstance(t, str):
                        parts.append(t)
                elif p.get("type") == "file":
                    t = p.get("text") or p.get("content") or p.get("data")
                    if isinstance(t, str):
                        parts.append(t)
        return "\n".join(x for x in parts if x)
    if isinstance(content, dict):
        t = content.get("text") or content.get("content")
        if isinstance(t, str):
            return t
    return str(content)


def extract_user_text(messages: List[Dict[str, Any]]) -> str:
    if not messages:
        return ""
    system_parts = []
    for m in messages:
        if m.get("role") == "system":
            t = _collect_text(m.get("content"))
            if t.strip():
                system_parts.append(t.strip())

    latest = None
    for m in reversed(messages):
        if m.get("role") in ("user", "tool"):
            latest = m
            break
    if latest is None:
        latest = messages[-1]

    body = _collect_text(latest.get("content"))
    role = latest.get("role")
    if role == "tool":
        name = latest.get("name") or latest.get("tool_call_id") or "tool"
        body = "Tool result (%s):\n%s" % (name, body)

    parts = []
    if system_parts:
        parts.append("System:\n" + "\n\n".join(system_parts))
    if body.strip():
        parts.append(body.strip())
    return "\n\n".join(parts).strip()


def call_muse(text: str, thread_id: str = None) -> str:
    if not text:
        return ""
    cmd = [MUSE_CLI, "send", text, "--wait", MUSE_WAIT]
    if thread_id:
        cmd += ["--thread", thread_id]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=int(MUSE_WAIT) + 60,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="muse-cli not found on PATH")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="muse-cli timed out")
    if proc.returncode != 0:
        raise HTTPException(status_code=502, detail=proc.stderr.strip() or proc.stdout.strip())
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="invalid JSON from muse-cli: " + proc.stdout[:500])
    reply = (data.get("reply") or {})
    content = reply.get("text")
    return "" if content is None else str(content)


@app.get("/v1/models")
@app.get("/models")
def models():
    return {
        "object": "list",
        "data": [{"id": MODEL_ID, "object": "model", "created": int(time.time()), "owned_by": "muse.ai"}],
    }


@app.post("/v1/chat/completions")
@app.post("/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    stream = bool(body.get("stream", False))
    thread_id = get_or_create_thread(messages)
    text = extract_user_text(messages)
    text = _augment_with_local_files(text)

    # Retry once if the stored thread is stale/invalid.
    try:
        content = call_muse(text, thread_id)
    except HTTPException as e:
        if e.status_code == 502:
            state = _load_state()
            key_src = _first_user_text(messages) or json.dumps(messages[:1], sort_keys=True)
            key = hashlib.sha256(key_src.encode()).hexdigest()[:16]
            state.pop(key, None)
            _save_state(state)
            thread_id = get_or_create_thread(messages)
            content = call_muse(text, thread_id)
        else:
            raise
    created = int(time.time())
    cid = "chatcmpl-muse-" + str(created)

    if not stream:
        return JSONResponse(
            {
                "id": cid,
                "object": "chat.completion",
                "created": created,
                "model": MODEL_ID,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }
        )

    def gen():
        chunk = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": MODEL_ID,
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": content}, "finish_reason": None}],
        }
        yield "data: " + json.dumps(chunk) + "\n\n"
        done_chunk = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": MODEL_ID,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield "data: " + json.dumps(done_chunk) + "\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
