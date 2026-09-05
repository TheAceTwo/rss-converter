import os
import json
import time
import xml.etree.ElementTree as ET
import urllib.request
# pyrefly: ignore [missing-import]
from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify
import logger as activity_log
from output_resolver import resolve_output_items, ticker_text
import propresenter
from watcher import TickerWatcher

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'rss-converter-gui-secret-key-999')
CONFIG_FILE = 'config.json'
DEFAULT_LIVE_LINK = os.environ.get('XML_URL', '')

# ==============================================================================
# DEFAULT CONFIGURATION
# - live_link: XML/RSS source link. Leave empty ("") if using custom text items only.
# - enable_spacer: Appends a blank item to the RSS feed for smooth ticker looping.
# - auth_username & auth_password: These are NOT included in the defaults.
#   They can ONLY be set by manually editing config.json.
#   The app will NEVER write or overwrite these fields — they are read-only from
#   the app's perspective. Setting either to "" (or omitting them) disables login.
# ==============================================================================
DEFAULT_CONFIG = {
    "live_link": DEFAULT_LIVE_LINK,
    "enable_spacer": True,
    "custom_items": [""],
    "output_items": []
}

# ------------------------------------------------------------------------------
# ProPresenter integration settings. Stored under config["propresenter"].
# enabled:               master switch for the background auto-trigger.
# host / port:           the ProPresenter machine (Settings > Network).
# prop_id / prop_name:   the prop that holds the RSS scrolling text.
# refresh_mode:          "trigger" | "clear_trigger" | "fade_trigger" (see propresenter.py).
# fade_seconds:          transition duration used by fade_trigger.
# ------------------------------------------------------------------------------
REFRESH_MODES = ("trigger", "clear_trigger", "fade_trigger")
PROPRESENTER_DEFAULTS = {
    "enabled": False,
    "host": "",
    "port": 1025,
    "prop_id": "",
    "prop_name": "",
    "refresh_mode": "trigger",
    "fade_seconds": 0.6,
}
DEFAULT_CONFIG["propresenter"] = dict(PROPRESENTER_DEFAULTS)


def _as_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def get_propresenter_settings(config):
    """Returns the propresenter block merged over defaults with types coerced."""
    raw = config.get("propresenter") or {}
    out = dict(PROPRESENTER_DEFAULTS)
    out["enabled"] = _as_bool(raw.get("enabled", out["enabled"]))
    out["host"] = str(raw.get("host", out["host"]) or "").strip()
    try:
        out["port"] = int(raw.get("port", out["port"]))
    except (TypeError, ValueError):
        out["port"] = PROPRESENTER_DEFAULTS["port"]
    out["prop_id"] = str(raw.get("prop_id", out["prop_id"]) or "").strip()
    out["prop_name"] = str(raw.get("prop_name", out["prop_name"]) or "").strip()
    mode = str(raw.get("refresh_mode", out["refresh_mode"]) or "").strip()
    out["refresh_mode"] = mode if mode in REFRESH_MODES else PROPRESENTER_DEFAULTS["refresh_mode"]
    try:
        fade = float(raw.get("fade_seconds", out["fade_seconds"]))
        out["fade_seconds"] = fade if 0 < fade <= 10 else PROPRESENTER_DEFAULTS["fade_seconds"]
    except (TypeError, ValueError):
        out["fade_seconds"] = PROPRESENTER_DEFAULTS["fade_seconds"]
    return out


# Auth fields are never written by the app — only by the user editing config.json directly.
_AUTH_KEYS = {"auth_username", "auth_password"}

def save_config(config):
    """Saves config to disk. Auth fields are always stripped from what gets written
    and re-read from the existing file so the app can never change them."""
    # Pull current auth off disk (if any) so they survive the write.
    preserved = {}
    try:
        with open(CONFIG_FILE, 'r') as f:
            on_disk = json.load(f)
        preserved = {k: on_disk[k] for k in _AUTH_KEYS if k in on_disk}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    # Strip auth from whatever was passed in, then put disk values back.
    out = {k: v for k, v in config.items() if k not in _AUTH_KEYS}
    out.update(preserved)

    with open(CONFIG_FILE, 'w') as f:
        json.dump(out, f, indent=2)

def get_config():
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


# The watcher is created at import so routes can call notify_change(), but the
# polling thread only starts in __main__ (see bottom of file). Tests import
# this module and must not spawn threads.
ticker_watcher = TickerWatcher(
    get_config=get_config,
    save_config=save_config,
    fetch_live_data=lambda link: fetch_live_data(link),
    get_settings=get_propresenter_settings,
    poll_seconds=15,
    debounce_seconds=3.0,
)

LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - RSS Control Panel</title>
    <style>
        * { box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; 
            background: #0f1117; 
            color: #e0e0e0; 
            margin: 0; 
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .login-card {
            width: 100%;
            max-width: 400px;
            background: #181c24;
            border: 1px solid #28303f;
            border-radius: 12px;
            padding: 36px 30px;
            box-shadow: 0 12px 36px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(255,255,255,0.05);
        }
        .logo-area {
            text-align: center;
            margin-bottom: 28px;
        }
        .logo-icon {
            width: 52px;
            height: 52px;
            border-radius: 12px;
            background: linear-gradient(135deg, #0066cc 0%, #0099ff 100%);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 12px;
            box-shadow: 0 4px 16px rgba(0, 102, 204, 0.4);
        }
        .logo-area h2 {
            margin: 0 0 6px 0;
            font-size: 1.4rem;
            color: #ffffff;
            font-weight: 700;
            letter-spacing: -0.4px;
        }
        .logo-area p {
            margin: 0;
            color: #7b879b;
            font-size: 0.88rem;
        }
        .form-group {
            margin-bottom: 18px;
        }
        .form-label {
            display: block;
            margin-bottom: 7px;
            font-size: 0.84rem;
            font-weight: 600;
            color: #abb5c4;
        }
        .form-input {
            width: 100%;
            background: #0f131a;
            border: 1px solid #28303f;
            color: #fff;
            padding: 11px 14px;
            border-radius: 7px;
            font-size: 0.95rem;
            transition: all 0.15s ease;
        }
        .form-input:focus {
            border-color: #0066cc;
            outline: none;
            box-shadow: 0 0 0 3px rgba(0, 102, 204, 0.25);
            background: #121721;
        }
        .btn-submit {
            width: 100%;
            background: #0066cc;
            color: #fff;
            padding: 12px;
            border: none;
            border-radius: 7px;
            font-weight: 600;
            font-size: 0.96rem;
            cursor: pointer;
            transition: all 0.15s ease;
            margin-top: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }
        .btn-submit:hover {
            background: #0052a3;
            transform: translateY(-1px);
            box-shadow: 0 4px 14px rgba(0, 102, 204, 0.4);
        }
        .btn-submit:active {
            transform: translateY(0);
        }
        .error-alert {
            background: #3d1418;
            border: 1px solid #6e2029;
            color: #fca5a5;
            padding: 10px 14px;
            border-radius: 7px;
            font-size: 0.86rem;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .footer-note {
            margin-top: 24px;
            text-align: center;
            font-size: 0.78rem;
            color: #576479;
        }
        .footer-note code {
            background: #10141d;
            padding: 2px 5px;
            border-radius: 4px;
            color: #8b9bb4;
            font-size: 0.76rem;
        }
    </style>
</head>
<body>
    <div class="login-card">
        <div class="logo-area">
            <div class="logo-icon">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                    <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                    <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
                </svg>
            </div>
            <h2>RSS Control Panel</h2>
            <p>Enter credentials to access the manager</p>
        </div>

        {% if error %}
            <div class="error-alert">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="12" y1="8" x2="12" y2="12"></line>
                    <line x1="12" y1="16" x2="12.01" y2="16"></line>
                </svg>
                <span>{{ error }}</span>
            </div>
        {% endif %}

        <form method="POST" action="/login">
            <div class="form-group">
                <label class="form-label" for="username">Username</label>
                <input type="text" id="username" name="username" class="form-input" placeholder="admin" required autofocus autocomplete="username" {% if is_locked %}disabled style="opacity:0.5; cursor:not-allowed;"{% endif %}>
            </div>
            <div class="form-group">
                <label class="form-label" for="password">Password</label>
                <input type="password" id="password" name="password" class="form-input" placeholder="••••••••" required autocomplete="current-password" {% if is_locked %}disabled style="opacity:0.5; cursor:not-allowed;"{% endif %}>
            </div>
            <button type="submit" class="btn-submit" {% if is_locked %}disabled style="opacity:0.5; cursor:not-allowed; background:#444;"{% endif %}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"></path>
                    <polyline points="10 17 15 12 10 7"></polyline>
                    <line x1="15" y1="12" x2="3" y2="12"></line>
                </svg>
                <span>Sign In</span>
            </button>
        </form>

        <div class="footer-note">
            Configure credentials in <code>config.json</code> (leave blank to disable login).
        </div>
    </div>
</body>
</html>
"""

SETUP_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Setup Required - RSS Control Panel</title>
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background: #0f1117;
            color: #e0e0e0;
            margin: 0;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .card {
            width: 100%;
            max-width: 480px;
            background: #181c24;
            border: 1px solid #28303f;
            border-radius: 12px;
            padding: 36px 30px;
            box-shadow: 0 12px 36px rgba(0,0,0,0.5);
        }
        .icon-area {
            text-align: center;
            margin-bottom: 24px;
        }
        .icon-wrap {
            width: 56px;
            height: 56px;
            border-radius: 14px;
            background: linear-gradient(135deg, #b45309 0%, #f59e0b 100%);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 14px;
            box-shadow: 0 4px 16px rgba(245,158,11,0.35);
        }
        h2 {
            margin: 0 0 6px 0;
            font-size: 1.35rem;
            color: #fff;
            font-weight: 700;
            letter-spacing: -0.3px;
            text-align: center;
        }
        .subtitle {
            margin: 0 0 28px 0;
            color: #7b879b;
            font-size: 0.88rem;
            text-align: center;
        }
        .step {
            display: flex;
            gap: 14px;
            align-items: flex-start;
            margin-bottom: 18px;
        }
        .step-num {
            flex-shrink: 0;
            width: 26px;
            height: 26px;
            border-radius: 50%;
            background: #1e2535;
            border: 1px solid #2e3a50;
            color: #7b95c4;
            font-size: 0.8rem;
            font-weight: 700;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .step-text {
            font-size: 0.9rem;
            color: #c8d0dc;
            line-height: 1.55;
            padding-top: 3px;
        }
        code {
            background: #10141d;
            border: 1px solid #222c3c;
            padding: 1px 6px;
            border-radius: 4px;
            color: #7eb8f7;
            font-size: 0.82rem;
            font-family: 'Cascadia Code', 'Fira Mono', monospace;
        }
        .code-block {
            background: #10141d;
            border: 1px solid #222c3c;
            border-radius: 8px;
            padding: 14px 16px;
            margin: 10px 0 0 0;
            font-family: 'Cascadia Code', 'Fira Mono', monospace;
            font-size: 0.82rem;
            color: #7eb8f7;
            line-height: 1.7;
            overflow-x: auto;
        }
        .divider {
            border: none;
            border-top: 1px solid #1e2535;
            margin: 24px 0;
        }
        .refresh-note {
            text-align: center;
            font-size: 0.82rem;
            color: #576479;
        }
        .refresh-note a {
            color: #4d8fd4;
            text-decoration: none;
        }
        .refresh-note a:hover {
            text-decoration: underline;
        }
    </style>
</head>
<body>
    <div class="card">
        <div class="icon-area">
            <div class="icon-wrap">
                <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="12" y1="8" x2="12" y2="12"></line>
                    <line x1="12" y1="16" x2="12.01" y2="16"></line>
                </svg>
            </div>
            <h2>Setup Required</h2>
            <p class="subtitle">No login credentials are configured yet.</p>
        </div>

        <div class="step">
            <div class="step-num">1</div>
            <div class="step-text">
                A <code>config.json</code> file has been created in the application directory.
            </div>
        </div>
        <div class="step">
            <div class="step-num">2</div>
            <div class="step-text">
                Open <code>config.json</code> and add your credentials:
                <div class="code-block">
                    &quot;auth_username&quot;: &quot;your_username&quot;,<br>
                    &quot;auth_password&quot;: &quot;your_password&quot;
                </div>
            </div>
        </div>
        <div class="step">
            <div class="step-num">3</div>
            <div class="step-text">
                Save the file, then <a href="/">click here to continue</a>. No server restart needed.
            </div>
        </div>

        <hr class="divider">
        <p class="refresh-note">
            Once credentials are saved in <code>config.json</code>, <a href="/">refresh this page</a>.
        </p>
    </div>
</body>
</html>
"""

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
        .draggable-card:hover .btn-quick-add,
        .custom-row:hover .btn-quick-add {
            opacity: 1;
        }
        .btn-quick-add:hover {
            background: #0066cc;
            border-color: #0066cc;
            color: #fff;
        }

        .btn-clear-all {
            background: #401818;
            border: 1px solid #632323;
            color: #ff9999;
            border-radius: 4px;
            padding: 4px 10px;
            font-size: 0.8rem;
            cursor: pointer;
            transition: all 0.12s ease;
            flex-shrink: 0;
            display: inline-flex;
            align-items: center;
            gap: 4px;
            font-weight: 500;
        }
        .btn-clear-all:hover {
            background: #b91c1c;
            border-color: #ef4444;
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

        .badge-source {
            font-size: 0.68rem;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 4px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            flex-shrink: 0;
        }
        .badge-source-live {
            background: rgba(56, 189, 248, 0.15);
            color: #38bdf8;
            border: 1px solid rgba(56, 189, 248, 0.35);
        }
        .badge-source-custom {
            background: rgba(192, 132, 252, 0.15);
            color: #c084fc;
            border: 1px solid rgba(192, 132, 252, 0.35);
        }
        .card-updated {
            animation: pulse-update 1.5s ease;
        }
        @keyframes pulse-update {
            0% { background: #133827; border-color: #22c55e; box-shadow: 0 0 10px rgba(34,197,94,0.5); }
            100% { background: #1b2533; border-color: #2c4159; box-shadow: none; }
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
        .ticker-track {
            flex: 1;
            overflow: hidden;
            position: relative;
            height: 100%;
            display: flex;
            align-items: center;
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
        .ticker-speed-control {
            background: #101520;
            border-left: 1px solid rgba(0, 102, 204, 0.35);
            height: 100%;
            padding: 0 18px;
            display: flex;
            align-items: center;
            gap: 10px;
            z-index: 10;
            flex-shrink: 0;
        }
        .speed-label {
            font-size: 0.78rem;
            color: #94a3b8;
            font-weight: 600;
            white-space: nowrap;
        }
        .speed-label strong {
            color: #38bdf8;
            font-variant-numeric: tabular-nums;
        }
        .ticker-speed-slider {
            -webkit-appearance: none;
            appearance: none;
            width: 100px;
            height: 6px;
            background: #1e293b;
            border-radius: 3px;
            outline: none;
            cursor: pointer;
        }
        .ticker-speed-slider::-webkit-slider-thumb {
            -webkit-appearance: none;
            appearance: none;
            width: 15px;
            height: 15px;
            border-radius: 50%;
            background: #0088ff;
            cursor: pointer;
            box-shadow: 0 0 8px rgba(0, 136, 255, 0.7);
            transition: transform 0.1s ease, background 0.15s ease;
        }
        .ticker-speed-slider::-webkit-slider-thumb:hover {
            background: #38bdf8;
            transform: scale(1.2);
        }
        .ticker-speed-slider::-moz-range-thumb {
            width: 15px;
            height: 15px;
            border-radius: 50%;
            background: #0088ff;
            cursor: pointer;
            border: none;
            box-shadow: 0 0 8px rgba(0, 136, 255, 0.7);
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
                <span class="badge-live">Live Feed</span>
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
                <a href="/" class="btn" title="Refresh Live Data" onclick="refreshLiveItems(true); return false;">
                    <svg class="icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
                    <span>Refresh Feeds</span>
                </a>
                <a href="/logout" class="btn btn-danger" style="padding: 10px 14px; font-size: 0.85rem;" title="Sign out of control panel">
                    <svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
                    <span>Logout</span>
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
                    <div style="display:flex; align-items:center; gap:8px;">
                        <button type="button" class="btn-quick-add" onclick="addAllLiveToOutput()" title="Add all live items to output" style="opacity:1; padding: 4px 10px; font-size:0.8rem;">
                            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                            <span>Add All</span>
                        </button>
                        <span class="item-count-badge" id="live-count">{{ live_items|length }} Items</span>
                    </div>
                </div>
                <form action="/save_live_link" method="POST" style="margin-bottom: 12px; display: flex; gap: 8px;">
                    <input type="url" name="live_link" class="custom-input" value="{{ live_link }}" placeholder="Enter Live XML URL..." style="font-size: 0.85rem; padding: 6px 10px;">
                    <button type="submit" class="btn" style="padding: 6px 14px; font-size: 0.82rem; white-space: nowrap;" title="Save and load XML source URL">
                        <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
                        <span>Save URL</span>
                    </button>
                </form>

                <div class="instructions-hint">
                    Drag any item box below into the <strong>Output Feed</strong> on the right.
                </div>
                
                <div class="item-list" id="live-items-list">
                    {% for item in live_items %}
                        <div class="draggable-card" 
                             draggable="true" 
                             data-source="live" 
                             data-id="{{ item.id }}"
                             data-text="{{ item.title }}"
                             ondragstart="handleSourceDragStart(event, this)">
                            <div class="card-content">
                                <span class="drag-handle" title="Drag to Output Box">
                                    <svg width="10" height="14" viewBox="0 0 10 14" fill="currentColor"><circle cx="2" cy="2" r="1.5"/><circle cx="8" cy="2" r="1.5"/><circle cx="2" cy="7" r="1.5"/><circle cx="8" cy="7" r="1.5"/><circle cx="2" cy="12" r="1.5"/><circle cx="8" cy="12" r="1.5"/></svg>
                                </span>
                                <span class="card-index">{{ loop.index }}.</span>
                                <span class="card-text">{{ item.title }}</span>
                            </div>
                            <button type="button" class="btn-quick-add" onclick="addLiveItemToOutput('{{ item.id|replace("'", "\\'") }}', '{{ item.title|replace("'", "\\'") }}')" title="Quick add to output">
                                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                                <span>Add</span>
                            </button>
                        </div>
                    {% else %}
                        <div style="padding: 20px; text-align: center; color: #666; font-style: italic;">
                            No live items currently available.
                        </div>
                    {% endfor %}
                </div>
                <p class="status-text">
                    Pulling live items dynamically from configured XML feed.
                </p>
            </div>

            <!-- Box 2: Custom Text Editor (Source 2) -->
            <div class="panel">
                <div class="panel-header">
                    <h3>
                        <svg class="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#c084fc" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                        <span>Custom Text Feed</span>
                    </h3>
                    <div style="display:flex; align-items:center; gap:8px;">
                        <button type="button" class="btn-quick-add" onclick="addAllCustomToOutput()" title="Add all custom items to output" style="opacity:1; padding: 4px 10px; font-size:0.8rem;">
                            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                            <span>Add All</span>
                        </button>
                        <span class="item-count-badge" id="custom-count">{{ custom_items|length }} Presets</span>
                    </div>
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
                                 data-custom-id="custom_{{ loop.index0 }}"
                                 data-text="{{ item }}"
                                 ondragstart="handleCustomDragStart(event, this)">
                                <span class="drag-handle" title="Drag to Output Box">
                                    <svg width="10" height="14" viewBox="0 0 10 14" fill="currentColor"><circle cx="2" cy="2" r="1.5"/><circle cx="8" cy="2" r="1.5"/><circle cx="2" cy="7" r="1.5"/><circle cx="8" cy="7" r="1.5"/><circle cx="2" cy="12" r="1.5"/><circle cx="8" cy="12" r="1.5"/></svg>
                                </span>
                                <input type="text" 
                                       name="custom_item" 
                                       class="custom-input" 
                                       value="{{ item }}" 
                                       placeholder="Custom ticker text {{ loop.index }}..."
                                       oninput="handleCustomInputChange(this)">
                                <button type="button" class="btn-quick-add" onclick="addCustomInputToOutput(this)" title="Quick add to output feed">
                                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                                    <span>Add</span>
                                </button>
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
                    <div style="display:flex; align-items:center; gap:8px;">
                        <button type="button" class="btn-clear-all" onclick="forceUpdateOutput()" title="Force save output to RSS feed now" style="background: rgba(0,102,204,0.15); border-color: #0066cc; color: #5bb8ff;">
                            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
                            <span>Force Update</span>
                        </button>
                        <button type="button" class="btn-clear-all" onclick="clearAllOutput()" title="Clear all items from output">
                            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                            <span>Clear All</span>
                        </button>
                        <span class="item-count-badge" id="output-count" style="background:#0066cc; color:#fff;">{{ output_items|length }} Active</span>
                        <span class="item-count-badge" id="save-status" style="background: transparent; color: #4ade80; font-size: 0.7rem; display: none;">✓ Saved</span>
                    </div>
                </div>
                <div class="instructions-hint">
                    Drop items here from Live Feed or Custom Text. Drag to reorder, click remove to delete. Changes auto-save.
                </div>
                
                    <div class="item-list output-drop-zone" 
                         id="output-items-container"
                         ondragover="handleOutputDragOver(event)"
                         ondragenter="handleOutputDragEnter(event)"
                         ondragleave="handleOutputDragLeave(event)"
                         ondrop="handleOutputDrop(event)">
                        
                        {% for item in output_items %}
                            <div class="output-item-card" 
                                 draggable="true" 
                                 data-source="{{ item.source }}"
                                 data-id="{{ item.id }}"
                                 data-text="{{ item.text }}"
                                 ondragstart="handleOutputItemDragStart(event, this)"
                                 ondragend="handleOutputItemDragEnd(event, this)">
                                <input type="hidden" name="output_item_data" value='{"source":"{{ item.source }}","id":"{{ item.id|replace("'", "\\'") }}","text":"{{ item.text|replace("'", "\\'") }}"}'>
                                <input type="hidden" name="output_item" value="{{ item.text }}">
                                <div class="card-content">
                                    <span class="drag-handle" title="Drag to reorder">
                                        <svg width="10" height="14" viewBox="0 0 10 14" fill="currentColor"><circle cx="2" cy="2" r="1.5"/><circle cx="8" cy="2" r="1.5"/><circle cx="2" cy="7" r="1.5"/><circle cx="8" cy="7" r="1.5"/><circle cx="2" cy="12" r="1.5"/><circle cx="8" cy="12" r="1.5"/></svg>
                                    </span>
                                    <span class="card-index">{{ loop.index }}.</span>
                                    {% if item.source == 'live' %}
                                        <span class="badge-source badge-source-live" title="Dynamically updates from live RSS feed">LIVE</span>
                                    {% else %}
                                        <span class="badge-source badge-source-custom" title="Custom static text">TEXT</span>
                                    {% endif %}
                                    <span class="card-text">{{ item.text }}</span>
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
                            <div style="font-size: 0.8rem; margin-top: 4px; color: #556677;">Drag live or custom items here to build your output feed</div>
                        </div>
                    </div>
            </div>
        </div>
    </div>

    <!-- Ticker Preview -->
    <div class="ticker-wrapper" id="broadcast-ticker" style="{% if not combined_ticker %}display: none;{% endif %}">
        <div class="ticker-label">
            ACTIVE BROADCAST
        </div>
        <div class="ticker-track">
            <div class="ticker-content">
                {{ combined_ticker }} &nbsp;&nbsp;&nbsp;&nbsp; {{ combined_ticker }}
            </div>
        </div>
        <div class="ticker-speed-control" title="Adjust ticker scrolling speed">
            <span class="speed-label">Speed: <strong id="speed-val">35s</strong></span>
            <input type="range" class="ticker-speed-slider" id="ticker-speed-slider" min="5" max="120" value="35" step="5" oninput="setTickerSpeed(this.value)">
        </div>
    </div>

    <script>
        let draggedData = null;
        let draggedElement = null;
        let isReorderingOutput = false;

        // --- Box 1: Live Feed Drag Handlers ---
        function handleSourceDragStart(e, el) {
            const text = el.getAttribute('data-text');
            const id = el.getAttribute('data-id') || '';
            draggedData = { source: 'live', id: id, text: text };
            draggedElement = el;
            isReorderingOutput = false;
            e.dataTransfer.setData('application/json', JSON.stringify(draggedData));
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
            const customId = el.getAttribute('data-custom-id') || '';
            draggedData = { source: 'custom', id: customId, text: text };
            draggedElement = el;
            isReorderingOutput = false;
            e.dataTransfer.setData('application/json', JSON.stringify(draggedData));
            e.dataTransfer.setData('text/plain', text);
            e.dataTransfer.effectAllowed = 'copy';
            el.classList.add('dragging');
            setTimeout(() => el.classList.remove('dragging'), 0);
        }

        function handleCustomInputChange(input) {
            const row = input.closest('.custom-row');
            if (!row) return;
            const customId = row.getAttribute('data-custom-id') || '';
            const newText = input.value;
            row.setAttribute('data-text', newText);

            if (customId) {
                const outputCards = document.querySelectorAll(`#output-items-container .output-item-card[data-source="custom"][data-id="${customId}"]`);
                outputCards.forEach(card => {
                    card.setAttribute('data-text', newText);
                    const textSpan = card.querySelector('.card-text');
                    if (textSpan) textSpan.textContent = newText;
                    const hiddenItem = card.querySelector('input[name="output_item"]');
                    if (hiddenItem) hiddenItem.value = newText;
                    const hiddenData = card.querySelector('input[name="output_item_data"]');
                    if (hiddenData) hiddenData.value = JSON.stringify({ source: 'custom', id: customId, text: newText });
                });
                updateTickerPreview();
                autoSaveOutput();
            }
        }

        let customIdCounter = Date.now();
        function addCustomRow() {
            const container = document.getElementById('custom-items-container');
            const count = container.querySelectorAll('.custom-row').length + 1;
            const customId = 'custom_' + (customIdCounter++);
            const div = document.createElement('div');
            div.className = 'custom-row';
            div.draggable = true;
            div.setAttribute('data-source', 'custom');
            div.setAttribute('data-custom-id', customId);
            div.setAttribute('data-text', '');
            div.ondragstart = function(e) { handleCustomDragStart(e, this); };
            div.innerHTML = `
                <span class="drag-handle" title="Drag to Output Box">
                    <svg width="10" height="14" viewBox="0 0 10 14" fill="currentColor"><circle cx="2" cy="2" r="1.5"/><circle cx="8" cy="2" r="1.5"/><circle cx="2" cy="7" r="1.5"/><circle cx="8" cy="7" r="1.5"/><circle cx="2" cy="12" r="1.5"/><circle cx="8" cy="12" r="1.5"/></svg>
                </span>
                <input type="text" name="custom_item" class="custom-input" placeholder="Custom ticker text ${count}..." oninput="handleCustomInputChange(this)">
                <button type="button" class="btn-quick-add" onclick="addCustomInputToOutput(this)" title="Quick add to output feed">
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                    <span>Add</span>
                </button>
                <button type="button" class="btn-remove" onclick="removeCustomRow(this)" title="Delete box">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
            `;
            container.appendChild(div);
            updateCustomCount();
            div.querySelector('input').focus();
        }

        function addCustomInputToOutput(btn) {
            const row = btn.closest('.custom-row');
            if (!row) return;
            const input = row.querySelector('input');
            if (!input || !input.value.trim()) return;
            const customId = row.getAttribute('data-custom-id') || '';
            addItemToOutput({ source: 'custom', id: customId, text: input.value.trim() });
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

        function addAllLiveToOutput() {
            const cards = document.querySelectorAll('#live-items-list .draggable-card');
            cards.forEach(card => {
                const id = card.getAttribute('data-id') || '';
                const text = card.getAttribute('data-text');
                if (text && text.trim()) {
                    addItemToOutput({ source: 'live', id: id, text: text.trim() });
                }
            });
        }

        function addAllCustomToOutput() {
            const rows = document.querySelectorAll('#custom-items-container .custom-row');
            rows.forEach(row => {
                const customId = row.getAttribute('data-custom-id') || '';
                const input = row.querySelector('input');
                if (input && input.value.trim()) {
                    addItemToOutput({ source: 'custom', id: customId, text: input.value.trim() });
                }
            });
        }

        // --- Box 3: Output Box Reordering & Drop Handlers ---
        function handleOutputItemDragStart(e, el) {
            draggedElement = el;
            const text = el.getAttribute('data-text') || '';
            const source = el.getAttribute('data-source') || 'custom';
            const id = el.getAttribute('data-id') || '';
            draggedData = { source: source, id: id, text: text };
            isReorderingOutput = true;
            e.dataTransfer.setData('application/json', JSON.stringify(draggedData));
            e.dataTransfer.setData('text/plain', text);
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
            
            let itemObj = null;
            try {
                const jsonStr = e.dataTransfer.getData('application/json');
                if (jsonStr) itemObj = JSON.parse(jsonStr);
            } catch(err) {}

            if (!itemObj) {
                itemObj = draggedData;
            }

            if (!itemObj) {
                const plain = e.dataTransfer.getData('text/plain');
                if (plain && plain.trim()) {
                    itemObj = { source: 'custom', id: '', text: plain.trim() };
                }
            }

            if (!itemObj || !itemObj.text || !itemObj.text.trim()) {
                cleanupDropIndicators();
                return;
            }

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
                const newCard = createOutputCard(itemObj);
                if (afterElement == null) {
                    container.appendChild(newCard);
                } else {
                    container.insertBefore(newCard, afterElement);
                }
            }

            updateOutputUI();
            updateTickerPreview();
            autoSaveOutput();
            draggedData = null;
            draggedElement = null;
            isReorderingOutput = false;
        }

        function createOutputCard(itemObj) {
            if (typeof itemObj === 'string') {
                itemObj = { source: 'custom', id: '', text: itemObj };
            }
            const source = itemObj.source || 'custom';
            const id = itemObj.id || '';
            const text = itemObj.text || '';

            const card = document.createElement('div');
            card.className = 'output-item-card';
            card.draggable = true;
            card.setAttribute('data-source', source);
            card.setAttribute('data-id', id);
            card.setAttribute('data-text', text);
            card.ondragstart = function(e) { handleOutputItemDragStart(e, this); };
            card.ondragend = function(e) { handleOutputItemDragEnd(e, this); };

            const safeText = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
            const safeDataJson = JSON.stringify({ source: source, id: id, text: text })
                .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

            const badgeHtml = source === 'live' 
                ? '<span class="badge-source badge-source-live" title="Dynamically updates from live RSS feed">LIVE</span>' 
                : '<span class="badge-source badge-source-custom" title="Custom static text">TEXT</span>';

            card.innerHTML = `
                <input type="hidden" name="output_item_data" value="${safeDataJson}">
                <input type="hidden" name="output_item" value="${safeText}">
                <div class="card-content">
                    <span class="drag-handle" title="Drag to reorder">
                        <svg width="10" height="14" viewBox="0 0 10 14" fill="currentColor"><circle cx="2" cy="2" r="1.5"/><circle cx="8" cy="2" r="1.5"/><circle cx="2" cy="7" r="1.5"/><circle cx="8" cy="7" r="1.5"/><circle cx="2" cy="12" r="1.5"/><circle cx="8" cy="12" r="1.5"/></svg>
                    </span>
                    <span class="card-index"></span>
                    ${badgeHtml}
                    <span class="card-text">${safeText}</span>
                </div>
                <button type="button" class="btn-remove" onclick="removeOutputRow(this)" title="Remove from output feed">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
            `;
            return card;
        }

        function addItemToOutput(itemObj) {
            if (!itemObj) return;
            if (typeof itemObj === 'string') itemObj = { source: 'custom', id: '', text: itemObj };
            if (!itemObj.text || !itemObj.text.trim()) return;
            const container = document.getElementById('output-items-container');
            const newCard = createOutputCard(itemObj);
            container.appendChild(newCard);
            updateOutputUI();
            updateTickerPreview();
            autoSaveOutput();
        }

        function addTextToOutput(text) {
            addItemToOutput({ source: 'custom', id: '', text: text });
        }

        function addLiveItemToOutput(id, text) {
            addItemToOutput({ source: 'live', id: id, text: text });
        }

        function removeOutputRow(btn) {
            const card = btn.closest('.output-item-card');
            if (card) {
                card.remove();
                updateOutputUI();
                updateTickerPreview();
                autoSaveOutput();
            }
        }

        function clearAllOutput() {
            const container = document.getElementById('output-items-container');
            const cards = container.querySelectorAll('.output-item-card');
            cards.forEach(card => card.remove());
            updateOutputUI();
            updateTickerPreview();
            autoSaveOutput();
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

        function updateTickerPreview() {
            const cards = document.querySelectorAll('#output-items-container .output-item-card');
            const items = [];
            cards.forEach(card => {
                const t = card.getAttribute('data-text');
                if (t && t.trim()) items.push(t.trim());
            });
            const combined = items.join('  |  ');
            const tickerWrapper = document.getElementById('broadcast-ticker');
            const tickerContent = document.querySelector('.ticker-content');
            if (tickerContent) {
                tickerContent.textContent = combined ? `${combined}     ${combined}` : '';
            }
            if (tickerWrapper) {
                tickerWrapper.style.display = combined ? 'flex' : 'none';
            }
        }

        function setTickerSpeed(val) {
            const tickerContent = document.querySelector('.ticker-content');
            const valDisplay = document.getElementById('speed-val');
            if (valDisplay) valDisplay.textContent = val + 's';
            if (tickerContent) {
                tickerContent.style.animationDuration = val + 's';
            }
            try {
                localStorage.setItem('ticker_speed', val);
            } catch(e) {}
        }

        // --- Auto-save output to server ---
        let saveTimeout = null;
        let isSaving = false;
        function autoSaveOutput() {
            if (saveTimeout) clearTimeout(saveTimeout);
            saveTimeout = setTimeout(doSaveOutput, 400);
        }

        function forceUpdateOutput() {
            if (saveTimeout) clearTimeout(saveTimeout);
            doSaveOutput();
        }

        async function doSaveOutput() {
            if (isSaving) return;
            isSaving = true;
            const cards = document.querySelectorAll('#output-items-container .output-item-card');
            const items = [];
            cards.forEach(card => {
                const source = card.getAttribute('data-source') || 'custom';
                const id = card.getAttribute('data-id') || '';
                const text = card.getAttribute('data-text') || '';
                if (text.trim()) {
                    items.push({ source: source, id: id, text: text.trim() });
                }
            });
            try {
                const res = await fetch('/api/save_output', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ items: items })
                });
                if (res.ok) {
                    const statusEl = document.getElementById('save-status');
                    if (statusEl) {
                        statusEl.style.display = 'inline';
                        statusEl.textContent = '✓ Saved';
                        setTimeout(() => { statusEl.style.display = 'none'; }, 2000);
                    }
                }
            } catch (err) {
                console.error('Auto-save failed:', err);
            } finally {
                isSaving = false;
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

        function createLiveCard(item, index) {
            const text = typeof item === 'object' ? item.title : item;
            const id = typeof item === 'object' ? (item.id || '') : '';

            const card = document.createElement('div');
            card.className = 'draggable-card';
            card.draggable = true;
            card.setAttribute('data-source', 'live');
            card.setAttribute('data-id', id);
            card.setAttribute('data-text', text);
            card.ondragstart = function(e) { handleSourceDragStart(e, this); };

            const cardContent = document.createElement('div');
            cardContent.className = 'card-content';

            const dragHandle = document.createElement('span');
            dragHandle.className = 'drag-handle';
            dragHandle.title = 'Drag to Output Box';
            dragHandle.innerHTML = '<svg width="10" height="14" viewBox="0 0 10 14" fill="currentColor"><circle cx="2" cy="2" r="1.5"/><circle cx="8" cy="2" r="1.5"/><circle cx="2" cy="7" r="1.5"/><circle cx="8" cy="7" r="1.5"/><circle cx="2" cy="12" r="1.5"/><circle cx="8" cy="12" r="1.5"/></svg>';

            const indexSpan = document.createElement('span');
            indexSpan.className = 'card-index';
            indexSpan.textContent = `${index + 1}.`;

            const textSpan = document.createElement('span');
            textSpan.className = 'card-text';
            textSpan.textContent = text;

            cardContent.appendChild(dragHandle);
            cardContent.appendChild(indexSpan);
            cardContent.appendChild(textSpan);

            const addBtn = document.createElement('button');
            addBtn.type = 'button';
            addBtn.className = 'btn-quick-add';
            addBtn.title = 'Quick add to output';
            addBtn.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg><span>Add</span>';
            addBtn.onclick = function() { addItemToOutput({ source: 'live', id: id, text: text }); };

            card.appendChild(cardContent);
            card.appendChild(addBtn);
            return card;
        }

        function renderLiveItems(items) {
            const list = document.getElementById('live-items-list');
            const badge = document.getElementById('live-count');
            if (!list) return;

            if (badge) {
                badge.textContent = `${items.length} Items`;
            }

            list.innerHTML = '';
            if (!items || items.length === 0) {
                const emptyDiv = document.createElement('div');
                emptyDiv.style.cssText = 'padding: 20px; text-align: center; color: #666; font-style: italic;';
                emptyDiv.textContent = 'No live items currently available.';
                list.appendChild(emptyDiv);
                return;
            }

            items.forEach((item, index) => {
                list.appendChild(createLiveCard(item, index));
            });
        }

        function updateLiveOutputCards(itemsById) {
            if (!itemsById) return;
            const cards = document.querySelectorAll('#output-items-container .output-item-card');
            let anyChanged = false;

            cards.forEach(card => {
                const source = card.getAttribute('data-source');
                let id = card.getAttribute('data-id');
                const currentText = card.getAttribute('data-text') || '';

                if (!id || source !== 'live') {
                    for (const [liveId, liveTitle] of Object.entries(itemsById)) {
                        const parts = liveId.split('|');
                        if ((parts.length === 2 && currentText.includes(parts[0]) && currentText.includes(parts[1])) ||
                            currentText === liveTitle || currentText.includes(liveTitle) || liveTitle.includes(currentText)) {
                            id = liveId;
                            source = 'live';
                            card.setAttribute('data-id', id);
                            card.setAttribute('data-source', 'live');
                            let badge = card.querySelector('.badge-source');
                            if (badge) {
                                badge.className = 'badge-source badge-source-live';
                                badge.textContent = 'LIVE';
                                badge.title = 'Dynamically updates from live RSS feed';
                            }
                            break;
                        }
                    }
                }

                if (source === 'live' && id && itemsById[id]) {
                    const newTitle = itemsById[id];
                    if (newTitle !== currentText) {
                        card.setAttribute('data-text', newTitle);
                        const textSpan = card.querySelector('.card-text');
                        if (textSpan) textSpan.textContent = newTitle;
                        
                        const hiddenData = card.querySelector('input[name="output_item_data"]');
                        if (hiddenData) {
                            hiddenData.value = JSON.stringify({ source: 'live', id: id, text: newTitle });
                        }
                        const hiddenItem = card.querySelector('input[name="output_item"]');
                        if (hiddenItem) {
                            hiddenItem.value = newTitle;
                        }

                        card.classList.remove('card-updated');
                        void card.offsetWidth;
                        card.classList.add('card-updated');
                        anyChanged = true;
                    }
                }
            });

            if (anyChanged) {
                updateTickerPreview();
                autoSaveOutput();
            }
        }

        let isFetchingLive = false;
        async function refreshLiveItems(isManual = false) {
            if (isFetchingLive) return;
            isFetchingLive = true;
            try {
                const res = await fetch('/api/live_items');
                if (!res.ok) return;
                const data = await res.json();
                if (data && Array.isArray(data.live_items)) {
                    renderLiveItems(data.live_items);
                }
                if (data && data.items_by_id) {
                    updateLiveOutputCards(data.items_by_id);
                }
            } catch (err) {
                console.error('Error refreshing live items:', err);
            } finally {
                isFetchingLive = false;
            }
        }

        // Initialize UI numbers on page load and start 15s auto-refresh
        document.addEventListener('DOMContentLoaded', () => {
            updateOutputUI();
            updateCustomCount();

            // Restore saved ticker speed
            try {
                const savedSpeed = localStorage.getItem('ticker_speed') || '35';
                const slider = document.getElementById('ticker-speed-slider');
                if (slider) slider.value = savedSpeed;
                setTickerSpeed(savedSpeed);
            } catch(e) {}

            // Automatically refresh live feed data every 15 seconds
            setInterval(refreshLiveItems, 15000);
        });
    </script>
</body>
</html>
"""

def fetch_live_data(live_link):
    """Fetches and parses live items and returns structured entries and items_by_id map."""
    items = []
    items_by_id = {}
    error = None
    if not live_link or not live_link.strip():
        return items, items_by_id, error

    try:
        req_live = urllib.request.Request(live_link.strip(), headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req_live, timeout=5) as resp_live:
            raw_xml_live = resp_live.read()
            
        root_live = ET.fromstring(raw_xml_live)
        
        # 1. RSS items or Atom entries
        xml_items = root_live.findall('.//item') or root_live.findall('.//entry')
        if xml_items:
            for idx, it in enumerate(xml_items):
                title_el = it.find('title')
                if title_el is not None and title_el.text:
                    title_str = title_el.text.strip()
                    guid_el = it.find('guid')
                    link_el = it.find('link')
                    item_id = (guid_el.text.strip() if guid_el is not None and guid_el.text else None) or \
                              (link_el.text.strip() if link_el is not None and link_el.text else None) or \
                              f"item_{idx}"
                    entry = {'id': item_id, 'title': title_str, 'source': 'live'}
                    items.append(entry)
                    items_by_id[item_id] = title_str
        # 2. Scoreboard <game> elements
        elif root_live.findall('game') or root_live.findall('.//game'):
            games = root_live.findall('game') or root_live.findall('.//game')
            for idx, game in enumerate(games):
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

                # Key game by away|home to track live updates consistently across score changes
                game_id = f"{away_name}|{home_name}"
                entry = {'id': game_id, 'title': title_str, 'source': 'live'}
                items.append(entry)
                items_by_id[game_id] = title_str
        # 3. Generic element text parsing
        else:
            for idx, child in enumerate(root_live):
                text = (child.text or '').strip()
                if text:
                    item_id = f"node_{idx}"
                    entry = {'id': item_id, 'title': text, 'source': 'live'}
                    items.append(entry)
                    items_by_id[item_id] = text

    except Exception as e:
        error = f"Error fetching live XML: {str(e)}"

    return items, items_by_id, error

@app.route('/api/live_items')
def api_live_items():
    config = get_config()
    live_link = config.get("live_link") or DEFAULT_LIVE_LINK
    live_items, items_by_id, error = fetch_live_data(live_link)
    activity_log.log_live_items_change([it['title'] for it in live_items])
    return jsonify({
        "live_items": live_items,
        "items_by_id": items_by_id,
        "error": error,
        "count": len(live_items)
    })

@app.route('/')
def index():
    config = get_config()
    custom_items = config.get("custom_items", [])
    raw_output_items = config.get("output_items")
    live_link = config.get("live_link") or DEFAULT_LIVE_LINK
    
    if raw_output_items is None:
        raw_output_items = list(custom_items) if custom_items else []
    
    if not custom_items:
        custom_items = [""]

    # Fetch The Raw Source XML if a link is provided
    live_items, items_by_id, error = fetch_live_data(live_link)

    # Log the live feed content the first time it's fetched and whenever it changes.
    activity_log.log_live_items_change([it['title'] for it in live_items])

    output_items = resolve_output_items(raw_output_items, live_items, items_by_id)
    combined_ticker = ticker_text(output_items)

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
    old_url = config.get('live_link', '')
    new_url = request.form.get('live_link', '').strip()
    config['live_link'] = new_url
    save_config(config)
    # Log the XML feed URL change: records old URL > new URL
    activity_log.log_xml_change(old_url, new_url)
    return redirect(url_for('index'))

@app.route('/toggle_spacer', methods=['POST'])
def toggle_spacer():
    config = get_config()
    config['enable_spacer'] = not config.get('enable_spacer', True)
    save_config(config)
    return redirect(url_for('index'))

@app.route('/api/save_output', methods=['POST'])
def api_save_output():
    """JSON endpoint: auto-save output items from the client."""
    data = request.get_json(silent=True) or {}
    raw_items = data.get('items', [])

    cleaned_items = []
    log_text_items = []
    for it in raw_items:
        if isinstance(it, dict) and it.get('text', '').strip():
            cleaned_items.append({
                "source": it.get("source", "custom"),
                "id": it.get("id", ""),
                "text": it.get("text", "").strip()
            })
            log_text_items.append(it["text"].strip())
        elif isinstance(it, str) and it.strip():
            cleaned_items.append({"source": "custom", "id": "", "text": it.strip()})
            log_text_items.append(it.strip())

    config = get_config()
    config['output_items'] = cleaned_items
    save_config(config)
    activity_log.log_feed_change(log_text_items)
    ticker_watcher.notify_change()
    return jsonify({"ok": True, "count": len(cleaned_items)})

@app.route('/save_custom', methods=['POST'])
def save_custom():
    config = get_config()
    submitted_items = request.form.getlist('custom_item')
    
    # Strip whitespace and omit completely blank entries
    cleaned_items = [item.strip() for item in submitted_items if item.strip()]
    
    config['custom_items'] = cleaned_items if cleaned_items else [""]
    save_config(config)
    # Log the custom text change: records every item currently in the static list
    activity_log.log_txt_change(cleaned_items)
    ticker_watcher.notify_change()
    return redirect(url_for('index'))

# ==============================================================================
# PROPRESENTER INTEGRATION ROUTES
# ==============================================================================
@app.route('/api/propresenter/status')
def api_propresenter_status():
    settings = get_propresenter_settings(get_config())
    return jsonify({
        "settings": settings,
        "last_trigger_at": ticker_watcher.last_status["last_trigger_at"],
        "last_error": ticker_watcher.last_status["last_error"],
    })


@app.route('/api/propresenter/settings', methods=['POST'])
def api_propresenter_settings():
    data = request.get_json(silent=True) or {}
    config = get_config()
    current = get_propresenter_settings(config)
    merged = dict(current)
    for key in PROPRESENTER_DEFAULTS:
        if key in data:
            merged[key] = data[key]
    settings = get_propresenter_settings({"propresenter": merged})
    config["propresenter"] = settings
    save_config(config)
    activity_log.log_propresenter("settings saved: host={} port={} prop={} enabled={} mode={} fade={}s".format(
        settings["host"], settings["port"], settings["prop_name"] or settings["prop_id"],
        settings["enabled"], settings["refresh_mode"], settings["fade_seconds"]))
    return jsonify({"ok": True, "settings": settings})


@app.route('/api/propresenter/props')
def api_propresenter_props():
    saved = get_propresenter_settings(get_config())
    host = (request.args.get('host') or saved["host"]).strip()
    port = request.args.get('port') or saved["port"]
    try:
        props = propresenter.list_props(host, port)
    except propresenter.ProPresenterError as e:
        return jsonify({"ok": False, "error": str(e)}), 502
    return jsonify({"ok": True, "props": props})


@app.route('/api/propresenter/trigger', methods=['POST'])
def api_propresenter_trigger():
    """Manual 'Trigger Now'. Optional JSON body {"refresh_mode": ..., "fade_seconds": ...}
    overrides the saved mode for this one press so the three modes can be compared
    live without saving each time."""
    settings = get_propresenter_settings(get_config())
    override = request.get_json(silent=True) or {}
    if override:
        merged = dict(settings)
        for key in ("refresh_mode", "fade_seconds"):
            if key in override:
                merged[key] = override[key]
        settings = get_propresenter_settings({"propresenter": merged})
    prop = settings["prop_id"] or settings["prop_name"]
    if not prop:
        return jsonify({"ok": False, "error": "No prop selected. Use Test Connection and pick the ticker prop."}), 502
    try:
        propresenter.trigger_prop(settings["host"], settings["port"], prop,
                                  mode=settings["refresh_mode"], fade_seconds=settings["fade_seconds"])
    except propresenter.ProPresenterError as e:
        ticker_watcher.last_status["last_error"] = str(e)
        activity_log.log_propresenter("manual trigger FAILED ({}): {}".format(settings["refresh_mode"], e))
        return jsonify({"ok": False, "error": str(e)}), 502
    ticker_watcher.last_status["last_trigger_at"] = time.time()
    ticker_watcher.last_status["last_error"] = ""
    activity_log.log_propresenter("manual trigger of prop {} via {}".format(
        settings["prop_name"] or prop, settings["refresh_mode"]))
    return jsonify({"ok": True, "refresh_mode": settings["refresh_mode"]})


# ==============================================================================
# RATE LIMITING & LOGIN LOCKOUT
# (5 failed attempts within a 5-minute sliding window triggers a 5-minute lockout)
# ==============================================================================
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_WINDOW_SECONDS = 300      # 5 minutes
LOCKOUT_DURATION_SECONDS = 300    # 5 minutes
failed_login_attempts = {}

def get_client_ip():
    """Extracts client IP address, checking X-Forwarded-For if behind a proxy/Docker."""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr or '127.0.0.1'

def check_ip_lockout(ip):
    """Returns remaining lockout seconds if the IP is currently locked out, else 0."""
    now = time.time()
    record = failed_login_attempts.get(ip)
    if not record:
        return 0
    
    # Active lockout check
    if record.get('lockout_until', 0) > now:
        return int(record['lockout_until'] - now) + 1
    
    # If lockout expired, reset
    if record.get('lockout_until', 0) > 0 and record.get('lockout_until', 0) <= now:
        record['lockout_until'] = 0
        record['attempts'] = []
        return 0
        
    # Prune attempts older than the 5-minute window
    record['attempts'] = [t for t in record.get('attempts', []) if now - t < LOCKOUT_WINDOW_SECONDS]
    return 0

def record_failed_attempt(ip):
    """Records a failed attempt timestamp for the IP. Triggers lockout if 5 attempts reached."""
    now = time.time()
    if ip not in failed_login_attempts:
        failed_login_attempts[ip] = {'attempts': [], 'lockout_until': 0}
    
    record = failed_login_attempts[ip]
    record['attempts'] = [t for t in record.get('attempts', []) if now - t < LOCKOUT_WINDOW_SECONDS]
    record['attempts'].append(now)
    
    if len(record['attempts']) >= MAX_FAILED_ATTEMPTS:
        record['lockout_until'] = now + LOCKOUT_DURATION_SECONDS
        return LOCKOUT_DURATION_SECONDS
    return 0

def clear_failed_attempts(ip):
    """Clears attempt record upon successful authentication."""
    failed_login_attempts.pop(ip, None)

@app.before_request
def require_login():
    config = get_config()
    required_user = str(config.get("auth_username", "")).strip()
    required_pass = str(config.get("auth_password", "")).strip()
    credentials_set = bool(required_user and required_pass)

    # Block all routes except /setup and static files when credentials are not configured.
    if not credentials_set:
        if request.endpoint not in ('setup', 'static'):
            return redirect(url_for('setup'))
    else:
        # Credentials are configured — require login for all routes except login/static.
        if request.endpoint not in ('login', 'static') and not session.get('logged_in'):
            return redirect(url_for('login'))

@app.route('/setup')
def setup():
    """Shown when config.json has no credentials set. Instructs user to add them."""
    config = get_config()
    required_user = str(config.get("auth_username", "")).strip()
    required_pass = str(config.get("auth_password", "")).strip()
    # If credentials have been added since the page was last loaded, go to login.
    if required_user and required_pass:
        return redirect(url_for('login'))
    return render_template_string(SETUP_TEMPLATE)

@app.route('/login', methods=['GET', 'POST'])
def login():
    config = get_config()
    required_user = str(config.get("auth_username", "")).strip()
    required_pass = str(config.get("auth_password", "")).strip()

    # If credentials are still not set, send back to setup page.
    if not required_user or not required_pass:
        return redirect(url_for('setup'))

    ip = get_client_ip()
    lockout_remaining = check_ip_lockout(ip)
    
    if lockout_remaining > 0:
        mins = (lockout_remaining + 59) // 60
        error = f"Too many failed login attempts. Access temporarily locked for {mins} minute{'s' if mins != 1 else ''} ({lockout_remaining}s remaining)."
        return render_template_string(LOGIN_TEMPLATE, error=error, is_locked=True)
        
    error = None
    if request.method == 'POST':
        user = request.form.get('username', '').strip()
        pwd = request.form.get('password', '')
        
        if user == required_user and pwd == required_pass:
            clear_failed_attempts(ip)
            session['logged_in'] = True
            # Log successful login
            activity_log.log_login(user, ip, success=True)
            return redirect(url_for('index'))
        else:
            lockout_time = record_failed_attempt(ip)
            # Log failed login attempt
            activity_log.log_login(user, ip, success=False)
            if lockout_time > 0:
                error = "Too many failed attempts (5 attempts in 5 minutes). You are locked out for 5 minutes."
                return render_template_string(LOGIN_TEMPLATE, error=error, is_locked=True)
            else:
                attempts_done = len(failed_login_attempts[ip]['attempts'])
                attempts_left = MAX_FAILED_ATTEMPTS - attempts_done
                error = f"Invalid username or password. ({attempts_left} attempt{'s' if attempts_left != 1 else ''} remaining before 5-minute lockout)"
            
    return render_template_string(LOGIN_TEMPLATE, error=error, is_locked=False)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    ticker_watcher.start()
    app.run(host='0.0.0.0', port=5001)