import pytest

import propresenter


def test_list_props_returns_flat_dicts(fake_pp):
    props = propresenter.list_props(fake_pp.host, fake_pp.port)
    assert props == [
        {"uuid": "AAAA-1111", "name": "Ticker", "index": 0, "is_active": True},
        {"uuid": "BBBB-2222", "name": "Logo Bug", "index": 1, "is_active": False},
    ]
    assert fake_pp.calls == ["GET /v1/props"]


def test_trigger_prop_calls_trigger_only_by_default(fake_pp):
    propresenter.trigger_prop(fake_pp.host, fake_pp.port, "AAAA-1111")
    assert fake_pp.calls == ["GET /v1/prop/AAAA-1111/trigger"]


def test_clear_trigger_mode_calls_clear_then_trigger(fake_pp):
    propresenter.trigger_prop(fake_pp.host, fake_pp.port, "AAAA-1111", mode="clear_trigger")
    assert fake_pp.calls == ["GET /v1/prop/AAAA-1111/clear", "GET /v1/prop/AAAA-1111/trigger"]


def test_fade_trigger_mode_sets_duration_keeping_transition_type_then_triggers(fake_pp):
    propresenter.trigger_prop(fake_pp.host, fake_pp.port, "AAAA-1111", mode="fade_trigger", fade_seconds=1.2)
    assert fake_pp.calls == ["GET /v1/prop/AAAA-1111", "PUT /v1/prop/AAAA-1111", "GET /v1/prop/AAAA-1111/trigger"]
    assert fake_pp.puts == [{"transition": {"uuid": "TRANS-DISSOLVE", "name": "Dissolve", "duration": 1.2}}]


def test_fade_trigger_mode_without_transition_raises_helpful_error(fake_pp):
    with pytest.raises(propresenter.ProPresenterError) as exc:
        propresenter.trigger_prop(fake_pp.host, fake_pp.port, "BBBB-2222", mode="fade_trigger")
    assert "transition" in str(exc.value).lower()
    assert not any(c.endswith("/trigger") for c in fake_pp.calls)


def test_unknown_mode_raises_before_any_network(fake_pp):
    with pytest.raises(propresenter.ProPresenterError):
        propresenter.trigger_prop(fake_pp.host, fake_pp.port, "AAAA-1111", mode="explode")
    assert fake_pp.calls == []


def test_trigger_prop_url_encodes_names_with_spaces(fake_pp):
    propresenter.trigger_prop(fake_pp.host, fake_pp.port, "Logo Bug")
    assert fake_pp.calls == ["GET /v1/prop/Logo%20Bug/trigger"]


def test_trigger_unknown_prop_raises_with_404_message(fake_pp):
    with pytest.raises(propresenter.ProPresenterError) as exc:
        propresenter.trigger_prop(fake_pp.host, fake_pp.port, "nope")
    assert "404" in str(exc.value)


def test_unreachable_host_raises_quickly():
    # Port 9 (discard) on localhost is almost certainly closed.
    with pytest.raises(propresenter.ProPresenterError):
        propresenter.list_props("127.0.0.1", 9, timeout=0.5)


def test_empty_host_raises_before_any_network():
    with pytest.raises(propresenter.ProPresenterError) as exc:
        propresenter.trigger_prop("", 1025, "AAAA-1111")
    assert "host" in str(exc.value).lower()
