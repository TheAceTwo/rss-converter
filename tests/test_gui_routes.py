import json


def test_index_renders_with_empty_config(logged_in_client):
    res = logged_in_client.get("/")
    assert res.status_code == 200
    assert b"RSS Control Panel" in res.data
