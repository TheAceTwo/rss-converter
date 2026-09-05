"""
propresenter.py - Minimal client for the ProPresenter HTTP API.

Endpoints used (see https://openapi.propresenter.com/):
  GET /v1/props                 -> JSON list of props
  GET /v1/prop/{id}             -> JSON details of one prop (includes "transition")
  PUT /v1/prop/{id}             -> update prop details (we only ever send "transition")
  GET /v1/prop/{id}/trigger     -> 204 on success, 404 if the prop is unknown
  GET /v1/prop/{id}/clear       -> 204 on success

{id} may be the prop's uuid, its name, or its index. Enable the API in
ProPresenter under Settings > Network. There is no authentication.

Refresh modes (trigger_prop):
  "trigger"        fire the prop; ProPresenter reloads the RSS in place.
  "clear_trigger"  clear, pause 0.3 s, fire. Same as a manual clear + click.
  "fade_trigger"   set the prop's existing transition to fade_seconds, then fire.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

REFRESH_MODES = ("trigger", "clear_trigger", "fade_trigger")


class ProPresenterError(Exception):
    """Raised for any failure talking to ProPresenter. Message is user-facing."""


def _base_url(host, port):
    host = (host or "").strip()
    if not host:
        raise ProPresenterError("ProPresenter host is not set.")
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise ProPresenterError("ProPresenter port must be a number.")
    return "http://{}:{}".format(host, port)


def _get(url, timeout):
    """GET url. Returns (status_code, body_bytes). Raises ProPresenterError."""
    return _request("GET", url, None, timeout)


def _request(method, url, json_body, timeout):
    data = None
    headers = {"Accept": "application/json"}
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        raise ProPresenterError("ProPresenter returned HTTP {} for {}".format(e.code, url))
    except urllib.error.URLError as e:
        raise ProPresenterError("Cannot reach ProPresenter at {}: {}".format(url, e.reason))
    except (OSError, ValueError) as e:  # timeouts, bad hosts
        raise ProPresenterError("Cannot reach ProPresenter at {}: {}".format(url, e))


def list_props(host, port, timeout=3.0):
    """Returns [{uuid, name, index, is_active}] for every prop ProPresenter knows."""
    status, body = _get(_base_url(host, port) + "/v1/props", timeout)
    try:
        raw = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ProPresenterError("ProPresenter /v1/props did not return JSON.")
    props = []
    for entry in raw if isinstance(raw, list) else []:
        ident = entry.get("id", {}) if isinstance(entry, dict) else {}
        props.append({
            "uuid": str(ident.get("uuid", "")),
            "name": str(ident.get("name", "")),
            "index": ident.get("index"),
            "is_active": bool(entry.get("is_active", False)),
        })
    return props


def clear_prop(host, port, prop_id, timeout=3.0):
    if not str(prop_id).strip():
        raise ProPresenterError("No prop selected.")
    url = "{}/v1/prop/{}/clear".format(_base_url(host, port), urllib.parse.quote(str(prop_id), safe=""))
    _get(url, timeout)


def get_prop(host, port, prop_id, timeout=3.0):
    """Returns the raw JSON dict for one prop (GET /v1/prop/{id})."""
    if not str(prop_id).strip():
        raise ProPresenterError("No prop selected.")
    url = "{}/v1/prop/{}".format(_base_url(host, port), urllib.parse.quote(str(prop_id), safe=""))
    status, body = _get(url, timeout)
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ProPresenterError("ProPresenter /v1/prop/{} did not return JSON.".format(prop_id))


def set_prop_transition_duration(host, port, prop_id, seconds, timeout=3.0):
    """
    Keeps the prop's current transition type and sets only its duration.
    Raises if the prop has no transition configured, because we never guess a
    transition uuid: the user sets any transition once in ProPresenter.
    """
    prop = get_prop(host, port, prop_id, timeout)
    transition = prop.get("transition") if isinstance(prop, dict) else None
    if not transition or not transition.get("uuid"):
        raise ProPresenterError(
            "Prop has no transition set. In ProPresenter, give the prop any transition "
            "(for example Dissolve) once, then use Fade mode.")
    body = {"transition": {
        "uuid": transition["uuid"],
        "name": transition.get("name", ""),
        "duration": float(seconds),
    }}
    url = "{}/v1/prop/{}".format(_base_url(host, port), urllib.parse.quote(str(prop_id), safe=""))
    _request("PUT", url, body, timeout)


def trigger_prop(host, port, prop_id, mode="trigger", fade_seconds=0.6, timeout=3.0):
    """Makes ProPresenter reload the prop's RSS Linked Text using the chosen mode."""
    if mode not in REFRESH_MODES:
        raise ProPresenterError("Unknown refresh mode '{}'.".format(mode))
    if not str(prop_id).strip():
        raise ProPresenterError("No prop selected.")
    base = _base_url(host, port)
    encoded = urllib.parse.quote(str(prop_id), safe="")
    if mode == "clear_trigger":
        _get("{}/v1/prop/{}/clear".format(base, encoded), timeout)
        time.sleep(0.3)  # give ProPresenter a beat to finish the clear transition
    elif mode == "fade_trigger":
        set_prop_transition_duration(host, port, prop_id, fade_seconds, timeout)
    _get("{}/v1/prop/{}/trigger".format(base, encoded), timeout)
