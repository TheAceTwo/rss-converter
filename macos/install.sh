#!/bin/bash
# Installs rss-converter for the current user and starts it at every login.
# Run from the unzipped rss-converter folder:   ./install.sh
# Remove it again with:                         ./install.sh uninstall
set -euo pipefail

LABEL="com.theacetwo.rss-converter"
DEST="$HOME/Applications/rss-converter"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/rss-converter.log"
DOMAIN="gui/$(id -u)"

# Stop a previous install if one is running.
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true

if [ "${1:-}" = "uninstall" ]; then
  rm -f "$PLIST"
  rm -rf "$DEST"
  echo "Removed. Your settings and activity log are kept in ~/Library/Application Support/rss-converter"
  exit 0
fi

SRC="$(cd "$(dirname "$0")" && pwd)"
if [ ! -x "$SRC/rss-converter" ]; then
  echo "Run this script from inside the unzipped rss-converter folder." >&2
  exit 1
fi

mkdir -p "$HOME/Applications" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
if [ "$SRC" != "$DEST" ]; then
  rm -rf "$DEST"
  cp -R "$SRC" "$DEST"
fi
# Downloaded files are quarantined by Gatekeeper; this app is unsigned.
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true

cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$DEST/rss-converter</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLIST_EOF

launchctl bootstrap "$DOMAIN" "$PLIST"
echo "Installed and running."
echo "  Control panel: http://localhost:5001"
echo "  RSS feed:      http://localhost:5000/rss"
echo "  Settings:      ~/Library/Application Support/rss-converter/config.json"
echo "  App output:    $LOG"
