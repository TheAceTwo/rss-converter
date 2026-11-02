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


def test_custom_items_save_rebuilds_output_and_notifies(logged_in_client, tmp_config, monkeypatch):
    import gui
    calls = []
    monkeypatch.setattr(gui.ticker_watcher, "notify_change", lambda: calls.append(1))
    res = logged_in_client.post("/api/custom_items", json={"items": [
        {"text": "Hi", "enabled": True},
        {"text": "Hidden", "enabled": False},
    ]})
    assert res.status_code == 200
    body = res.get_json()
    assert body["output_items"] == [{"source": "custom", "id": "", "text": "Hi"}]
    assert calls == [1]
    saved = json.loads(tmp_config.read_text())
    assert saved["custom_items"] == [{"text": "Hi", "enabled": True}, {"text": "Hidden", "enabled": False}]
    assert saved["output_items"] == [{"source": "custom", "id": "", "text": "Hi"}]
    assert saved["auth_username"] == "tester"


def test_custom_items_rejects_bad_body(logged_in_client):
    res = logged_in_client.post("/api/custom_items", json={"items": "nope"})
    assert res.status_code == 400


def test_custom_items_keep_live_items_first(logged_in_client, tmp_config):
    cfg = json.loads(tmp_config.read_text())
    cfg["output_items"] = [{"source": "live", "id": "a|b", "text": "A 1 B 0"}]
    tmp_config.write_text(json.dumps(cfg))
    res = logged_in_client.post("/api/custom_items", json={"items": [{"text": "After", "enabled": True}]})
    assert [it["text"] for it in res.get_json()["output_items"]] == ["A 1 B 0", "After"]


def test_live_toggle_off_leaves_only_custom(logged_in_client, tmp_config, monkeypatch):
    import gui
    monkeypatch.setattr(gui.ticker_watcher, "notify_change", lambda: None)
    cfg = json.loads(tmp_config.read_text())
    cfg["live_link"] = "http://example.test/feed.xml"
    cfg["custom_items"] = [{"text": "Custom", "enabled": True}]
    cfg["output_items"] = [{"source": "live", "id": "a|b", "text": "A 1 B 0"}]
    tmp_config.write_text(json.dumps(cfg))
    live = [{"id": "a|b", "title": "A 2 B 0", "source": "live"}]
    monkeypatch.setattr(gui, "fetch_live_data", lambda link: (live, {}, None))

    res = logged_in_client.post("/api/live_enabled", json={"enabled": False})
    body = res.get_json()
    assert body["live_enabled"] is False
    assert body["output_items"] == [{"source": "custom", "id": "", "text": "Custom"}]
    assert body["live_items"] == live   # still previewed in the panel while off air
    assert json.loads(tmp_config.read_text())["live_enabled"] is False


def test_live_toggle_on_puts_every_feed_item_first(logged_in_client, tmp_config, monkeypatch):
    import gui
    monkeypatch.setattr(gui.ticker_watcher, "notify_change", lambda: None)
    cfg = json.loads(tmp_config.read_text())
    cfg["live_link"] = "http://example.test/feed.xml"
    cfg["live_enabled"] = False
    cfg["custom_items"] = [{"text": "Custom", "enabled": True}]
    tmp_config.write_text(json.dumps(cfg))
    live = [{"id": "x", "title": "Game 1", "source": "live"}, {"id": "y", "title": "Game 2", "source": "live"}]
    monkeypatch.setattr(gui, "fetch_live_data", lambda link: (live, {}, None))

    body = logged_in_client.post("/api/live_enabled", json={"enabled": True}).get_json()
    assert [it["text"] for it in body["output_items"]] == ["Game 1", "Game 2", "Custom"]


def test_index_renders_toggles(logged_in_client):
    res = logged_in_client.get("/")
    assert b'id="live-enabled-toggle"' in res.data
    assert b"Custom Boxes" in res.data


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


def test_auth_falls_back_to_environment(monkeypatch):
    import gui
    monkeypatch.setenv("AUTH_USERNAME", "envuser")
    monkeypatch.setenv("AUTH_PASSWORD", "envpass")
    assert gui.get_auth_credentials({}) == ("envuser", "envpass")
    # config.json wins when it has both values
    assert gui.get_auth_credentials({"auth_username": "a", "auth_password": "b"}) == ("a", "b")


def test_auth_env_unset_means_setup_page(tmp_config, monkeypatch):
    import gui
    monkeypatch.delenv("AUTH_USERNAME", raising=False)
    monkeypatch.delenv("AUTH_PASSWORD", raising=False)
    tmp_config.write_text(json.dumps({"live_link": ""}))
    res = gui.app.test_client().get("/")
    assert res.status_code == 302
    assert "/setup" in res.headers["Location"]
