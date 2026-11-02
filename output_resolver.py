"""
output_resolver.py - Pure functions that turn the stored settings plus the
current live feed into the final ticker items. Shared by the control panel
(gui.py) and the background watcher (watcher.TickerWatcher).

Ticker order is always:
    1. every item from the live XML feed, in feed order (when the feed is on)
    2. every custom box that is switched on, top to bottom

Stored config keys:
    live_enabled  bool, default True. Off = only custom boxes go on air.
    custom_items  list of {"text": str, "enabled": bool}
    output_items  list of {"source": "live"|"custom", "id": str, "text": str},
                  the computed result that app.py serves at /rss.
"""

SEPARATOR = "  |  "


def _as_bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def normalize_custom_items(raw_custom, legacy_output=None):
    """
    Returns custom boxes as [{"text", "enabled"}].

    Older configs stored custom boxes as plain strings and chose what was on
    air by putting items into output_items by hand. For those, a box starts
    switched on only if its text was on air, and custom text that was on air
    without a matching box gets a box of its own, so upgrading never changes
    what the ticker shows.
    """
    raw_custom = raw_custom or []
    if all(isinstance(it, dict) for it in raw_custom) and raw_custom:
        return [
            {"text": str(it.get("text", "") or ""), "enabled": _as_bool(it.get("enabled"), True)}
            for it in raw_custom
        ]

    on_air = []
    for it in legacy_output or []:
        if isinstance(it, dict) and it.get("source", "custom") == "custom":
            text = str(it.get("text", "") or "").strip()
        elif isinstance(it, str):
            text = it.strip()
        else:
            continue
        if text and text not in on_air:
            on_air.append(text)

    boxes = []
    for it in raw_custom:
        if isinstance(it, dict):
            text = str(it.get("text", "") or "")
            boxes.append({"text": text, "enabled": _as_bool(it.get("enabled"), True)})
            continue
        text = str(it or "")
        if not text.strip():
            continue
        boxes.append({"text": text, "enabled": text.strip() in on_air})

    have = {b["text"].strip() for b in boxes}
    for text in on_air:
        if text not in have:
            boxes.append({"text": text, "enabled": True})
    return boxes


def ticker_settings(config):
    """(live_enabled, custom_items) read from a config dict, upgrading old formats."""
    live_enabled = _as_bool(config.get("live_enabled"), True)
    custom_items = normalize_custom_items(config.get("custom_items"), config.get("output_items"))
    return live_enabled, custom_items


def build_output_items(live_enabled, live_items, custom_items, previous_output=None, live_ok=True):
    """
    live_enabled:    whether the XML feed is on air.
    live_items:      list of {id, title} from fetch_live_data.
    custom_items:    list of {text, enabled} from normalize_custom_items.
    previous_output: the stored output_items. Used for the live part when
                     live_ok is False, so a failed fetch (or an edit that did
                     not refetch) keeps the last good scores on air.
    Returns the list of {source, id, text} to store as output_items.
    """
    output = []
    if live_enabled:
        if live_ok:
            for it in live_items or []:
                title = str(it.get("title", "") or "").strip()
                if title:
                    output.append({"source": "live", "id": it.get("id", ""), "text": title})
        else:
            for it in previous_output or []:
                if isinstance(it, dict) and it.get("source") == "live" and str(it.get("text", "")).strip():
                    output.append({"source": "live", "id": it.get("id", ""), "text": it["text"]})
    for box in custom_items or []:
        text = str(box.get("text", "") or "").strip()
        if box.get("enabled") and text:
            output.append({"source": "custom", "id": "", "text": text})
    return output


def ticker_text(output_items):
    """The combined single-line ticker preview string."""
    valid = [it["text"].strip() for it in output_items if it.get("text") and it["text"].strip()]
    return SEPARATOR.join(valid)
