#!/bin/sh
# Install a per-project ChatGPTWeb core systemd service. Run with sudo.
set -eu

usage() {
    cat <<'EOF'
Usage: sudo install-systemd.sh --python PATH --env-file PATH --workdir PATH --user USER [options]

Required:
  --python PATH       Python interpreter that has ChatGPTWeb installed.
  --env-file PATH     Portable KEY=value core configuration file.
  --workdir PATH      Project working directory.
  --user USER         Linux account that owns the sessions and browser profile.

Options:
  --group GROUP       Service group. Defaults to the user's primary group.
  --unit-name NAME    systemd unit name without '.service'. Default: chatgptweb-core.
  --start             Enable and start the service after installation.

The installer writes only /etc/systemd/system/<unit>.service. It never copies,
changes, or deletes your session JSON, storage directory, or environment file.
EOF
}

PYTHON_EXECUTABLE=
ENV_FILE=
WORKDIR=
SERVICE_USER=
SERVICE_GROUP=
UNIT_NAME=chatgptweb-core
START_SERVICE=false

while [ "$#" -gt 0 ]; do
    case "$1" in
        --python) PYTHON_EXECUTABLE=${2:?missing value}; shift 2 ;;
        --env-file) ENV_FILE=${2:?missing value}; shift 2 ;;
        --workdir) WORKDIR=${2:?missing value}; shift 2 ;;
        --user) SERVICE_USER=${2:?missing value}; shift 2 ;;
        --group) SERVICE_GROUP=${2:?missing value}; shift 2 ;;
        --unit-name) UNIT_NAME=${2:?missing value}; shift 2 ;;
        --start) START_SERVICE=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

for required in "$PYTHON_EXECUTABLE" "$ENV_FILE" "$WORKDIR" "$SERVICE_USER"; do
    if [ -z "$required" ]; then
        echo "Missing a required option." >&2
        usage >&2
        exit 2
    fi
done

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this installer with sudo." >&2
    exit 1
fi
if [ ! -x "$PYTHON_EXECUTABLE" ]; then
    echo "Python executable not found: $PYTHON_EXECUTABLE" >&2
    exit 1
fi
if [ ! -f "$ENV_FILE" ]; then
    echo "Environment file not found: $ENV_FILE" >&2
    exit 1
fi
if [ ! -d "$WORKDIR" ]; then
    echo "Working directory not found: $WORKDIR" >&2
    exit 1
fi
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    echo "Service user not found: $SERVICE_USER" >&2
    exit 1
fi
if [ -z "$SERVICE_GROUP" ]; then
    SERVICE_GROUP=$(id -gn "$SERVICE_USER")
fi

case "$UNIT_NAME" in
    *[!A-Za-z0-9_.@-]*|'') echo "Invalid unit name: $UNIT_NAME" >&2; exit 2 ;;
esac

escape_sed() {
    printf '%s' "$1" | sed 's/[&|\\]/\\&/g'
}

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TEMPLATE="$SCRIPT_DIR/chatgptweb-core.service.template"
TARGET="/etc/systemd/system/$UNIT_NAME.service"
if [ ! -f "$TEMPLATE" ]; then
    echo "Service template not found: $TEMPLATE" >&2
    exit 1
fi

sed \
    -e "s|__PYTHON__|$(escape_sed "$PYTHON_EXECUTABLE")|g" \
    -e "s|__ENV_FILE__|$(escape_sed "$ENV_FILE")|g" \
    -e "s|__WORKDIR__|$(escape_sed "$WORKDIR")|g" \
    -e "s|__USER__|$(escape_sed "$SERVICE_USER")|g" \
    -e "s|__GROUP__|$(escape_sed "$SERVICE_GROUP")|g" \
    "$TEMPLATE" > "$TARGET"

chmod 0644 "$TARGET"
systemctl daemon-reload
echo "Installed $UNIT_NAME.service."
echo "Status: systemctl status $UNIT_NAME"
echo "Logs:   journalctl -u $UNIT_NAME -f"
if [ "$START_SERVICE" = true ]; then
    systemctl enable --now "$UNIT_NAME.service"
fi
