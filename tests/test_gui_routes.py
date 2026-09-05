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
