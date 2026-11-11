# muse-opencode-bridge

Expose your personal [muse.ai](https://muse.ai) agent as an OpenAI-compatible model so you can talk to it directly from [OpenCode](https://opencode.ai) (or any OpenAI client) — picked from the model list as `muse/muse-chat`.

It is a thin bridge over [muse-cli](https://github.com/nikships/muse-cli): it translates `/v1/chat/completions` into `muse-cli send` and returns your agent's reply. Your muse.ai login, sessions and memory stay in muse.ai; this bridge just makes them reachable as a model.

## Prerequisites

- `muse-cli` installed and logged in (`muse-cli status` works).
  - https://github.com/nikships/muse-cli
- Python 3.10+
- OpenCode (optional, for the model-list integration)

## Quick start

```bash
git clone https://github.com/kareem-g/muse-opencode-bridge.git
cd muse-opencode-bridge
./install.sh
```

The installer:
1. Checks `muse-cli` and Python.
2. Installs `fastapi` + `uvicorn`.
3. Installs the bridge to `~/.local/bin/muse-opencode-bridge`.
4. Patches `~/.config/opencode/opencode.jsonc` to add the `muse` provider (backup saved as `*.bak.muse-bridge`).
5. Starts a background service (systemd on Linux, launchd on macOS).

Then in OpenCode select model **muse / muse-chat**.

## Manual run

```bash
python3 -m pip install -r requirements.txt
python3 bridge.py                 # http://127.0.0.1:18765
MUSE_BRIDGE_PORT=9000 python3 bridge.py
```

## Configuration (env vars)

| Var | Default | Meaning |
| --- | --- | --- |
| `MUSE_BRIDGE_HOST` | `127.0.0.1` | Bind host |
| `MUSE_BRIDGE_PORT` | `18765` | Bind port |
| `MUSE_BRIDGE_MODEL` | `muse-chat` | Model id exposed |
| `MUSE_BRIDGE_WAIT` | `120` | Seconds to wait for muse agent reply |
| `MUSE_CLI_BIN` | `muse-cli` | Path to muse-cli binary |

## OpenCode config snippet

If you prefer manual setup, add to `~/.config/opencode/opencode.jsonc` under `provider`:

```json
"muse": {
  "name": "Muse.ai",
  "npm": "@ai-sdk/openai-compatible",
  "options": {
    "baseURL": "http://127.0.0.1:18765/v1",
    "apiKey": "sk-muse-local"
  },
  "models": {
    "muse-chat": { "name": "Muse Chat", "tool_call": true, "attachment": true }
  }
}
```

## Notes

- Each request blocks up to `MUSE_BRIDGE_WAIT` seconds while the muse agent thinks.
- Each OpenCode conversation gets its own muse.ai side chat (created on first message and reused for follow-ups), so sessions stay separate. State is stored in `~/.config/muse-opencode-bridge/sessions.json`.
- The bridge uses muse-cli. Conversation history is managed by muse.ai.
- Service logs: Linux `journalctl --user -u muse-opencode-bridge`; macOS `~/.config/muse-opencode-bridge.log`.
- To uninstall: `systemctl --user disable --now muse-opencode-bridge` (Linux) / `launchctl unload ~/Library/LaunchAgents/com.muse-opencode-bridge.plist` (macOS), then remove `~/.local/bin/muse-opencode-bridge`.

## License

MIT
EOF