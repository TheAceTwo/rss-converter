"""
paths.py - Where config.json and the activity log live.

Running from source (Docker, `python app.py`): unchanged. config.json is read
from the current directory and the log sits next to the scripts.

Packaged app (PyInstaller) or RSS_CONVERTER_DATA_DIR set: both files live in a
per-user data folder, because the app bundle is not a place to write to and a
Finder-launched app has no meaningful working directory.
  macOS default: ~/Library/Application Support/rss-converter
"""

import os
import sys

APP_NAME = "rss-converter"


def data_dir():
    """The per-user data folder, or None when running from source."""
    override = os.environ.get("RSS_CONVERTER_DATA_DIR")
    if override:
        return os.path.abspath(os.path.expanduser(override))
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            return os.path.expanduser("~/Library/Application Support/" + APP_NAME)
        return os.path.expanduser("~/." + APP_NAME)
    return None


def resolve(filename, default):
    """Path for `filename` in the data folder (created if needed), else `default`."""
    folder = data_dir()
    if folder is None:
        return default
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, filename)
