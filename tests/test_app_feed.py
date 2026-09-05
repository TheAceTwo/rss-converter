import json
import xml.etree.ElementTree as ET


def _write(tmp_config, items):
    cfg = json.loads(tmp_config.read_text())
    cfg["output_items"] = items
    tmp_config.write_text(json.dumps(cfg))


def _client():
    import app as feed_app
    feed_app.app.config["TESTING"] = True
    return feed_app.app.test_client()


def test_guid_changes_when_text_changes(tmp_config):
    _write(tmp_config, [{"source": "custom", "id": "", "text": "Newton 7 Roswell 0"}])
    first = ET.fromstring(_client().get("/rss").data).find(".//item/guid").text
    _write(tmp_config, [{"source": "custom", "id": "", "text": "Newton 14 Roswell 0"}])
    second = ET.fromstring(_client().get("/rss").data).find(".//item/guid").text
    assert first != second
    assert first.startswith("item-") and len(first) == len("item-") + 12


def test_guid_is_stable_for_same_text(tmp_config):
    _write(tmp_config, [{"source": "custom", "id": "", "text": "Same"}])
    a = ET.fromstring(_client().get("/rss").data).find(".//item/guid").text
    b = ET.fromstring(_client().get("/rss").data).find(".//item/guid").text
    assert a == b


def test_no_cache_headers_and_last_build_date(tmp_config):
    _write(tmp_config, [{"source": "custom", "id": "", "text": "X"}])
    res = _client().get("/rss")
    assert res.headers["Cache-Control"] == "no-cache, no-store, must-revalidate"
    root = ET.fromstring(res.data)
    assert root.find("./channel/lastBuildDate") is not None
    assert root.find("./channel/lastBuildDate").text.endswith("GMT")


def test_description_is_valid_html_after_xml_parse(tmp_config):
    _write(tmp_config, [{"source": "custom", "id": "", "text": "Score & more"}])
    root = ET.fromstring(_client().get("/rss").data)
    desc = root.find(".//item/description").text
    assert desc == "<h3>Score &amp; more</h3><p>Active Output Feed Item</p>"
    assert "CDATA" not in desc


def test_blank_items_skipped_and_spacer_present(tmp_config):
    _write(tmp_config, [{"source": "custom", "id": "", "text": "  "}, {"source": "custom", "id": "", "text": "A"}])
    root = ET.fromstring(_client().get("/rss").data)
    titles = [i.find("title").text for i in root.findall(".//item")]
    assert titles == ["A", " "]
