import time

import pytest

import propresenter
from watcher import TickerWatcher


def make_env(monkeypatch, output_items, live_titles, enabled=True):
    """Builds a watcher wired to in-memory config and a recording trigger."""
    state = {
        "config": {
            "live_link": "http://example.test/feed.xml",
            "enable_spacer": True,
            "custom_items": [""],
            "output_items": output_items,
            "propresenter": {
                "enabled": enabled, "host": "127.0.0.1", "port": 1025,
                "prop_id": "AAAA-1111", "prop_name": "Ticker",
                "refresh_mode": "clear_trigger", "fade_seconds": 0.6,
            },
        },
        "saves": [],
        "triggers": [],
        "live": live_titles,
    }

    def get_config():
        return dict(state["config"])

    def save_config(cfg):
        state["config"] = dict(cfg)
        state["saves"].append(dict(cfg))

    def fetch_live_data(link):
        items = [{"id": t.split(" ")[0] + "|" + t.split(" ")[2], "title": t, "source": "live"} for t in state["live"]]
        by_id = {i["id"]: i["title"] for i in items}
        return items, by_id, None

    def get_settings(cfg):
        import gui
        return gui.get_propresenter_settings(cfg)

    def trigger_fn(host, port, prop_id, mode="trigger", fade_seconds=0.6, timeout=3.0):
        state["triggers"].append((host, port, prop_id, mode, fade_seconds))

    w = TickerWatcher(get_config, save_config, fetch_live_data, get_settings,
                      poll_seconds=0.05, debounce_seconds=0.1, trigger_fn=trigger_fn)
    return w, state


def test_check_once_persists_updated_live_scores(monkeypatch):
    stored = [{"source": "live", "id": "Newton|Roswell", "text": "Newton 0 Roswell 0"}]
    w, state = make_env(monkeypatch, stored, ["Newton 7 Roswell 0"])
    changed = w.check_once()
    # First observation primes the watcher: it persists the fresh score but
    # reports no change (and never triggers), so ProPresenter is not poked on boot.
    assert changed is False
    assert state["saves"][-1]["output_items"][0]["text"] == "Newton 7 Roswell 0"
    # A later score change on the same item is reported as a change.
    state["live"] = ["Newton 14 Roswell 0"]
    assert w.check_once() is True
    assert state["saves"][-1]["output_items"][0]["text"] == "Newton 14 Roswell 0"


def test_check_once_without_change_does_not_save(monkeypatch):
    stored = [{"source": "live", "id": "Newton|Roswell", "text": "Newton 7 Roswell 0"}]
    w, state = make_env(monkeypatch, stored, ["Newton 7 Roswell 0"])
    w.check_once()               # first run primes last_text
    saves_before = len(state["saves"])
    assert w.check_once() is False
    assert len(state["saves"]) == saves_before


def test_change_triggers_once_after_debounce(monkeypatch):
    stored = [{"source": "live", "id": "Newton|Roswell", "text": "Newton 0 Roswell 0"}]
    w, state = make_env(monkeypatch, stored, ["Newton 0 Roswell 0"])
    w.check_once()               # prime, no trigger expected on first sight
    state["live"] = ["Newton 7 Roswell 0"]
    w.check_once()
    w.notify_change()
    w.notify_change()            # burst: still one trigger
    time.sleep(0.3)
    assert state["triggers"] == [("127.0.0.1", 1025, "AAAA-1111", "clear_trigger", 0.6)]
    assert w.last_status["last_trigger_at"] is not None


def test_first_observation_does_not_trigger(monkeypatch):
    stored = [{"source": "custom", "id": "", "text": "Hello"}]
    w, state = make_env(monkeypatch, stored, [])
    w.check_once()
    time.sleep(0.3)
    assert state["triggers"] == []


def test_disabled_integration_never_triggers(monkeypatch):
    stored = [{"source": "custom", "id": "", "text": "Hello"}]
    w, state = make_env(monkeypatch, stored, [], enabled=False)
    w.check_once()
    w.notify_change()
    time.sleep(0.3)
    assert state["triggers"] == []


def test_trigger_failure_is_recorded_not_raised(monkeypatch):
    stored = [{"source": "custom", "id": "", "text": "Hello"}]
    w, state = make_env(monkeypatch, stored, [])

    def boom(*args, **kwargs):
        raise propresenter.ProPresenterError("Cannot reach ProPresenter")
    w.trigger_fn = boom

    w.check_once()
    w.notify_change()
    time.sleep(0.3)
    assert "Cannot reach" in w.last_status["last_error"]


def test_start_runs_loop_and_stop_ends_it(monkeypatch):
    stored = [{"source": "live", "id": "Newton|Roswell", "text": "Newton 0 Roswell 0"}]
    w, state = make_env(monkeypatch, stored, ["Newton 0 Roswell 0"])
    w.start()
    w.start()                    # idempotent
    time.sleep(0.15)
    state["live"] = ["Newton 14 Roswell 0"]
    time.sleep(0.4)
    w.stop()
    assert state["saves"][-1]["output_items"][0]["text"] == "Newton 14 Roswell 0"
    assert len(state["triggers"]) == 1
