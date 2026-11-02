#!/bin/bash
# Stop and remove the launchd agents installed by install-launchd.sh.
UID_NUM="$(id -u)"
for name in feed gui; do
    label="com.rss-converter.$name"
    launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true
    rm -f "$HOME/Library/LaunchAgents/$label.plist"
    echo "Removed $label"
done
