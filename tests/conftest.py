import json
import os
import sys

import pytest

# Make the repo root importable when pytest runs from anywhere.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    """A throwaway config.json that both gui and app read/write."""
    cfg_path = tmp_path / "config.json"
    cfg = {
        "live_link": "",
        "enable_spacer": True,
        "auth_username": "tester",
        "auth_password": "secret",
        "custom_items": [""],
        "output_items": [],
    }
    cfg_path.write_text(json.dumps(cfg))

    import gui
    import app as feed_app
    monkeypatch.setattr(gui, "CONFIG_FILE", str(cfg_path))
    monkeypatch.setattr(feed_app, "CONFIG_FILE", str(cfg_path))
    return cfg_path


@pytest.fixture
def logged_in_client(tmp_config):
    import gui
    gui.app.config["TESTING"] = True
    client = gui.app.test_client()
    with client.session_transaction() as sess:
        sess["logged_in"] = True
    return client
