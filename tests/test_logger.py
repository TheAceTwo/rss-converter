def test_log_propresenter_writes_pp_tagged_line(tmp_path, monkeypatch):
    import logging
    import logger as activity_log

    log_file = tmp_path / "rss_changes.log"
    handler = logging.FileHandler(str(log_file), encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    monkeypatch.setattr(activity_log._logger, "handlers", [handler])

    activity_log.log_propresenter("triggered prop Ticker (uuid AAAA-1111)")
    handler.flush()

    line = log_file.read_text().strip()
    assert "[PP] triggered prop Ticker (uuid AAAA-1111)" in line
