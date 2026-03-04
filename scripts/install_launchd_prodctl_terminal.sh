#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$LAUNCH_AGENTS_DIR/com.antigravity.prodctl.terminal.plist"
LOG_DIR="$ROOT_DIR/reports"
STDOUT_LOG="$LOG_DIR/launchd_prodctl_terminal.out.log"
STDERR_LOG="$LOG_DIR/launchd_prodctl_terminal.err.log"

mkdir -p "$LAUNCH_AGENTS_DIR"
mkdir -p "$LOG_DIR"

COMMAND="cd '$ROOT_DIR' && ~/bin/prodctl deploy --hours 2 --interval 120 --prefix paper_lab_prod_boot"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.antigravity.prodctl.terminal</string>

  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/osascript</string>
    <string>-e</string>
    <string>tell application "Terminal" to do script "$COMMAND"</string>
  </array>

  <key>RunAtLoad</key>
  <true/>

  <key>StandardOutPath</key>
  <string>$STDOUT_LOG</string>

  <key>StandardErrorPath</key>
  <string>$STDERR_LOG</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/com.antigravity.prodctl.terminal" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl enable "gui/$(id -u)/com.antigravity.prodctl.terminal"
launchctl kickstart -k "gui/$(id -u)/com.antigravity.prodctl.terminal"

echo "✅ LaunchAgent Terminal instalado"
echo "📄 Plist: $PLIST_PATH"
echo "🔎 Estado: launchctl print gui/$(id -u)/com.antigravity.prodctl.terminal"
