#!/bin/bash
# Entry point used by the launchd agents. Usage: start-service.sh feed|gui
set -e
. "$(dirname "$0")/common.sh"

ensure_venv
load_env
cd "$REPO_DIR"

case "$1" in
    feed) exec "$VENV_DIR/bin/python" app.py ;;
    gui)  exec "$VENV_DIR/bin/python" gui.py ;;
    *)    echo "usage: $0 feed|gui" >&2; exit 2 ;;
esac
