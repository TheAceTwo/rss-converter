"""
feed_log.py - A plain-text history of what the public RSS feed (/rss) served.

One line per change to the ticker content, newest at the bottom:

    2026-11-02 18:05:31  Newton 14 Roswell 7 2ND QTR | Go Tigers!

Lines older than FEED_LOG_DAYS (default 30) are deleted automatically, so the
file holds roughly the last month.

The file lives next to config.json (so in Docker it is in the data volume),
or wherever FEED_LOG_FILE points.
"""

import os
import threading
import time
from datetime import datetime, timedelta

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
_TIME_LEN = len("2026-01-01 00:00:00")
PRUNE_INTERVAL_SECONDS = 3600

_lock = threading.Lock()
_last_prune = 0.0


def retention_days():
    try:
        days = int(os.environ.get("FEED_LOG_DAYS", "30"))
    except ValueError:
        days = 30
    return max(days, 1)


def log_path(config_file):
    """Where the log lives: FEED_LOG_FILE, else feed_updates.log next to config.json."""
    explicit = os.environ.get("FEED_LOG_FILE", "").strip()
    if explicit:
        return explicit
    return os.path.join(os.path.dirname(os.path.abspath(config_file)), "feed_updates.log")


def format_line(texts, now):
    texts = [str(t).strip() for t in texts if str(t).strip()]
    body = " | ".join(texts) if texts else "(feed empty)"
    # Keep each update on one line however the source text is formatted.
    body = " ".join(body.split())
    return "{}  {}\n".format(now.strftime(TIME_FORMAT), body)


def prune(path, now=None):
    """Deletes lines older than the retention window. Returns how many were removed."""
    now = now or datetime.now()
    cutoff = now - timedelta(days=retention_days())
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return 0

    kept = []
    for line in lines:
        try:
            stamp = datetime.strptime(line[:_TIME_LEN], TIME_FORMAT)
        except ValueError:
            kept.append(line)   # not ours or malformed: leave it alone
            continue
        if stamp >= cutoff:
            kept.append(line)

    removed = len(lines) - len(kept)
    if removed:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(kept)
        os.replace(tmp, path)
    return removed


def record(path, texts, now=None):
    """Appends one update line, pruning old lines at most once an hour."""
    global _last_prune
    now = now or datetime.now()
    with _lock:
        try:
            if time.monotonic() - _last_prune > PRUNE_INTERVAL_SECONDS:
                prune(path, now)
                _last_prune = time.monotonic()
            with open(path, "a", encoding="utf-8") as f:
                f.write(format_line(texts, now))
        except OSError:
            pass    # logging must never break the feed


def read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""
