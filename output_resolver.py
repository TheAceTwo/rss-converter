"""
output_resolver.py - Pure functions that turn stored output items plus the
current live feed into the final ticker items. Shared by the control panel
page (gui.index) and the background watcher (watcher.TickerWatcher).
"""

SEPARATOR = "  |  "


def resolve_output_items(raw_output_items, live_items, items_by_id):
    """
    raw_output_items: list of dicts {source,id,text} or legacy plain strings
                      as stored in config.json["output_items"].
    live_items:       list of {id,title,source} from fetch_live_data.
    items_by_id:      {live_id: title} from fetch_live_data.
    Returns a new list of {source,id,text} dicts with live text refreshed.
    """
    output_items = []
    for it in raw_output_items or []:
        if isinstance(it, dict):
            src = it.get("source", "custom")
            item_id = it.get("id", "")
            current_text = it.get("text", "")
            if src == "live" and item_id and item_id in items_by_id:
                resolved_text = items_by_id[item_id]
            else:
                resolved_text = current_text
            output_items.append({"source": src, "id": item_id, "text": resolved_text})
        elif isinstance(it, str):
            matched_id = None
            resolved_text = it.strip()
            for live_it in live_items:
                lid = live_it["id"]
                ltitle = live_it["title"]
                parts = lid.split("|")
                if len(parts) == 2 and parts[0] in it and parts[1] in it:
                    matched_id = lid
                    resolved_text = items_by_id.get(matched_id, it.strip())
                    break
                elif it.strip() == ltitle.strip() or it.strip() in ltitle or ltitle in it.strip():
                    matched_id = lid
                    resolved_text = items_by_id.get(matched_id, it.strip())
                    break
            if matched_id:
                output_items.append({"source": "live", "id": matched_id, "text": resolved_text})
            else:
                output_items.append({"source": "custom", "id": "", "text": resolved_text})
    return output_items


def ticker_text(output_items):
    """The combined single-line ticker preview string."""
    valid = [it["text"].strip() for it in output_items if it.get("text") and it["text"].strip()]
    return SEPARATOR.join(valid)
