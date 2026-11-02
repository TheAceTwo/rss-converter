#!/bin/bash
# Install (or reinstall) two launchd agents so the feed and the control panel
# start when you log in and restart if they crash.
# Run again after editing rss-converter.env or pulling new code to restart both.
set -e
. "$(dirname "$0")/common.sh"

case "$REPO_DIR" in
    "$HOME/Desktop"*|"$HOME/Documents"*|"$HOME/Downloads"*)
        echo "Warning: $REPO_DIR is in Desktop/Documents/Downloads." >&2
        echo "macOS privacy protection can stop launchd from reading files there." >&2
        echo "If the services do not start, move the folder (e.g. to ~/rss-converter) and run this again." >&2
        ;;
esac

ensure_venv
ensure_env_file
mkdir -p "$LOG_DIR" "$HOME/Library/LaunchAgents"
chmod +x "$REPO_DIR/mac/"*.sh

UID_NUM="$(id -u)"

install_agent() {
    local name="$1" label="com.rss-converter.$1"
    local plist="$HOME/Library/LaunchAgents/$label.plist"

    launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true

    cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$label</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$REPO_DIR/mac/start-service.sh</string>
        <string>$name</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$REPO_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/$name.out.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/$name.err.log</string>
</dict>
</plist>
PLIST

    launchctl bootstrap "gui/$UID_NUM" "$plist"
    echo "Installed and started $label"
}

install_agent feed
install_agent gui

load_env
echo
echo "Feed:          http://localhost:${FEED_PORT}/rss"
echo "Control panel: http://localhost:${GUI_PORT}"
echo "Logs:          $LOG_DIR"
