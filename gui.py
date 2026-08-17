import os
import json
import xml.etree.ElementTree as ET
import urllib.request
# pyrefly: ignore [missing-import]
from flask import Flask, render_template_string, request, redirect, url_for

app = Flask(__name__)
CONFIG_FILE = 'config.json'
DEFAULT_LIVE_LINK = os.environ.get('XML_URL', 'https://legacy.scoreatl.com/xml/scoreboard/hs/top/')

def get_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            cfg = json.load(f)
            if "live_link" not in cfg:
                cfg["live_link"] = DEFAULT_LIVE_LINK
            return cfg
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "live_link": DEFAULT_LIVE_LINK,
            "enable_spacer": True,
            "custom_items": [""],
            "output_items": []
        }

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def node_to_dict(node):
    """Recursively converts XML nodes into a clean dictionary structure."""
    data = {}
    for child in node:
        text = (child.text or '').strip()
        if len(child) == 0:
            data[child.tag] = text
        else:
            data[child.tag] = node_to_dict(child)
    return data

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RSS Control Panel</title>
    <style>
        * { box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; 
            background: #141414; color: #e0e0e0; margin: 0; padding: 20px; padding-bottom: 120px; 
            user-select: none;
        }
        .container { max-width: 1500px; margin: 0 auto; }
        
        /* Header */
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #2e2e2e; padding-bottom: 15px; margin-bottom: 24px; }
        .header-title { display: flex; align-items: center; gap: 12px; }
        h1 { margin: 0; font-size: 1.6rem; color: #ffffff; font-weight: 700; letter-spacing: -0.5px; }
        .badge-live { background: #0066cc; color: #fff; font-size: 0.75rem; padding: 3px 8px; border-radius: 12px; font-weight: 600; text-transform: uppercase; }
        
        /* Buttons */
        .btn { background: #0066cc; color: #fff; padding: 10px 18px; border: none; border-radius: 6px; text-decoration: none; cursor: pointer; font-weight: 600; font-size: 0.92rem; display: inline-flex; align-items: center; justify-content: center; gap: 6px; transition: all 0.15s ease; }
        .btn:hover { background: #0052a3; transform: translateY(-1px); }
        .btn:active { transform: translateY(0); }
        .btn-toggle-on { background: #1b6329; border: 1px solid #2b8a3e; }
        .btn-toggle-on:hover { background: #237834; }
        .btn-toggle-off { background: #611e1e; border: 1px solid #8e2a2a; }
        .btn-toggle-off:hover { background: #782727; }
        .btn-success { background: #16a34a; }
        .btn-success:hover { background: #15803d; }
        .btn-danger { background: #dc2626; color: #fff; }
        .btn-danger:hover { background: #b91c1c; }
        
        .controls { display: flex; gap: 10px; align-items: center; }
        
        /* Grid Layout */
        .grid { display: grid; grid-template-columns: 1fr 1fr 1.15fr; gap: 24px; margin-bottom: 30px; align-items: start; }
        
        /* Panels */
        .panel { 
            background: #1c1c1c; 
            border: 1px solid #2e2e2e; 
            border-radius: 8px; 
            padding: 20px; 
            display: flex; 
            flex-direction: column;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        }
        .panel-output {
            border: 1px solid #0066cc;
            background: #181c22;
        }
        .panel-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #2e2e2e;
            padding-bottom: 12px;
            margin-bottom: 14px;
        }
        .panel-header h3 { margin: 0; color: #ffffff; font-size: 1.15rem; font-weight: 600; display: flex; align-items: center; gap: 8px; }
        .item-count-badge { background: #2a2a2a; color: #aaa; font-size: 0.78rem; padding: 2px 8px; border-radius: 10px; font-weight: 500; }
        
        .instructions-hint { font-size: 0.82rem; color: #8c8c8c; margin-bottom: 12px; line-height: 1.4; }
        
        /* List Box */
        .item-list { 
            background: #121212; 
            border: 1px solid #282828; 
            border-radius: 6px; 
            flex: 1;
            padding: 6px;
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        
        /* Draggable Cards */
        .draggable-card {
            background: #222222;
            border: 1px solid #333333;
            border-radius: 5px;
            padding: 10px 12px;
            font-size: 0.95rem;
            color: #eee;
            cursor: grab;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            transition: all 0.15s ease;
            position: relative;
        }
        .draggable-card:hover {
            background: #2a2a2a;
            border-color: #0066cc;
            transform: translateX(2px);
        }
        .draggable-card:active {
            cursor: grabbing;
        }
        .draggable-card.dragging {
            opacity: 0.45;
            border: 1px dashed #0088ff;
        }
        
        .card-content {
            display: flex;
            align-items: center;
            gap: 10px;
            flex: 1;
            min-width: 0;
        }
        .drag-handle {
            color: #666;
            cursor: grab;
            font-size: 1.1rem;
            user-select: none;
            flex-shrink: 0;
            display: inline-flex;
            align-items: center;
        }
        .draggable-card:hover .drag-handle {
            color: #0088ff;
        }
        .card-text {
            word-break: break-word;
            font-family: inherit;
            font-size: 0.93rem;
            line-height: 1.35;
        }
        .card-index {
            color: #777;
            font-size: 0.8rem;
            font-weight: bold;
            min-width: 22px;
            flex-shrink: 0;
        }

        /* Quick Add Button on hover for Box 1 */
        .btn-quick-add {
            background: #252525;
            border: 1px solid #444;
            color: #aaa;
            border-radius: 4px;
            padding: 3px 8px;
            font-size: 0.75rem;
            cursor: pointer;
            transition: all 0.12s ease;
            flex-shrink: 0;
            opacity: 0.6;
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }
        .draggable-card:hover .btn-quick-add {
            opacity: 1;
        }
        .btn-quick-add:hover {
            background: #0066cc;
            border-color: #0066cc;
            color: #fff;
        }
        
        /* Dynamic Custom Editor */
        .custom-row { 
            display: flex; 
            align-items: center; 
            gap: 8px; 
            background: #222222; 
            border: 1px solid #333333; 
            padding: 6px 10px; 
            border-radius: 5px; 
            transition: border-color 0.15s ease;
        }
        .custom-row:hover {
            border-color: #444;
        }
        .custom-row.dragging {
            opacity: 0.45;
            border: 1px dashed #0088ff;
        }
        .custom-input { 
            flex: 1; 
            user-select: text; 
            background: #141414; 
            border: 1px solid #3a3a3a; 
            color: #fff; 
            padding: 8px 10px; 
            border-radius: 4px; 
            font-size: 0.92rem; 
        }
        .custom-input:focus { border-color: #0066cc; outline: none; background: #161616; }
        
        .btn-remove { 
            background: #401818; 
            color: #ff8888; 
            border: 1px solid #632323; 
            border-radius: 4px; 
            padding: 6px 8px; 
            cursor: pointer; 
            font-weight: bold; 
            font-size: 0.88rem; 
            display: flex; 
            align-items: center; 
            justify-content: center;
            transition: all 0.12s ease;
            flex-shrink: 0;
        }
        .btn-remove:hover { background: #b91c1c; border-color: #ef4444; color: #fff; }
        
        .btn-add { 
            background: #1c2b1c; 
            color: #86efac; 
            border: 1px solid #235427; 
            width: 100%; 
            margin-top: 10px; 
            margin-bottom: 10px; 
            cursor: pointer; 
            padding: 9px; 
            border-radius: 5px; 
            font-weight: 600; 
            font-size: 0.9rem; 
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            transition: all 0.12s ease;
        }
        .btn-add:hover { background: #166534; border-color: #22c55e; color: #fff; }

        .icon { display: inline-block; vertical-align: middle; flex-shrink: 0; }

        /* Output Box Styles & Drop Target */
        .output-drop-zone {
            border: 2px dashed #2a4158;
            background: #11151a;
            min-height: 120px;
            border-radius: 6px;
            transition: all 0.2s ease;
        }
        .output-drop-zone.drag-over {
            border-color: #0088ff;
            background: #132233;
            box-shadow: inset 0 0 16px rgba(0, 136, 255, 0.25);
        }
        .empty-placeholder {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 30px 15px;
            color: #667788;
            text-align: center;
            pointer-events: none;
        }
        .empty-placeholder svg { margin-bottom: 10px; opacity: 0.6; }
        
        .output-item-card {
            background: #1b2533;
            border: 1px solid #2c4159;
            border-radius: 5px;
            padding: 10px 12px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            cursor: grab;
            transition: all 0.15s ease;
        }
        .output-item-card:hover {
            background: #223247;
            border-color: #0088ff;
        }
        .output-item-card:active {
            cursor: grabbing;
        }
        .output-item-card.dragging {
            opacity: 0.4;
            border: 1px dashed #0088ff;
        }
        
        .drop-insertion-line {
            height: 3px;
            background: #0088ff;
            border-radius: 2px;
            margin: 2px 0;
            box-shadow: 0 0 8px #0088ff;
            pointer-events: none;
        }

        .output-actions {
            display: flex;
            gap: 10px;
            margin-top: 14px;
        }

        .status-text { margin-top: 12px; font-size: 0.83rem; color: #888; }
        
        /* Broadcast Ticker */
        .ticker-wrapper { 
            position: fixed; 
            bottom: 0; 
            left: 0; 
            width: 100%; 
            background: rgba(12, 16, 22, 0.97); 
            border-top: 2px solid #0066cc; 
            box-shadow: 0 -4px 25px rgba(0,0,0,0.85); 
            overflow: hidden; 
            white-space: nowrap; 
            height: 60px; 
            display: flex; 
            align-items: center; 
            z-index: 1000;
        }
        .ticker-label { 
            background: #0066cc; 
            color: #fff; 
            font-weight: 700; 
            font-size: 0.82rem; 
            text-transform: uppercase; 
            padding: 0 18px; 
            height: 100%; 
            display: flex; 
            align-items: center; 
            letter-spacing: 1px; 
            z-index: 10; 
            flex-shrink: 0; 
        }
        .ticker-content { 
            display: inline-block; 
            white-space: nowrap; 
            padding-left: 100%; 
            animation: ticker 35s linear infinite; 
            font-size: 1.18rem; 
            font-weight: 600; 
            color: #ffffff; 
            letter-spacing: 0.5px; 
        }
        @keyframes ticker { 0% { transform: translate3d(0, 0, 0); } 100% { transform: translate3d(-100%, 0, 0); } }
    </style>
</head>
<body>
    <div class="container">
        <!-- Top Header -->
        <div class="header">
            <div class="header-title">
                <h1>RSS Control Panel</h1>
                <span class="badge-live">ProPresenter Feed</span>
            </div>
            
            <div class="controls">
                <form action="/toggle_spacer" method="POST" style="margin:0;">
                    <button type="submit" class="btn {% if enable_spacer %}btn-toggle-on{% else %}btn-toggle-off{% endif %}" title="Toggle blank loop spacer item at the end of feed">
                        {% if enable_spacer %}
                            <svg class="icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                            <span>Loop Spacer: ON</span>
                        {% else %}
                            <svg class="icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                            <span>Loop Spacer: OFF</span>
                        {% endif %}
                    </button>
                </form>
                <a href="/" class="btn" title="Refresh Live Data">
                    <svg class="icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
                    <span>Refresh Feeds</span>
                </a>
            </div>
        </div>

        {% if error %}
            <div style="background: #421818; border: 1px solid #732626; color: #ffb3b3; padding: 12px 16px; border-radius: 6px; margin-bottom: 20px;">
                <strong>Notice:</strong> {{ error }}
            </div>
        {% endif %}

        <div class="grid">
            <!-- Box 1: Incoming Live Link Data (Source 1) -->
            <div class="panel">
                <div class="panel-header">
                    <h3>
                        <svg class="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4.9 19.1C1 15.2 1 8.8 4.9 4.9"/><path d="M7.8 16.2c-2.3-2.3-2.3-6.1 0-8.5"/><circle cx="12" cy="12" r="2"/><path d="M16.2 7.8c2.3 2.3 2.3 6.1 0 8.5"/><path d="M19.1 4.9C23 8.8 23 15.2 19.1 19.1"/></svg>
                        <span>Incoming Live Link</span>
                    </h3>
                    <span class="item-count-badge">{{ live_items|length }} Games</span>
                </div>
                <form action="/save_live_link" method="POST" style="margin-bottom: 12px; display: flex; gap: 8px;">
                    <input type="url" name="live_link" class="custom-input" value="{{ live_link }}" placeholder="Live XML URL..." required style="font-size: 0.85rem; padding: 6px 10px;">
                    <button type="submit" class="btn" style="padding: 6px 14px; font-size: 0.82rem; white-space: nowrap;" title="Save and load XML source URL">
                        <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
                        <span>Save URL</span>
                    </button>
                </form>

                <div class="instructions-hint">
                    Drag any game box below into the <strong>Output Box</strong> on the right.
                </div>
                
                <div class="item-list" id="live-items-list">
                    {% for item in live_items %}
                        <div class="draggable-card" 
                             draggable="true" 
                             data-source="live" 
                             data-text="{{ item }}"
                             ondragstart="handleSourceDragStart(event, this)">
                            <div class="card-content">
                                <span class="drag-handle" title="Drag to Output Box">
                                    <svg width="10" height="14" viewBox="0 0 10 14" fill="currentColor"><circle cx="2" cy="2" r="1.5"/><circle cx="8" cy="2" r="1.5"/><circle cx="2" cy="7" r="1.5"/><circle cx="8" cy="7" r="1.5"/><circle cx="2" cy="12" r="1.5"/><circle cx="8" cy="12" r="1.5"/></svg>
                                </span>
                                <span class="card-index">{{ loop.index }}.</span>
                                <span class="card-text">{{ item }}</span>
                            </div>
                            <button type="button" class="btn-quick-add" onclick="addTextToOutput('{{ item|replace("'", "\\'") }}')" title="Quick add to output">
                                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                                <span>Add</span>
                            </button>
                        </div>
                    {% else %}
                        <div style="padding: 20px; text-align: center; color: #666; font-style: italic;">
                            No live games currently available.
                        </div>
                    {% endfor %}
                </div>
                <p class="status-text">
                    Pulling live scores dynamically from configured XML feed.
                </p>
            </div>

            <!-- Box 2: Custom Text Editor (Source 2) -->
            <div class="panel">
                <div class="panel-header">
                    <h3>
                        <svg class="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#c084fc" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                        <span>Custom Text Feed</span>
                    </h3>
                    <span class="item-count-badge" id="custom-count">{{ custom_items|length }} Presets</span>
                </div>
                <div class="instructions-hint">
                    Type messages, drag them to Output, or save presets.
                </div>
                
                <form action="/save_custom" method="POST" id="custom-form" style="display: flex; flex-direction: column; flex: 1;">
                    <div class="item-list" id="custom-items-container">
                        {% for item in custom_items %}
                            <div class="custom-row" 
                                 draggable="true" 
                                 data-source="custom"
                                 ondragstart="handleCustomDragStart(event, this)">
                                <span class="drag-handle" title="Drag to Output Box">
                                    <svg width="10" height="14" viewBox="0 0 10 14" fill="currentColor"><circle cx="2" cy="2" r="1.5"/><circle cx="8" cy="2" r="1.5"/><circle cx="2" cy="7" r="1.5"/><circle cx="8" cy="7" r="1.5"/><circle cx="2" cy="12" r="1.5"/><circle cx="8" cy="12" r="1.5"/></svg>
                                </span>
                                <input type="text" 
                                       name="custom_item" 
                                       class="custom-input" 
                                       value="{{ item }}" 
                                       placeholder="Custom ticker text {{ loop.index }}..."
                                       oninput="updateCustomDragData(this)">
                                <button type="button" class="btn-remove" onclick="removeCustomRow(this)" title="Delete box">
                                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                                </button>
                            </div>
                        {% endfor %}
                    </div>
                    
                    <button type="button" class="btn-add" onclick="addCustomRow()">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                        <span>Add Custom Text Box</span>
                    </button>
                    <button type="submit" class="btn" style="width: 100%;">
                        <svg class="icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
                        <span>Save Custom Presets</span>
                    </button>
                </form>
                <p class="status-text">
                    Custom text presets are stored and ready to drag into the output feed anytime.
                </p>
            </div>
            
            <!-- Box 3: Final Output Feed (Target Drop Zone) -->
            <div class="panel panel-output">
                <div class="panel-header">
                    <h3>
                        <svg class="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#4ade80" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>
                        <span>Active Output Feed</span>
                    </h3>
                    <span class="item-count-badge" id="output-count" style="background:#0066cc; color:#fff;">{{ output_items|length }} Active</span>
                </div>
                <div class="instructions-hint">
                    Drop boxes here from Live Feed or Custom Text. Drag to reorder, click remove to delete.
                </div>
                
                <form action="/save_output" method="POST" id="output-form" style="display: flex; flex-direction: column; flex: 1;">
                    <div class="item-list output-drop-zone" 
                         id="output-items-container"
                         ondragover="handleOutputDragOver(event)"
                         ondragenter="handleOutputDragEnter(event)"
                         ondragleave="handleOutputDragLeave(event)"
                         ondrop="handleOutputDrop(event)">
                        
                        {% for item in output_items %}
                            <div class="output-item-card" 
                                 draggable="true" 
                                 data-text="{{ item }}"
                                 ondragstart="handleOutputItemDragStart(event, this)"
                                 ondragend="handleOutputItemDragEnd(event, this)">
                                <input type="hidden" name="output_item" value="{{ item }}">
                                <div class="card-content">
                                    <span class="drag-handle" title="Drag to reorder">
                                        <svg width="10" height="14" viewBox="0 0 10 14" fill="currentColor"><circle cx="2" cy="2" r="1.5"/><circle cx="8" cy="2" r="1.5"/><circle cx="2" cy="7" r="1.5"/><circle cx="8" cy="7" r="1.5"/><circle cx="2" cy="12" r="1.5"/><circle cx="8" cy="12" r="1.5"/></svg>
                                    </span>
                                    <span class="card-index">{{ loop.index }}.</span>
                                    <span class="card-text">{{ item }}</span>
                                </div>
                                <button type="button" class="btn-remove" onclick="removeOutputRow(this)" title="Remove from output feed">
                                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                                </button>
                            </div>
                        {% endfor %}
                        
                        <div class="empty-placeholder" id="output-empty-msg" style="{% if output_items %}display: none;{% endif %}">
                            <svg width="40" height="40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"></path>
                            </svg>
                            <div><strong>Drop boxes here</strong></div>
                            <div style="font-size: 0.8rem; margin-top: 4px; color: #556677;">Drag games or custom texts here to build your broadcast feed</div>
                        </div>
                    </div>
                    
                    <button type="submit" class="btn btn-success" style="width: 100%; margin-top: 14px;" title="Save changes and immediately update RSS feed sent to ProPresenter">
                        <svg class="icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
                        <span>Save Output Feed</span>
                    </button>
                </form>
                <p class="status-text">
                    Press <strong>Save Output Feed</strong> to push your curated lineup live to ProPresenter.
                </p>
            </div>
        </div>
    </div>

    <!-- Ticker Preview -->
    {% if combined_ticker %}
        <div class="ticker-wrapper">
            <div class="ticker-label">
                ACTIVE BROADCAST
            </div>
            <div class="ticker-content">
                {{ combined_ticker }} &nbsp;&nbsp;&nbsp;&nbsp; {{ combined_ticker }}
            </div>
        </div>
    {% endif %}

    <script>
        let draggedData = null;
        let draggedElement = null;
        let isReorderingOutput = false;

        // --- Box 1: Live Feed Drag Handlers ---
        function handleSourceDragStart(e, el) {
            const text = el.getAttribute('data-text');
            draggedData = text;
            draggedElement = el;
            isReorderingOutput = false;
            e.dataTransfer.setData('text/plain', text);
            e.dataTransfer.effectAllowed = 'copy';
            el.classList.add('dragging');
            setTimeout(() => el.classList.remove('dragging'), 0);
        }

        // --- Box 2: Custom Text Drag Handlers ---
        function handleCustomDragStart(e, el) {
            const input = el.querySelector('input');
            const text = (input ? input.value : '').trim();
            if (!text) {
                e.preventDefault();
                return;
            }
            draggedData = text;
            draggedElement = el;
            isReorderingOutput = false;
            e.dataTransfer.setData('text/plain', text);
            e.dataTransfer.effectAllowed = 'copy';
            el.classList.add('dragging');
            setTimeout(() => el.classList.remove('dragging'), 0);
        }

        function updateCustomDragData(input) {
            const row = input.closest('.custom-row');
            if (row) {
                row.setAttribute('data-text', input.value);
            }
        }

        function addCustomRow() {
            const container = document.getElementById('custom-items-container');
            const count = container.querySelectorAll('.custom-row').length + 1;
            const div = document.createElement('div');
            div.className = 'custom-row';
            div.draggable = true;
            div.setAttribute('data-source', 'custom');
            div.ondragstart = function(e) { handleCustomDragStart(e, this); };
            div.innerHTML = `
                <span class="drag-handle" title="Drag to Output Box">
                    <svg width="10" height="14" viewBox="0 0 10 14" fill="currentColor"><circle cx="2" cy="2" r="1.5"/><circle cx="8" cy="2" r="1.5"/><circle cx="2" cy="7" r="1.5"/><circle cx="8" cy="7" r="1.5"/><circle cx="2" cy="12" r="1.5"/><circle cx="8" cy="12" r="1.5"/></svg>
                </span>
                <input type="text" name="custom_item" class="custom-input" placeholder="Custom ticker text ${count}..." oninput="updateCustomDragData(this)">
                <button type="button" class="btn-remove" onclick="removeCustomRow(this)" title="Delete box">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
            `;
            container.appendChild(div);
            updateCustomCount();
            div.querySelector('input').focus();
        }

        function removeCustomRow(btn) {
            const container = document.getElementById('custom-items-container');
            const rows = container.querySelectorAll('.custom-row');
            if (rows.length > 1) {
                btn.parentElement.remove();
            } else {
                const input = btn.parentElement.querySelector('input');
                if (input) input.value = '';
            }
            updateCustomCount();
        }

        function updateCustomCount() {
            const count = document.querySelectorAll('#custom-items-container .custom-row').length;
            const badge = document.getElementById('custom-count');
            if (badge) badge.textContent = `${count} Presets`;
        }

        // --- Box 3: Output Box Reordering & Drop Handlers ---
        function handleOutputItemDragStart(e, el) {
            draggedElement = el;
            draggedData = el.getAttribute('data-text');
            isReorderingOutput = true;
            e.dataTransfer.setData('text/plain', draggedData);
            e.dataTransfer.effectAllowed = 'move';
            setTimeout(() => el.classList.add('dragging'), 0);
        }

        function handleOutputItemDragEnd(e, el) {
            el.classList.remove('dragging');
            cleanupDropIndicators();
        }

        function handleOutputDragOver(e) {
            e.preventDefault();
            e.dataTransfer.dropEffect = isReorderingOutput ? 'move' : 'copy';
            const container = document.getElementById('output-items-container');
            container.classList.add('drag-over');

            const afterElement = getDragAfterElement(container, e.clientY);
            cleanupDropIndicators();

            if (afterElement == null) {
                const placeholder = document.getElementById('output-empty-msg');
                if (placeholder && placeholder.style.display !== 'none') {
                    // Do nothing
                } else {
                    const indicator = getOrCreateIndicator();
                    container.appendChild(indicator);
                }
            } else {
                const indicator = getOrCreateIndicator();
                container.insertBefore(indicator, afterElement);
            }
        }

        function handleOutputDragEnter(e) {
            e.preventDefault();
            document.getElementById('output-items-container').classList.add('drag-over');
        }

        function handleOutputDragLeave(e) {
            const container = document.getElementById('output-items-container');
            if (!container.contains(e.relatedTarget)) {
                container.classList.remove('drag-over');
                cleanupDropIndicators();
            }
        }

        function handleOutputDrop(e) {
            e.preventDefault();
            const container = document.getElementById('output-items-container');
            container.classList.remove('drag-over');
            
            let text = e.dataTransfer.getData('text/plain') || draggedData;
            if (!text || !text.trim()) {
                cleanupDropIndicators();
                return;
            }
            text = text.trim();

            const afterElement = getDragAfterElement(container, e.clientY);
            cleanupDropIndicators();

            if (isReorderingOutput && draggedElement && draggedElement.classList.contains('output-item-card')) {
                // Reordering an existing output card
                if (afterElement == null) {
                    container.appendChild(draggedElement);
                } else {
                    container.insertBefore(draggedElement, afterElement);
                }
            } else {
                // Dragging a new item from Live Feed or Custom Feed
                const newCard = createOutputCard(text);
                if (afterElement == null) {
                    container.appendChild(newCard);
                } else {
                    container.insertBefore(newCard, afterElement);
                }
            }

            updateOutputUI();
            draggedData = null;
            draggedElement = null;
            isReorderingOutput = false;
        }

        function createOutputCard(text) {
            const card = document.createElement('div');
            card.className = 'output-item-card';
            card.draggable = true;
            card.setAttribute('data-text', text);
            card.ondragstart = function(e) { handleOutputItemDragStart(e, this); };
            card.ondragend = function(e) { handleOutputItemDragEnd(e, this); };

            // Escape HTML for text
            const safeText = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
            
            card.innerHTML = `
                <input type="hidden" name="output_item" value="${safeText}">
                <div class="card-content">
                    <span class="drag-handle" title="Drag to reorder">
                        <svg width="10" height="14" viewBox="0 0 10 14" fill="currentColor"><circle cx="2" cy="2" r="1.5"/><circle cx="8" cy="2" r="1.5"/><circle cx="2" cy="7" r="1.5"/><circle cx="8" cy="7" r="1.5"/><circle cx="2" cy="12" r="1.5"/><circle cx="8" cy="12" r="1.5"/></svg>
                    </span>
                    <span class="card-index"></span>
                    <span class="card-text">${safeText}</span>
                </div>
                <button type="button" class="btn-remove" onclick="removeOutputRow(this)" title="Remove from output feed">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
            `;
            return card;
        }

        function addTextToOutput(text) {
            if (!text || !text.trim()) return;
            const container = document.getElementById('output-items-container');
            const newCard = createOutputCard(text.trim());
            container.appendChild(newCard);
            updateOutputUI();
        }

        function removeOutputRow(btn) {
            const card = btn.closest('.output-item-card');
            if (card) {
                card.remove();
                updateOutputUI();
            }
        }

        function updateOutputUI() {
            const container = document.getElementById('output-items-container');
            const cards = container.querySelectorAll('.output-item-card');
            const placeholder = document.getElementById('output-empty-msg');
            const badge = document.getElementById('output-count');

            if (cards.length === 0) {
                if (placeholder) placeholder.style.display = 'flex';
            } else {
                if (placeholder) placeholder.style.display = 'none';
            }

            cards.forEach((card, index) => {
                const indexSpan = card.querySelector('.card-index');
                if (indexSpan) {
                    indexSpan.textContent = `${index + 1}.`;
                }
            });

            if (badge) {
                badge.textContent = `${cards.length} Active`;
            }
        }

        function getDragAfterElement(container, y) {
            const draggableElements = [...container.querySelectorAll('.output-item-card:not(.dragging)')];

            return draggableElements.reduce((closest, child) => {
                const box = child.getBoundingClientRect();
                const offset = y - box.top - box.height / 2;
                if (offset < 0 && offset > closest.offset) {
                    return { offset: offset, element: child };
                } else {
                    return closest;
                }
            }, { offset: Number.NEGATIVE_INFINITY }).element;
        }

        let activeIndicator = null;
        function getOrCreateIndicator() {
            if (!activeIndicator) {
                activeIndicator = document.createElement('div');
                activeIndicator.className = 'drop-insertion-line';
            }
            return activeIndicator;
        }

        function cleanupDropIndicators() {
            if (activeIndicator && activeIndicator.parentElement) {
                activeIndicator.parentElement.removeChild(activeIndicator);
            }
            activeIndicator = null;
        }

        // Initialize UI numbers on page load
        document.addEventListener('DOMContentLoaded', () => {
            updateOutputUI();
            updateCustomCount();
        });
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    config = get_config()
    custom_items = config.get("custom_items", [])
    output_items = config.get("output_items")
    live_link = config.get("live_link") or DEFAULT_LIVE_LINK
    
    if output_items is None:
        output_items = list(custom_items) if custom_items else []
    
    if not custom_items:
        custom_items = [""]
    
    live_items = []
    error = None
    combined_ticker = ""

    # Generate combined ticker from output_items
    if output_items:
        valid_items = [str(it).strip() for it in output_items if str(it).strip()]
        combined_ticker = "  |  ".join(valid_items)

    # Fetch The Raw Source XML (Independent parsing for Box 1)
    try:
        req_live = urllib.request.Request(live_link, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req_live, timeout=5) as resp_live:
            raw_xml_live = resp_live.read()
            
        root_live = ET.fromstring(raw_xml_live)
        
        for game in root_live.findall('game'):
            game_data = node_to_dict(game)
            
            home = game_data.get('home', {})
            away = game_data.get('away', {})
            
            away_name = away.get('name', 'Away')
            away_score = away.get('score', '0')
            home_name = home.get('name', 'Home')
            home_score = home.get('score', '0')
            
            status = game_data.get('statusText', '').strip()
            
            if status and status not in ["0", "Q0"]:
                title_str = f"{away_name} {away_score} {home_name} {home_score} {status}"
            else:
                title_str = f"{away_name} {away_score} {home_name} {home_score}"
                
            live_items.append(title_str)
            
    except Exception as e:
        error = f"Error fetching live XML: {str(e)}"

    return render_template_string(
        HTML_TEMPLATE, 
        output_items=output_items,
        live_items=live_items,
        live_link=live_link,
        combined_ticker=combined_ticker,
        error=error,
        enable_spacer=config.get("enable_spacer", True),
        custom_items=custom_items
    )

@app.route('/save_live_link', methods=['POST'])
def save_live_link():
    config = get_config()
    new_url = request.form.get('live_link', '').strip()
    if new_url:
        config['live_link'] = new_url
        save_config(config)
    return redirect(url_for('index'))

@app.route('/toggle_spacer', methods=['POST'])
def toggle_spacer():
    config = get_config()
    config['enable_spacer'] = not config.get('enable_spacer', True)
    save_config(config)
    return redirect(url_for('index'))

@app.route('/save_output', methods=['POST'])
def save_output():
    config = get_config()
    submitted_items = request.form.getlist('output_item')
    
    # Strip whitespace and omit completely blank entries
    cleaned_items = [item.strip() for item in submitted_items if item.strip()]
    
    config['output_items'] = cleaned_items
    save_config(config)
    return redirect(url_for('index'))

@app.route('/save_custom', methods=['POST'])
def save_custom():
    config = get_config()
    submitted_items = request.form.getlist('custom_item')
    
    # Strip whitespace and omit completely blank entries
    cleaned_items = [item.strip() for item in submitted_items if item.strip()]
    
    config['custom_items'] = cleaned_items if cleaned_items else [""]
    save_config(config)
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)