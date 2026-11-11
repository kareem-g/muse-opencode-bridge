#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRIDGE_SRC="$REPO_DIR/bridge.py"
INSTALL_BIN="${HOME}/.local/bin/muse-opencode-bridge"
PORT="${MUSE_BRIDGE_PORT:-18765}"

echo "==> muse-opencode-bridge installer"

# 1. Prerequisites
if ! command -v muse-cli >/dev/null 2>&1; then
  echo "ERROR: muse-cli is not installed or not on PATH."
  echo "Install it first: https://github.com/nikships/muse-cli"
  echo "  curl -fsSL https://raw.githubusercontent.com/nikships/muse-cli/main/install.sh | bash"
  exit 1
fi

if ! muse-cli status >/dev/null 2>&1; then
  echo "WARNING: muse-cli status failed. Make sure you are logged in (muse-cli auth export)."
fi

PYTHON=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then PYTHON="$(command -v $c)"; break; fi
done
if [ -z "$PYTHON" ]; then
  echo "ERROR: python3 not found."; exit 1
fi
echo "Using Python: $PYTHON"

# 2. Install Python deps
echo "==> Installing Python dependencies (fastapi, uvicorn)"
"$PYTHON" -m pip install --quiet --user -r "$REPO_DIR/requirements.txt" 2>&1 | tail -5 || \
  "$PYTHON" -m pip install --quiet -r "$REPO_DIR/requirements.txt"

# 3. Install bridge binary
mkdir -p "$(dirname "$INSTALL_BIN")"
cp "$BRIDGE_SRC" "$INSTALL_BIN"
chmod +x "$INSTALL_BIN"
echo "Installed bridge to $INSTALL_BIN"

# 4. Auto-patch OpenCode config (if present)
OC_CONFIG="${HOME}/.config/opencode/opencode.jsonc"
if [ -f "$OC_CONFIG" ]; then
  echo "==> Patching OpenCode config: $OC_CONFIG"
  cp "$OC_CONFIG" "${OC_CONFIG}.bak.muse-bridge"
  "$PYTHON" - "$OC_CONFIG" "$PORT" <<'PY'
import json, sys
path, port = sys.argv[1], sys.argv[2]
with open(path) as f:
    cfg = json.load(f)
cfg.setdefault("provider", {})
if "muse" not in cfg["provider"]:
    cfg["provider"]["muse"] = {
        "name": "Muse.ai",
        "npm": "@ai-sdk/openai-compatible",
        "options": {
            "baseURL": "http://127.0.0.1:%s/v1" % port,
            "apiKey": "sk-muse-local",
        },
        "models": {"muse-chat": {"name": "Muse Chat"}},
    }
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
    print("  added muse provider")
else:
    print("  muse provider already present (left as-is)")
PY
else
  echo "OpenCode config not found at $OC_CONFIG"
  echo "Add this provider manually:"
  cat <<EOF

  "muse": {
    "name": "Muse.ai",
    "npm": "@ai-sdk/openai-compatible",
    "options": { "baseURL": "http://127.0.0.1:${PORT}/v1", "apiKey": "sk-muse-local" },
    "models": { "muse-chat": { "name": "Muse Chat" } }
  }
EOF
fi

# 5. Service setup
OS="$(uname -s)"
if [ "$OS" = "Linux" ]; then
  SERVICE_DIR="${HOME}/.config/systemd/user"
  SERVICE_FILE="$SERVICE_DIR/muse-opencode-bridge.service"
  mkdir -p "$SERVICE_DIR"
  PYTHON_PATH="$(command -v "$PYTHON")"
  cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Muse.ai OpenAI-compatible bridge for OpenCode
After=network.target

[Service]
Type=simple
ExecStart=$PYTHON_PATH $INSTALL_BIN
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1
Environment=PATH=${HOME}/.local/bin:${HOME}/miniconda3/bin:/usr/local/bin:/usr/bin:/bin
Environment=MUSE_BRIDGE_PORT=$PORT

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload 2>/dev/null || true
  systemctl --user enable --now muse-opencode-bridge 2>/dev/null || true
  echo "Started systemd user service: muse-opencode-bridge"
elif [ "$OS" = "Darwin" ]; then
  PLIST="${HOME}/Library/LaunchAgents/com.muse-opencode-bridge.plist"
  mkdir -p "$(dirname "$PLIST")"
  PYTHON_PATH="$(command -v "$PYTHON")"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.muse-opencode-bridge</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_PATH</string>
    <string>$INSTALL_BIN</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>MUSE_BRIDGE_PORT</key><string>$PORT</string>
    <key>PATH</key><string>${HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${HOME}/.config/muse-opencode-bridge.log</string>
  <key>StandardErrorPath</key><string>${HOME}/.config/muse-opencode-bridge.log</string>
</dict>
</plist>
EOF
  launchctl load "$PLIST" 2>/dev/null || true
  echo "Loaded launchd agent: com.muse-opencode-bridge"
else
  echo "Unsupported OS for auto-service. Run manually: $INSTALL_BIN"
fi

sleep 1
if curl -s "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1; then
  echo ""
  echo "==> Bridge is running on http://127.0.0.1:${PORT}"
  echo "    Model id: muse-chat  (use as muse/muse-chat in OpenCode)"
else
  echo ""
  echo "WARNING: bridge did not respond. Check logs or run: $INSTALL_BIN"
fi
EOF
chmod +x /home/kareem/muse-opencode-bridge/install.sh