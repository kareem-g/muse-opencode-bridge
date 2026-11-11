#!/usr/bin/env python3
"""Minimal MCP (stdio) server exposing muse-cli commands as tools for OpenCode."""
import json
import os
import subprocess
import sys

MUSE_CLI = os.environ.get("MUSE_CLI_BIN", "muse-cli")


def run_cli(args, timeout=180):
    try:
        proc = subprocess.run(
            [MUSE_CLI] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return {"error": "muse-cli not found on PATH"}
    except subprocess.TimeoutExpired:
        return {"error": "muse-cli timed out"}
    out = proc.stdout.strip()
    err = proc.stderr.strip()
    if proc.returncode != 0:
        return {"error": err or out or "muse-cli failed (exit %d)" % proc.returncode}
    # Try to parse JSON for nicer output
    try:
        return {"result": json.loads(out)}
    except (json.JSONDecodeError, ValueError):
        return {"result": out}


TOOLS = [
    {
        "name": "muse_status",
        "description": "Get muse.ai agent status (VM id, chats, unread, identity).",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "muse_threads",
        "description": "List main chat and side chats (session ids).",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "muse_history",
        "description": "Read recent messages from the main chat or a side chat.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "thread": {"type": "string", "description": "Side chat session id (optional, defaults to main chat)"},
                "limit": {"type": "integer", "description": "Number of messages (default 10)"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "muse_send",
        "description": "Send a message to the muse.ai agent and wait for its reply.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message to send"},
                "thread": {"type": "string", "description": "Side chat session id (optional)"},
                "wait": {"type": "integer", "description": "Seconds to wait for reply (default 120)"},
            },
            "required": ["message"],
            "additionalProperties": False,
        },
    },
    {
        "name": "muse_goals",
        "description": "List goals.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "muse_ideas",
        "description": "List ideas.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "muse_feed",
        "description": "Read the agent feed.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "Number of items (default 10)"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "muse_files",
        "description": "List files (images/videos) produced by the agent.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "Number of items (default 20)"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "muse_unread",
        "description": "Get unread counts.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "muse_session_start",
        "description": "Start a new side chat.",
        "inputSchema": {
            "type": "object",
            "properties": {"title": {"type": "string", "description": "Title for the side chat"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "muse_raw",
        "description": "Escape hatch: call any muse-cli gateway method.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "method": {"type": "string", "description": "Gateway method name"},
                "body": {"type": "string", "description": "JSON body (optional)"},
            },
            "required": ["method"],
            "additionalProperties": False,
        },
    },
]


def call_tool(name, args):
    args = args or {}
    if name == "muse_status":
        return run_cli(["status"])
    if name == "muse_threads":
        return run_cli(["threads"])
    if name == "muse_history":
        cmd = ["history"]
        if args.get("thread"):
            cmd += ["--thread", args["thread"]]
        if args.get("limit"):
            cmd += ["--limit", str(args["limit"])]
        return run_cli(cmd)
    if name == "muse_send":
        msg = args.get("message", "")
        cmd = ["send", msg]
        if args.get("thread"):
            cmd += ["--thread", args["thread"]]
        wait = args.get("wait", 120)
        cmd += ["--wait", str(wait)]
        res = run_cli(cmd, timeout=int(wait) + 60)
        # Simplify: return reply text when present
        if isinstance(res, dict) and isinstance(res.get("result"), dict):
            reply = res["result"].get("reply")
            if isinstance(reply, dict) and "text" in reply:
                return {"reply": reply["text"], "raw": res["result"]}
        return res
    if name == "muse_goals":
        return run_cli(["goals"])
    if name == "muse_ideas":
        return run_cli(["ideas"])
    if name == "muse_feed":
        cmd = ["feed"]
        if args.get("limit"):
            cmd += ["--limit", str(args["limit"])]
        return run_cli(cmd)
    if name == "muse_files":
        cmd = ["files"]
        if args.get("limit"):
            cmd += ["--limit", str(args["limit"])]
        return run_cli(cmd)
    if name == "muse_unread":
        return run_cli(["unread"])
    if name == "muse_session_start":
        cmd = ["session-start"]
        if args.get("title"):
            cmd += ["--title", args["title"]]
        return run_cli(cmd)
    if name == "muse_raw":
        cmd = ["raw", args["method"]]
        if args.get("body"):
            cmd += ["--body", args["body"]]
        return run_cli(cmd)
    return {"error": "unknown tool %s" % name}


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}

        if method == "initialize":
            send({
                "jsonrpc": "2.0",
                "id": rid,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "muse-mcp", "version": "0.1.0"},
                },
            })
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            res = call_tool(name, arguments)
            is_error = isinstance(res, dict) and "error" in res
            text = json.dumps(res, indent=2) if not isinstance(res, str) else res
            send({
                "jsonrpc": "2.0",
                "id": rid,
                "result": {
                    "content": [{"type": "text", "text": text}],
                    "isError": bool(is_error),
                },
            })
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": rid, "result": {}})
        else:
            if rid is not None:
                send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Method not found"}})


if __name__ == "__main__":
    main()
