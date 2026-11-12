#!/bin/zsh
set -euo pipefail

# Stops the Mac LaunchAgent so discovery only runs as the cluster CronJob.
LABEL="com.akisok.curation-pipeline"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
UID_NUM="$(id -u)"

if launchctl print "gui/${UID_NUM}/${LABEL}" >/dev/null 2>&1; then
  launchctl bootout "gui/${UID_NUM}" "$PLIST"
  echo "Unloaded ${LABEL}"
else
  echo "${LABEL} is not loaded"
fi
