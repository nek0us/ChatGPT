#!/bin/sh
# Remove the unit only; account sessions, storage, logs, and env files stay intact.
set -eu

UNIT_NAME=${1:-chatgptweb-core}
case "$UNIT_NAME" in
    *[!A-Za-z0-9_.@-]*|'') echo "Invalid unit name: $UNIT_NAME" >&2; exit 2 ;;
esac
if [ "$(id -u)" -ne 0 ]; then
    echo "Run this installer with sudo." >&2
    exit 1
fi

systemctl disable --now "$UNIT_NAME.service" 2>/dev/null || true
rm -f "/etc/systemd/system/$UNIT_NAME.service"
systemctl daemon-reload
echo "Removed $UNIT_NAME.service. Existing core data was left untouched."
