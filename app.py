import os
import json
import xml.etree.ElementTree as ET
# pyrefly: ignore [missing-import]
from flask import Flask, Response

app = Flask(__name__)

SOURCE_URL = os.environ.get('XML_URL', 'https://legacy.scoreatl.com/xml/scoreboard/hs/top/')
CONFIG_FILE = 'config.json'

def get_config():
    """Reads the configuration file, sets defaults if missing."""
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "enable_spacer": True,
            "custom_items": [],
            "output_items": []
        }

@app.route('/')
@app.route('/rss')
def get_rss():
    config = get_config()
    
    # Build base RSS 2.0 structure
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Score Atlanta High School Scoreboard"
    ET.SubElement(channel, "link").text = SOURCE_URL
    ET.SubElement(channel, "description").text = "Live dynamic feed conversion for scoreatl.com"

    output_items = config.get("output_items")
    if output_items is None:
        output_items = config.get("custom_items", [])

    for i, item_text in enumerate(output_items):
        if not item_text or not str(item_text).strip():
            continue
            
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = str(item_text).strip()
        ET.SubElement(item, "link").text = f"{SOURCE_URL}#item_{i}"
        
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
        ET.SubElement(spacer_item, "link").text = f"{SOURCE_URL}#spacer"
        ET.SubElement(spacer_item, "guid").text = "spacer_end"

    # Convert XML to string and replace escaped CDATA markers
    rss_output = ET.tostring(rss, encoding='utf-8', xml_declaration=True).decode('utf-8')
    rss_output = rss_output.replace('&lt;![CDATA[', '<![CDATA[').replace(']]&gt;', ']]>')

    return Response(rss_output, mimetype='application/rss+xml')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)