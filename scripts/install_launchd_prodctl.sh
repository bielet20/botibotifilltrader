#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$LAUNCH_AGENTS_DIR/com.antigravity.prodctl.deploy.plist"
LOG_DIR="$ROOT_DIR/reports"
STDOUT_LOG="$LOG_DIR/launchd_prodctl.out.log"
STDERR_LOG="$LOG_DIR/launchd_prodctl.err.log"
PRODCTL_BIN="$HOME/bin/prodctl"
PRODCTL_CORE_BIN="$HOME/bin/prodctl_core"

mkdir -p "$LAUNCH_AGENTS_DIR"
mkdir -p "$LOG_DIR"

if [[ ! -x "$PRODCTL_BIN" ]]; then
  echo "❌ No existe $PRODCTL_BIN"
  echo "Primero crea el comando con: mkdir -p ~/bin && chmod +x ~/bin/prodctl"
  exit 1
fi

cat > "$PRODCTL_CORE_BIN" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "$ROOT_DIR"
exec bash scripts/production_control.sh "\$@"
EOF
chmod +x "$PRODCTL_CORE_BIN"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.antigravity.prodctl.deploy</string>

  <key>ProgramArguments</key>
  <array>
    <string>$PRODCTL_CORE_BIN</string>
    <string>deploy</string>
    <string>--hours</string>
    <string>2</string>
    <string>--interval</string>
    <string>120</string>
    <string>--prefix</string>
    <string>paper_lab_prod_boot</string>
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

launchctl bootout "gui/$(id -u)/com.antigravity.prodctl.deploy" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl enable "gui/$(id -u)/com.antigravity.prodctl.deploy"
launchctl kickstart -k "gui/$(id -u)/com.antigravity.prodctl.deploy"

echo "✅ LaunchAgent instalado"
echo "📄 Plist: $PLIST_PATH"
echo "📝 Logs:  $STDOUT_LOG / $STDERR_LOG"
echo "🔎 Estado: launchctl print gui/$(id -u)/com.antigravity.prodctl.deploy"
