from output_resolver import resolve_output_items, ticker_text


LIVE = [
    {"id": "Newton|Roswell", "title": "Newton 14 Roswell 0 2ND QTR", "source": "live"},
    {"id": "Milton|Blessed Trinity", "title": "Milton 7 Blessed Trinity 3 1ST QTR", "source": "live"},
]
BY_ID = {it["id"]: it["title"] for it in LIVE}


def test_live_dict_item_takes_current_live_text():
    stored = [{"source": "live", "id": "Newton|Roswell", "text": "Newton 7 Roswell 0 1ST QTR"}]
    out = resolve_output_items(stored, LIVE, BY_ID)
    assert out == [{"source": "live", "id": "Newton|Roswell", "text": "Newton 14 Roswell 0 2ND QTR"}]


def test_live_dict_item_missing_from_feed_keeps_stored_text():
    stored = [{"source": "live", "id": "Gone|Team", "text": "Gone 0 Team 0"}]
    out = resolve_output_items(stored, LIVE, BY_ID)
    assert out[0]["text"] == "Gone 0 Team 0"
    assert out[0]["source"] == "live"


def test_custom_dict_item_is_unchanged():
    stored = [{"source": "custom", "id": "", "text": "Welcome to Friday Night"}]
    out = resolve_output_items(stored, LIVE, BY_ID)
    assert out == stored


def test_legacy_string_matching_both_team_names_becomes_live():
    out = resolve_output_items(["Newton vs Roswell tonight"], LIVE, BY_ID)
    assert out == [{"source": "live", "id": "Newton|Roswell", "text": "Newton 14 Roswell 0 2ND QTR"}]


def test_legacy_string_with_no_match_becomes_custom():
    out = resolve_output_items(["  Halftime show at 8  "], LIVE, BY_ID)
    assert out == [{"source": "custom", "id": "", "text": "Halftime show at 8"}]


def test_ticker_text_joins_non_blank_items():
    items = [
        {"source": "custom", "id": "", "text": "A"},
        {"source": "custom", "id": "", "text": "   "},
        {"source": "custom", "id": "", "text": "B"},
    ]
    assert ticker_text(items) == "A  |  B"


def test_ticker_text_empty_list():
    assert ticker_text([]) == ""
