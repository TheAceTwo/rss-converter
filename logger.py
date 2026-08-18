"""
logger.py - Activity logger for the RSS Control Panel.

Log format (matches logexample.txt):
  HH:MM:SS AM/PM YYYY-MM-DD [Type] message

Event types:
  [Login] - A login attempt (success or failure).
  [XML]   - The live XML feed URL was changed.
  [TXT]   - The custom (static) text boxes were changed.
  [Feed]  - The live output feed selection was changed.
"""

import os
import logging
from datetime import datetime

# ---------------------------------------------------------------------------
# File path for the activity log. Sits next to this script.
# ---------------------------------------------------------------------------
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rss_changes.log')

# ---------------------------------------------------------------------------
# Set up a plain file logger (no extra formatting - we build the line ourselves).
# ---------------------------------------------------------------------------
_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
_handler.setFormatter(logging.Formatter('%(message)s'))

_logger = logging.getLogger('rss_activity')
_logger.setLevel(logging.INFO)
_logger.addHandler(_handler)
# Prevent messages from bubbling up to the Flask root logger.
_logger.propagate = False


def _timestamp() -> str:
    """Returns a timestamp string matching the log format: 12:47:28 PM 2026-08-18"""
    now = datetime.now()
    return now.strftime('%I:%M:%S %p %Y-%m-%d')


def _fmt_list(items: list) -> str:
    """
    Formats a list as consecutive bracketed entries: [item1][item2][item3]
    If the list is empty, returns [] to make it obvious.
    """
    if not items:
        return '[]'
    return ''.join(f'[{item}]' for item in items)


# ---------------------------------------------------------------------------
# Public logging helpers - call these from gui.py routes
# ---------------------------------------------------------------------------

def log_login(username: str, ip: str, success: bool) -> None:
    """
    Logs a login attempt.
    Example: 12:15:05 PM 2026-08-18 [Login] username=admin, ip=[127.0.0.1], success=False
    """
    result = 'True' if success else 'False'
    line = f"{_timestamp()} [Login] username={username}, ip=[{ip}], success={result}"
    _logger.info(line)


def log_xml_change(old_url: str, new_url: str) -> None:
    """
    Logs a change to the live XML feed URL.
    Example: 12:47:44 PM 2026-08-18 [XML] Item 1: [old_url] > [new_url]
    """
    line = f"{_timestamp()} [XML] Item 1: [{old_url}] > [{new_url}]"
    _logger.info(line)


def log_txt_change(items: list) -> None:
    """
    Logs a change to the custom (static) text items.
    The full list at whatever length it is is written as bracketed entries.
    Example: 12:50:45 PM 2026-08-18 [TXT] user changed static output to [item1][item2]
    """
    line = f"{_timestamp()} [TXT] user changed static output to {_fmt_list(items)}"
    _logger.info(line)


# ---------------------------------------------------------------------------
# In-memory cache of the last-seen live feed items list.
# Sentinel of None means "never fetched yet" — triggers a log on first fetch.
# ---------------------------------------------------------------------------
_last_live_items = None


def log_live_items_change(items: list) -> None:
    """
    Logs the content coming in from the live XML feed URL, but ONLY when the
    list is first fetched (startup) or when its content actually changes.
    Repeated page loads that return the same items are silently ignored.

    Example: 12:47:28 PM 2026-08-18 [XML-Live] feed updated to [item1][item2][item3]
    """
    global _last_live_items
    if items == _last_live_items:
        return  # No change — skip logging
    _last_live_items = list(items)
    line = f"{_timestamp()} [XML-Live] feed updated to {_fmt_list(items)}"
    _logger.info(line)


def log_feed_change(items: list) -> None:
    """
    Logs a change to the live output feed (output_items).
    The full list at whatever length it is is written as bracketed entries.
    Example: 12:47:28 PM 2026-08-18 [Feed] user changed live output to [item1][item2]
    """
    line = f"{_timestamp()} [Feed] user changed live output to {_fmt_list(items)}"
    _logger.info(line)
