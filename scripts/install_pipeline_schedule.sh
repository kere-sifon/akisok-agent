#!/bin/zsh
set -euo pipefail

# Installs a LaunchAgent that runs the discovery pipeline once a day (08:00 local).
# Review and Approve stay manual.

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.akisok.curation-pipeline"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="$ROOT/logs"
UID_NUM="$(id -u)"

mkdir -p "$LOG_DIR" "$HOME/Library/LaunchAgents"
chmod +x "$ROOT/scripts/run_pipeline.sh"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>WorkingDirectory</key>
  <string>${ROOT}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>${ROOT}/scripts/run_pipeline.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>8</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/pipeline.stdout.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/pipeline.stderr.log</string>
  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
EOF

if launchctl print "gui/${UID_NUM}/${LABEL}" >/dev/null 2>&1; then
  launchctl bootout "gui/${UID_NUM}" "$PLIST"
fi
launchctl bootstrap "gui/${UID_NUM}" "$PLIST"

echo "Installed ${LABEL}"
echo "  08:00 local — discovery only, no auto-publish"
echo "  Logs: ${LOG_DIR}/pipeline.stdout.log"
echo "Unload: launchctl bootout gui/${UID_NUM} ${PLIST}"
echo "Run now: launchctl kickstart -k gui/${UID_NUM}/${LABEL}"
