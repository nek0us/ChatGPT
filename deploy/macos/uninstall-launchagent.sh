#!/bin/sh
set -eu

LABEL=${1:-com.chatgptweb.core}
DOMAIN="gui/$(id -u)"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
RUNNER="$HOME/Library/LaunchAgents/$LABEL.sh"
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
rm -f "$TARGET" "$RUNNER"
echo "Removed $LABEL. Existing core data was left untouched."
