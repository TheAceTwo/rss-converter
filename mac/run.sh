#!/bin/bash
# Run the feed and the control panel in this Terminal window.
# Ctrl+C stops both. For start-at-login, use mac/install-launchd.sh instead.
set -e
. "$(dirname "$0")/common.sh"

ensure_venv
load_env
cd "$REPO_DIR"

"$VENV_DIR/bin/python" app.py &
FEED_PID=$!
"$VENV_DIR/bin/python" gui.py &
GUI_PID=$!

trap 'kill $FEED_PID $GUI_PID 2>/dev/null; wait 2>/dev/null' INT TERM EXIT

echo
echo "Feed:          http://localhost:${FEED_PORT}/rss"
echo "Control panel: http://localhost:${GUI_PORT}"
echo "Press Ctrl+C to stop."
echo

wait
