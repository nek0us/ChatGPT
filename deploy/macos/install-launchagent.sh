#!/bin/sh
# Install a per-user launchd agent. Tested structure only; macOS runtime is not
# available in this repository's CI, so verify it on the target Mac.
set -eu

usage() {
    cat <<'EOF'
Usage: install-launchagent.sh --python PATH --env-file PATH --workdir PATH [--label LABEL]

Installs a per-user LaunchAgent. The agent starts at login and is restarted by
launchd after crashes. It never modifies session, storage, log, or env files.
EOF
}

PYTHON_EXECUTABLE=
ENV_FILE=
WORKDIR=
LABEL=com.chatgptweb.core
while [ "$#" -gt 0 ]; do
    case "$1" in
        --python) PYTHON_EXECUTABLE=${2:?missing value}; shift 2 ;;
        --env-file) ENV_FILE=${2:?missing value}; shift 2 ;;
        --workdir) WORKDIR=${2:?missing value}; shift 2 ;;
        --label) LABEL=${2:?missing value}; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done
for required in "$PYTHON_EXECUTABLE" "$ENV_FILE" "$WORKDIR"; do
    if [ -z "$required" ]; then
        usage >&2
        exit 2
    fi
done
for path in "$PYTHON_EXECUTABLE" "$ENV_FILE" "$WORKDIR"; do
    if [ ! -e "$path" ]; then
        echo "Required path does not exist: $path" >&2
        exit 1
    fi
done

escape_sed() {
    printf '%s' "$1" | sed 's/[&|\\]/\\&/g'
}
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TARGET_DIR="$HOME/Library/LaunchAgents"
TARGET="$TARGET_DIR/$LABEL.plist"
RUNNER="$TARGET_DIR/$LABEL.sh"
mkdir -p "$TARGET_DIR"

cat > "$RUNNER" <<EOF
#!/bin/sh
exec "$(printf '%s' "$PYTHON_EXECUTABLE")" -m ChatGPTWeb.core_server --env-file "$(printf '%s' "$ENV_FILE")"
EOF
chmod 700 "$RUNNER"

sed \
    -e "s|__LABEL__|$(escape_sed "$LABEL")|g" \
    -e "s|__RUNNER__|$(escape_sed "$RUNNER")|g" \
    -e "s|__WORKDIR__|$(escape_sed "$WORKDIR")|g" \
    "$SCRIPT_DIR/chatgptweb-core.plist.template" > "$TARGET"
chmod 600 "$TARGET"
plutil -lint "$TARGET"

DOMAIN="gui/$(id -u)"
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$TARGET"
launchctl kickstart -k "$DOMAIN/$LABEL"
echo "Installed $LABEL. Status: launchctl print $DOMAIN/$LABEL"
