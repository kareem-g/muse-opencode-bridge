#!/usr/bin/env python3
"""OpenAI-compatible bridge that exposes a muse.ai personal agent (via muse-cli) as a model.

Run:
    python bridge.py            # serves on 127.0.0.1:18765
    MUSE_BRIDGE_PORT=9000 python bridge.py

Then point OpenCode (or any OpenAI client) at http://127.0.0.1:<port>/v1
with model id "muse-chat".
"""
import json
import os
import subprocess
import time
from typing import Any, Dict, List

try:
    from fastapi import FastAPI, HTTPException
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

app = FastAPI(title="muse-opencode-bridge")


def extract_user_text(messages: List[Dict[str, Any]]) -> str:
    for m in reversed(messages or []):
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, list):
                parts = []
                for p in c:
                    if isinstance(p, dict) and p.get("type") == "text":
                        parts.append(p.get("text", ""))
                    elif isinstance(p, str):
                        parts.append(p)
                return "\n".join(parts).strip()
            return str(c).strip() if c is not None else ""
    if messages:
        last = messages[-1].get("content")
        return str(last).strip() if last is not None else ""
    return ""


def call_muse(text: str) -> str:
    if not text:
        return ""
    try:
        proc = subprocess.run(
            [MUSE_CLI, "send", text, "--wait", MUSE_WAIT],
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
async def chat_completions(request: Any):
    body = await request.json()
    messages = body.get("messages", [])
    stream = bool(body.get("stream", False))
    text = extract_user_text(messages)
    content = call_muse(text)
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
