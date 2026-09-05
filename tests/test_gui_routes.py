import json


def test_index_renders_with_empty_config(logged_in_client):
    res = logged_in_client.get("/")
    assert res.status_code == 200
    assert b"RSS Control Panel" in res.data


def test_propresenter_settings_defaults_when_missing():
    import gui
    settings = gui.get_propresenter_settings({})
    assert settings == {
        "enabled": False,
        "host": "",
        "port": 1025,
        "prop_id": "",
        "prop_name": "",
        "refresh_mode": "trigger",
        "fade_seconds": 0.6,
    }


def test_propresenter_settings_merge_and_coerce_types():
    import gui
    settings = gui.get_propresenter_settings({
        "propresenter": {"enabled": "true", "host": "192.168.1.50", "port": "50001",
                         "refresh_mode": "fade_trigger", "fade_seconds": "1.5"}
    })
    assert settings["enabled"] is True
    assert settings["host"] == "192.168.1.50"
    assert settings["port"] == 50001
    assert settings["prop_id"] == ""
    assert settings["refresh_mode"] == "fade_trigger"
    assert settings["fade_seconds"] == 1.5


def test_propresenter_settings_bad_port_falls_back_to_default():
    import gui
    settings = gui.get_propresenter_settings({"propresenter": {"port": "abc"}})
    assert settings["port"] == 1025


def test_propresenter_settings_unknown_mode_and_bad_fade_fall_back():
    import gui
    settings = gui.get_propresenter_settings({"propresenter": {"refresh_mode": "explode", "fade_seconds": "-3"}})
    assert settings["refresh_mode"] == "trigger"
    assert settings["fade_seconds"] == 0.6


def test_status_returns_defaults(logged_in_client):
    res = logged_in_client.get("/api/propresenter/status")
    assert res.status_code == 200
    body = res.get_json()
    assert body["settings"]["port"] == 1025
    assert body["settings"]["enabled"] is False
    assert body["last_error"] == ""


def test_save_settings_persists_and_preserves_auth(logged_in_client, tmp_config):
    res = logged_in_client.post("/api/propresenter/settings", json={
        "host": "192.168.1.50", "port": 50001, "prop_id": "AAAA-1111",
        "prop_name": "Ticker", "enabled": True, "refresh_mode": "fade_trigger", "fade_seconds": 1.0,
    })
    assert res.status_code == 200
    on_disk = json.loads(tmp_config.read_text())
    assert on_disk["propresenter"] == {
        "enabled": True, "host": "192.168.1.50", "port": 50001,
        "prop_id": "AAAA-1111", "prop_name": "Ticker", "refresh_mode": "fade_trigger", "fade_seconds": 1.0,
    }
    assert on_disk["auth_username"] == "tester"   # save_config must not drop auth


def test_list_props_uses_query_host_and_port(logged_in_client, fake_pp):
    res = logged_in_client.get("/api/propresenter/props?host={}&port={}".format(fake_pp.host, fake_pp.port))
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert [p["name"] for p in body["props"]] == ["Ticker", "Logo Bug"]


def test_list_props_unreachable_returns_502(logged_in_client):
    res = logged_in_client.get("/api/propresenter/props?host=127.0.0.1&port=9")
    assert res.status_code == 502
    assert res.get_json()["ok"] is False


def test_manual_trigger_uses_saved_settings(logged_in_client, fake_pp):
    logged_in_client.post("/api/propresenter/settings", json={
        "host": fake_pp.host, "port": fake_pp.port, "prop_id": "AAAA-1111", "enabled": True,
    })
    res = logged_in_client.post("/api/propresenter/trigger")
    assert res.status_code == 200
    assert fake_pp.calls[-1] == "GET /v1/prop/AAAA-1111/trigger"


def test_manual_trigger_can_override_mode_for_side_by_side_testing(logged_in_client, fake_pp):
    logged_in_client.post("/api/propresenter/settings", json={
        "host": fake_pp.host, "port": fake_pp.port, "prop_id": "AAAA-1111", "enabled": True,
        "refresh_mode": "trigger",
    })
    res = logged_in_client.post("/api/propresenter/trigger", json={"refresh_mode": "clear_trigger"})
    assert res.status_code == 200
    assert fake_pp.calls[-2:] == ["GET /v1/prop/AAAA-1111/clear", "GET /v1/prop/AAAA-1111/trigger"]
    # The override is for the one test press only; saved settings are unchanged.
    saved = logged_in_client.get("/api/propresenter/status").get_json()["settings"]
    assert saved["refresh_mode"] == "trigger"


def test_manual_trigger_without_prop_returns_502(logged_in_client):
    res = logged_in_client.post("/api/propresenter/trigger")
    assert res.status_code == 502
    assert "prop" in res.get_json()["error"].lower()


def test_save_output_notifies_watcher(logged_in_client, monkeypatch):
    import gui
    calls = []
    monkeypatch.setattr(gui.ticker_watcher, "notify_change", lambda: calls.append(1))
    res = logged_in_client.post("/api/save_output", json={"items": [{"source": "custom", "id": "", "text": "Hi"}]})
    assert res.status_code == 200
    assert calls == [1]


def test_routes_require_login(tmp_config):
    import gui
    client = gui.app.test_client()
    res = client.get("/api/propresenter/status")
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]


def test_index_renders_propresenter_card(logged_in_client):
    res = logged_in_client.get("/")
    assert b"ProPresenter Auto-Refresh" in res.data
    assert b'id="pp-host"' in res.data
    assert b"ppTriggerNow" in res.data
    assert res.data.count(b'<input type="radio" name="pp-mode"') == 3
