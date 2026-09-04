import os
import json
import xml.etree.ElementTree as ET
# pyrefly: ignore [missing-import]
from flask import Flask, Response

app = Flask(__name__)

DEFAULT_LIVE_LINK = os.environ.get('XML_URL', '')
CONFIG_FILE = 'config.json'

# ==============================================================================
# DEFAULT CONFIGURATION
# - live_link: XML/RSS source link. Leave empty ("") if using custom text items only.
# - enable_spacer: Appends a blank item to the RSS feed for smooth ticker looping.
# - auth_username & auth_password: Login credentials for the web management GUI (gui.py).
#   IMPORTANT: Setting EITHER auth_username OR auth_password to "" (empty string)
#   completely DISABLES login authentication, allowing open access to the GUI.
# ==============================================================================
DEFAULT_CONFIG = {
    "live_link": DEFAULT_LIVE_LINK,
    "enable_spacer": True,
    "auth_username": "heres-200-digits-of-pi-since-you-wont-change-the-default-login",
    "auth_password": "3.14159265358979323846264338327950288419716939937510582097494459230781640628620899862803482534211706798214808651328230664709384460955058223172535940812848111745028410270193852110555964462294895493038196",
    "custom_items": [""],
    "output_items": []
}

def save_config(config):
    """Saves the configuration to config.json."""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def get_config():
    """Reads the configuration file, creating and setting defaults if missing."""
    if not os.path.exists(CONFIG_FILE):
        cfg = DEFAULT_CONFIG.copy()
        try:
            save_config(cfg)
        except OSError:
            pass
        return cfg
    try:
        with open(CONFIG_FILE, 'r') as f:
            cfg = json.load(f)
            if "live_link" not in cfg:
                cfg["live_link"] = DEFAULT_LIVE_LINK
            return cfg
    except (FileNotFoundError, json.JSONDecodeError):
        cfg = DEFAULT_CONFIG.copy()
        try:
            save_config(cfg)
        except OSError:
            pass
        return cfg

@app.route('/')
@app.route('/rss')
def get_rss():
    config = get_config()
    source_url = config.get("live_link") or DEFAULT_LIVE_LINK
    
    # Build base RSS 2.0 structure
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Dynamic RSS Feed"
    ET.SubElement(channel, "link").text = source_url or "http://localhost:5000/rss"
    ET.SubElement(channel, "description").text = "Live dynamic feed conversion"

    output_items = config.get("output_items")
    if output_items is None:
        output_items = config.get("custom_items", [])

    for i, raw_item in enumerate(output_items):
        item_text = raw_item.get('text', '') if isinstance(raw_item, dict) else str(raw_item)
        if not item_text or not str(item_text).strip():
            continue
            
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = str(item_text).strip()
        ET.SubElement(item, "link").text = f"{source_url}#item_{i}" if source_url else f"#item_{i}"
        
        html_desc = f"<h3>{str(item_text).strip()}</h3><p>Active Output Feed Item</p>"
        desc_element = ET.SubElement(item, "description")
        desc_element.text = f"<![CDATA[{html_desc}]]>"
        
        ET.SubElement(item, "guid").text = f"output_item_{i}"

    # ==========================================
    # LOOP SPACER INJECTION
    # ==========================================
    if config.get("enable_spacer", True):
        spacer_item = ET.SubElement(channel, "item")
        ET.SubElement(spacer_item, "title").text = "\u00A0"
        ET.SubElement(spacer_item, "link").text = f"{source_url}#spacer" if source_url else "#spacer"
        ET.SubElement(spacer_item, "guid").text = "spacer_end"

    # Convert XML to string and replace escaped CDATA markers
    rss_output = ET.tostring(rss, encoding='utf-8', xml_declaration=True).decode('utf-8')
    rss_output = rss_output.replace('&lt;![CDATA[', '<![CDATA[').replace(']]&gt;', ']]>')

    return Response(rss_output, mimetype='application/rss+xml')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)