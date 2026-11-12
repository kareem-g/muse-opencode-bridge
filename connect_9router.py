#!/usr/bin/env python3
"""Register the muse-opencode-bridge in a 9Router SQLite database (like museai)."""
import argparse
import json
import os
import sqlite3
import sys
import time

DEFAULT_DB = os.path.expanduser("~/.9router/db/data.sqlite")


def connect(db_path, port, api_key, prefix):
    if not os.path.exists(db_path):
        print("[!] 9Router database not found at %s" % db_path, file=sys.stderr)
        print("[!] Make sure 9Router is installed and has run at least once.", file=sys.stderr)
        sys.exit(1)

    base_url = "http://127.0.0.1:%d/v1" % port
    node_id = "openai-compatible-chat-%s" % prefix
    conn_id = "conn-%s-local" % prefix
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    node_data = {
        "prefix": prefix,
        "apiType": "chat",
        "baseUrl": base_url,
        "nodeName": "Muse Bridge",
        "models": [
            {"id": "muse-chat", "name": "Muse Chat (Personal Agent)"},
            {"id": "muse-image", "name": "Muse Image"},
            {"id": "muse-video", "name": "Muse Video"},
        ],
    }

    conn_data = {
        "defaultModel": "muse-chat",
        "apiKey": api_key,
        "testStatus": "active",
        "lastError": None,
        "providerSpecificData": {
            "prefix": prefix,
            "apiType": "chat",
            "baseUrl": base_url,
            "nodeName": "Muse Bridge",
        },
    }

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO providerNodes (id, type, name, data, createdAt, updatedAt) VALUES (?, ?, ?, ?, ?, ?);",
        (node_id, "openai-compatible", "Muse Bridge", json.dumps(node_data), now, now),
    )
    cur.execute(
        "INSERT OR REPLACE INTO providerConnections (id, provider, authType, name, email, priority, isActive, data, createdAt, updatedAt) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
        (conn_id, node_id, "apikey", "Muse Bridge Local", "admin@local", 1, 1, json.dumps(conn_data), now, now),
    )
    conn.commit()
    conn.close()

    print("[+] Registered Muse Bridge in 9Router.")
    print("    Node ID : %s" % node_id)
    print("    Base URL: %s" % base_url)
    print("    Prefix  : %s" % prefix)
    print("    Test    : curl -s -X POST http://127.0.0.1:20128/v1/chat/completions -H 'Content-Type: application/json' -d '{\"model\": \"%s/muse-chat\", \"messages\": [{\"role\": \"user\", \"content\": \"ping\"}]}'" % prefix)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Connect muse-opencode-bridge to 9Router")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to 9Router database")
    parser.add_argument("--port", type=int, default=18765, help="bridge port")
    parser.add_argument("--api-key", default="sk-muse-local", help="API key")
    parser.add_argument("--prefix", default="muse", help="model prefix")
    args = parser.parse_args()
    connect(args.db, args.port, args.api_key, args.prefix)
