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


import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class _FakeProPresenter:
    def __init__(self):
        self.calls = []
        self.puts = []
        self.props = [
            {"id": {"uuid": "AAAA-1111", "name": "Ticker", "index": 0}, "is_active": True,
             "auto_clear_enabled": False, "auto_clear_duration": 0,
             "transition": {"uuid": "TRANS-DISSOLVE", "name": "Dissolve", "duration": 0.0}},
            {"id": {"uuid": "BBBB-2222", "name": "Logo Bug", "index": 1}, "is_active": False,
             "auto_clear_enabled": False, "auto_clear_duration": 0},
        ]
        self.fail_next = None
        self.host = "127.0.0.1"
        self.port = None
        self._server = None

    def _find(self, key):
        from urllib.parse import unquote
        key = unquote(key)
        for p in self.props:
            if key in (p["id"]["uuid"], p["id"]["name"]):
                return p
        return None

    def start(self):
        state = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence test output
                pass

            def _maybe_fail(self):
                if state.fail_next is not None:
                    code, state.fail_next = state.fail_next, None
                    self.send_response(code)
                    self.end_headers()
                    return True
                return False

            def _json(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                state.calls.append("GET " + self.path)
                if self._maybe_fail():
                    return
                if self.path == "/v1/props":
                    self._json(200, state.props)
                    return
                parts = self.path.strip("/").split("/")
                # /v1/prop/{id}
                if len(parts) == 3 and parts[0] == "v1" and parts[1] == "prop":
                    prop = state._find(parts[2])
                    if prop is None:
                        self.send_response(404); self.end_headers(); return
                    self._json(200, prop)
                    return
                # /v1/prop/{id}/trigger  or  /v1/prop/{id}/clear
                if len(parts) == 4 and parts[0] == "v1" and parts[1] == "prop" and parts[3] in ("trigger", "clear"):
                    self.send_response(204 if state._find(parts[2]) else 404)
                    self.end_headers()
                    return
                self.send_response(404)
                self.end_headers()

            def do_PUT(self):
                state.calls.append("PUT " + self.path)
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                if self._maybe_fail():
                    return
                parts = self.path.strip("/").split("/")
                if len(parts) == 3 and parts[0] == "v1" and parts[1] == "prop":
                    prop = state._find(parts[2])
                    if prop is None:
                        self.send_response(404); self.end_headers(); return
                    body = json.loads(raw.decode() or "{}")
                    state.puts.append(body)
                    if "transition" in body:
                        prop["transition"] = body["transition"]
                    self._json(200, prop)
                    return
                self.send_response(404)
                self.end_headers()

        self._server = HTTPServer((self.host, 0), Handler)
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()


@pytest.fixture
def fake_pp():
    server = _FakeProPresenter()
    server.start()
    yield server
    server.stop()
