import json
from datetime import datetime, timedelta

import feed_log


def test_record_writes_one_readable_line(tmp_path):
    path = str(tmp_path / "feed_updates.log")
    feed_log.record(path, ["Newton 14 Roswell 7", "Go\nTigers!"], now=datetime(2026, 11, 2, 18, 5, 31))
    assert open(path).read() == "2026-11-02 18:05:31  Newton 14 Roswell 7 | Go Tigers!\n"


def test_empty_feed_is_recorded(tmp_path):
    path = str(tmp_path / "f.log")
    feed_log.record(path, [], now=datetime(2026, 11, 2, 18, 0, 0))
    assert "(feed empty)" in open(path).read()


def test_prune_drops_lines_older_than_retention(tmp_path, monkeypatch):
    monkeypatch.setenv("FEED_LOG_DAYS", "30")
    path = tmp_path / "f.log"
    now = datetime(2026, 11, 30, 12, 0, 0)
    old = (now - timedelta(days=31)).strftime(feed_log.TIME_FORMAT)
    recent = (now - timedelta(days=29)).strftime(feed_log.TIME_FORMAT)
    path.write_text(f"{old}  old item\n{recent}  recent item\n")
    assert feed_log.prune(str(path), now) == 1
    assert path.read_text() == f"{recent}  recent item\n"


def test_log_path_defaults_next_to_config(tmp_path, monkeypatch):
    monkeypatch.delenv("FEED_LOG_FILE", raising=False)
    assert feed_log.log_path(str(tmp_path / "config.json")) == str(tmp_path / "feed_updates.log")


def test_save_config_logs_only_when_feed_content_changes(tmp_config, monkeypatch):
    import gui
    monkeypatch.delenv("FEED_LOG_FILE", raising=False)
    log = tmp_config.parent / "feed_updates.log"
    cfg = json.loads(tmp_config.read_text())

    cfg["output_items"] = [{"source": "custom", "id": "", "text": "Hello"}]
    gui.save_config(cfg)
    gui.save_config(cfg)                         # same content: no new line
    cfg["enable_spacer"] = False
    gui.save_config(cfg)                         # other setting: no new line
    cfg["output_items"] = [{"source": "live", "id": "a", "text": "A 1 B 0"},
                           {"source": "custom", "id": "", "text": "Hello"}]
    gui.save_config(cfg)

    lines = log.read_text().splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("  Hello")
    assert lines[1].endswith("  A 1 B 0 | Hello")


def test_feed_log_page_shows_newest_first(logged_in_client, tmp_config):
    log = tmp_config.parent / "feed_updates.log"
    log.write_text("2026-11-01 10:00:00  first\n2026-11-02 10:00:00  second\n")
    res = logged_in_client.get("/feed-log")
    assert res.status_code == 200
    assert res.mimetype == "text/plain"
    body = res.get_data(as_text=True)
    assert body.index("  second") < body.index("  first")


def test_feed_log_page_requires_login(tmp_config):
    import gui
    res = gui.app.test_client().get("/feed-log")
    assert res.status_code == 302
