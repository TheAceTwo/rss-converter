from output_resolver import (
    build_output_items,
    normalize_custom_items,
    ticker_settings,
    ticker_text,
)


LIVE = [
    {"id": "Newton|Roswell", "title": "Newton 14 Roswell 0 2ND QTR", "source": "live"},
    {"id": "Milton|Blessed Trinity", "title": "Milton 7 Blessed Trinity 3 1ST QTR", "source": "live"},
]


def test_all_live_items_come_first_then_enabled_custom_boxes():
    custom = [
        {"text": "Go Tigers!", "enabled": True},
        {"text": "Hidden", "enabled": False},
        {"text": "Concessions open", "enabled": True},
    ]
    out = build_output_items(True, LIVE, custom)
    assert [it["text"] for it in out] == [
        "Newton 14 Roswell 0 2ND QTR",
        "Milton 7 Blessed Trinity 3 1ST QTR",
        "Go Tigers!",
        "Concessions open",
    ]
    assert [it["source"] for it in out] == ["live", "live", "custom", "custom"]
    assert out[0]["id"] == "Newton|Roswell"


def test_live_off_shows_only_custom_boxes():
    out = build_output_items(False, LIVE, [{"text": "Only me", "enabled": True}])
    assert out == [{"source": "custom", "id": "", "text": "Only me"}]


def test_blank_custom_boxes_are_skipped():
    out = build_output_items(False, [], [{"text": "   ", "enabled": True}])
    assert out == []


def test_failed_fetch_keeps_previous_live_items():
    previous = [
        {"source": "live", "id": "Newton|Roswell", "text": "Newton 7 Roswell 0"},
        {"source": "custom", "id": "", "text": "Old custom"},
    ]
    out = build_output_items(True, [], [{"text": "New custom", "enabled": True}], previous, live_ok=False)
    assert out == [
        {"source": "live", "id": "Newton|Roswell", "text": "Newton 7 Roswell 0"},
        {"source": "custom", "id": "", "text": "New custom"},
    ]


def test_normalize_keeps_new_format():
    raw = [{"text": "A", "enabled": False}, {"text": "B"}]
    assert normalize_custom_items(raw) == [
        {"text": "A", "enabled": False},
        {"text": "B", "enabled": True},
    ]


def test_normalize_legacy_strings_enables_only_what_was_on_air():
    legacy_custom = ["On air", "Preset only", ""]
    legacy_output = [
        {"source": "live", "id": "Newton|Roswell", "text": "Newton 7 Roswell 0"},
        {"source": "custom", "id": "", "text": "On air"},
        {"source": "custom", "id": "", "text": "Typed straight into output"},
    ]
    assert normalize_custom_items(legacy_custom, legacy_output) == [
        {"text": "On air", "enabled": True},
        {"text": "Preset only", "enabled": False},
        {"text": "Typed straight into output", "enabled": True},
    ]


def test_ticker_settings_defaults_live_on():
    live_enabled, custom = ticker_settings({"custom_items": [""]})
    assert live_enabled is True
    assert custom == []


def test_ticker_settings_reads_live_off():
    live_enabled, _ = ticker_settings({"live_enabled": False})
    assert live_enabled is False


def test_ticker_text_joins_non_blank_items():
    items = [
        {"source": "live", "id": "a", "text": "One"},
        {"source": "custom", "id": "", "text": "  "},
        {"source": "custom", "id": "", "text": "Two"},
    ]
    assert ticker_text(items) == "One  |  Two"


def test_ticker_text_empty_list():
    assert ticker_text([]) == ""
