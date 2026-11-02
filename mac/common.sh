#!/bin/bash
# Shared helpers for the Mac scripts. Sourced, not run directly.
# Written for the bash 3.2 that ships with macOS.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$REPO_DIR/.venv"
ENV_FILE="$REPO_DIR/rss-converter.env"
LOG_DIR="$REPO_DIR/logs"

# Create rss-converter.env with defaults and a random SECRET_KEY the first time.
ensure_env_file() {
    if [ ! -f "$ENV_FILE" ]; then
        echo "Creating $ENV_FILE with default settings"
        cat > "$ENV_FILE" <<ENVEOF
# rss-converter settings for this Mac. Not committed to git.
# Restart the services after editing (mac/install-launchd.sh again, or re-run mac/run.sh).

# Feed for ProPresenter: http://<this-mac>:FEED_PORT/rss
# (5000 is taken by AirPlay Receiver on macOS, so the default is 5050.)
FEED_PORT=5050

# Control panel: http://<this-mac>:GUI_PORT
GUI_PORT=5001

# 0.0.0.0 = reachable from other machines on the network.
# 127.0.0.1 = this Mac only (fine if ProPresenter runs on this Mac).
FEED_HOST=0.0.0.0
GUI_HOST=0.0.0.0

# Signs control panel login cookies. Keep it secret.
SECRET_KEY=$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 48)

# Optional: default live XML source if none is set in the control panel.
XML_URL=
ENVEOF
    fi
}

load_env() {
    ensure_env_file
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
}

# Create the virtualenv and install requirements if needed.
ensure_venv() {
    if ! command -v python3 >/dev/null 2>&1; then
        echo "python3 not found. Install Python 3 from https://www.python.org/downloads/macos/ or with 'brew install python'." >&2
        exit 1
    fi
    if [ ! -x "$VENV_DIR/bin/python" ]; then
        echo "Creating virtualenv in $VENV_DIR"
        python3 -m venv "$VENV_DIR"
    fi
    if [ ! -f "$VENV_DIR/.requirements-installed" ] || [ "$REPO_DIR/requirements.txt" -nt "$VENV_DIR/.requirements-installed" ]; then
        echo "Installing requirements"
        "$VENV_DIR/bin/pip" install --quiet --upgrade pip
        "$VENV_DIR/bin/pip" install --quiet -r "$REPO_DIR/requirements.txt"
        touch "$VENV_DIR/.requirements-installed"
    fi
}
