import os
import secrets
import json
import time
import threading
import xml.etree.ElementTree as ET
import urllib.request
# pyrefly: ignore [missing-import]
from flask import Flask, Response, render_template_string, request, redirect, url_for, session, jsonify
import logger as activity_log
import feed_log
from output_resolver import build_output_items, ticker_settings, ticker_text
import propresenter
from watcher import TickerWatcher

app = Flask(__name__)
# Same config.json as app.py: next to the code, not the current directory.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.environ.get('RSS_CONFIG_FILE') or os.path.join(BASE_DIR, 'config.json')
def load_secret_key():
    """
    The key that signs login cookies. Uses SECRET_KEY when it is set and not
    blank. Otherwise generates a random key once and keeps it in a
    .secret_key file next to config.json, so logins work with no setup and
    survive restarts. (An empty key makes Flask fail every login with a 500.)
    """
    key = os.environ.get('SECRET_KEY', '').strip()
    if key:
        return key
    key_file = os.path.join(os.path.dirname(os.path.abspath(CONFIG_FILE)), '.secret_key')
    try:
        with open(key_file, 'r', encoding='utf-8') as f:
            key = f.read().strip()
        if key:
            return key
    except OSError:
        pass
    key = secrets.token_hex(32)
    try:
        with open(key_file, 'w', encoding='utf-8') as f:
            f.write(key)
    except OSError:
        pass  # read-only folder: the key still works until the next restart
    return key


app.secret_key = load_secret_key()
GUI_HOST = os.environ.get('GUI_HOST', '0.0.0.0')
GUI_PORT = int(os.environ.get('GUI_PORT', '5001'))
DEFAULT_LIVE_LINK = os.environ.get('XML_URL', '')
config_lock = threading.Lock()

# ==============================================================================
# DEFAULT CONFIGURATION
# - live_link: XML/RSS source link. Leave empty ("") if using custom text items only.
# - live_enabled: When on, every item from the live XML feed goes on air
#   automatically, in feed order. Off = only custom boxes go on air.
# - custom_items: Custom text boxes, [{"text": str, "enabled": bool}]. Boxes
#   that are switched on are shown after the live feed, top to bottom.
# - output_items: The computed ticker (live items, then enabled custom boxes)
#   that app.py serves at /rss. Rebuilt by this app; never edited by hand.
# - enable_spacer: Appends a blank item to the RSS feed for smooth ticker looping.
# - auth_username & auth_password: These are NOT included in the defaults.
#   They can ONLY be set by manually editing config.json.
#   The app will NEVER write or overwrite these fields — they are read-only from
#   the app's perspective. Setting either to "" (or omitting them) disables login.
# ==============================================================================
DEFAULT_CONFIG = {
    "live_link": DEFAULT_LIVE_LINK,
    "live_enabled": True,
    "enable_spacer": True,
    "custom_items": [],
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


def get_auth_credentials(config):
    """
    (username, password) for the control panel. config.json wins; otherwise the
    AUTH_USERNAME / AUTH_PASSWORD environment variables (handy in Docker/Portainer).
    """
    user = str(config.get("auth_username", "") or "").strip()
    password = str(config.get("auth_password", "") or "").strip()
    if user and password:
        return user, password
    return (os.environ.get("AUTH_USERNAME", "").strip(),
            os.environ.get("AUTH_PASSWORD", "").strip())


# Auth fields are never written by the app — only by the user editing config.json directly.
_AUTH_KEYS = {"auth_username", "auth_password"}

def _feed_texts(output_items):
    """The non-blank item texts /rss serves, in order (what the feed log records)."""
    texts = []
    for it in output_items or []:
        text = it.get("text", "") if isinstance(it, dict) else str(it)
        if str(text).strip():
            texts.append(str(text).strip())
    return texts


def save_config(config):
    """Saves config to disk. Auth fields are always stripped from what gets written
    and re-read from the existing file so the app can never change them."""
    with config_lock:
        # Pull current auth off disk (if any) so they survive the write.
        preserved = {}
        previous_output = None
        try:
            with open(CONFIG_FILE, 'r') as f:
                on_disk = json.load(f)
            preserved = {k: on_disk[k] for k in _AUTH_KEYS if k in on_disk}
            previous_output = on_disk.get("output_items")
        except (FileNotFoundError, json.JSONDecodeError, OSError, AttributeError):
            pass

        # Strip auth from whatever was passed in, then put disk values back.
        out = {k: v for k, v in config.items() if k not in _AUTH_KEYS}
        out.update(preserved)

        with open(CONFIG_FILE, 'w') as f:
            json.dump(out, f, indent=2)

        # Every write of new ticker content goes through here (routes, the
        # background refresh and the watcher), so this is where /rss changes.
        new_texts = _feed_texts(out.get("output_items"))
        if new_texts != _feed_texts(previous_output):
            feed_log.record(feed_log.log_path(CONFIG_FILE), new_texts)

def get_config():
    with config_lock:
        if not os.path.exists(CONFIG_FILE):
            cfg = DEFAULT_CONFIG.copy()
            try:
                out = {k: v for k, v in cfg.items() if k not in _AUTH_KEYS}
                with open(CONFIG_FILE, 'w') as f:
                    json.dump(out, f, indent=2)
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
                out = {k: v for k, v in cfg.items() if k not in _AUTH_KEYS}
                with open(CONFIG_FILE, 'w') as f:
                    json.dump(out, f, indent=2)
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
            Running in Docker or Portainer? Set the <code>AUTH_USERNAME</code> and <code>AUTH_PASSWORD</code>
            environment variables on the stack and redeploy instead.
        </p>
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
        
        /* Auto-Refresh Status & Animations */
        .cycle-pulse-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background-color: #22c55e;
            box-shadow: 0 0 8px #22c55e;
            display: inline-block;
            flex-shrink: 0;
            animation: pulse-dot-anim 1.8s infinite;
        }
        .cycle-pulse-dot.error {
            background-color: #ef4444;
            box-shadow: 0 0 8px #ef4444;
            animation: none;
        }
        @keyframes pulse-dot-anim {
            0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.7); }
            70% { transform: scale(1.15); box-shadow: 0 0 0 6px rgba(34, 197, 94, 0); }
            100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(34, 197, 94, 0); }
        }
        .spin {
            animation: spin-anim 0.7s linear infinite;
        }
        @keyframes spin-anim {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }
        
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
        /* ProPresenter integration card */
        .pp-card { background: #1b1b1b; border: 1px solid #2e2e2e; border-radius: 8px; padding: 12px; margin-bottom: 12px; }
        .pp-card-title { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; font-size: 0.9rem; font-weight: 600; color: #fff; }
        .pp-row { display: flex; gap: 8px; margin-bottom: 8px; align-items: center; }
        .pp-row .custom-input { font-size: 0.85rem; padding: 6px 10px; }
        .pp-row select.custom-input { flex: 1; min-width: 0; }
        .pp-port { max-width: 90px; }
        .pp-toggles { display: flex; gap: 14px; font-size: 0.8rem; color: #bdbdbd; margin-bottom: 8px; }
        .pp-toggles label { display: inline-flex; align-items: center; gap: 6px; cursor: pointer; }
        .pp-modes { display: flex; flex-direction: column; gap: 6px; margin-bottom: 10px; }
        .pp-mode { display: flex; align-items: center; gap: 8px; font-size: 0.8rem; color: #bdbdbd; padding: 6px 8px; border: 1px solid #2e2e2e; border-radius: 6px; cursor: pointer; }
        .pp-mode:has(input:checked) { border-color: #0066cc; background: rgba(0,102,204,0.12); color: #fff; }
        .pp-mode small { color: #8a8a8a; margin-left: auto; }
        .pp-fade { width: 64px; font-size: 0.8rem; padding: 3px 6px; }
        .pp-status { font-size: 0.75rem; min-height: 1.1em; color: #9a9a9a; }
        .pp-status.ok { color: #4ade80; }
        .pp-status.err { color: #f87171; }
        .btn-sm { padding: 6px 12px; font-size: 0.8rem; white-space: nowrap; }

        /* ---- On/off switches ---- */
        .switch { display: inline-flex; align-items: center; gap: 8px; cursor: pointer; flex-shrink: 0; user-select: none; }
        .switch input { position: absolute; opacity: 0; width: 0; height: 0; }
        .switch-track { position: relative; width: 36px; height: 20px; background: #3a3a3a; border: 1px solid #4a4a4a; border-radius: 999px; transition: background 0.15s ease, border-color 0.15s ease; }
        .switch-thumb { position: absolute; top: 2px; left: 2px; width: 14px; height: 14px; background: #bbb; border-radius: 50%; transition: transform 0.15s ease, background 0.15s ease; }
        .switch input:checked + .switch-track { background: #1b6329; border-color: #2b8a3e; }
        .switch input:checked + .switch-track .switch-thumb { transform: translateX(16px); background: #fff; }
        .switch input:focus-visible + .switch-track { outline: 2px solid #0088ff; outline-offset: 2px; }
        .switch-lg .switch-track { width: 44px; height: 24px; }
        .switch-lg .switch-thumb { width: 18px; height: 18px; }
        .switch-lg input:checked + .switch-track .switch-thumb { transform: translateX(20px); }
        .switch-label { font-size: 0.72rem; font-weight: 700; letter-spacing: 0.5px; color: #888; min-width: 48px; }
        .switch input:checked ~ .switch-label { color: #4ade80; }

        /* ---- Live feed panel ---- */
        .live-card { display: flex; align-items: center; gap: 10px; background: #1b2533; border: 1px solid #2c4159; border-radius: 5px; padding: 10px 12px; }
        #live-panel.is-off .live-card { opacity: 0.4; background: #222; border-color: #333; }
        #live-panel.is-off .live-card .card-text { text-decoration: line-through; }
        .off-notice { background: #2a2210; border: 1px solid #6b5416; color: #f5d27a; padding: 10px 12px; border-radius: 6px; font-size: 0.85rem; margin-bottom: 12px; }
        .list-empty { padding: 20px; text-align: center; color: #666; font-style: italic; }

        /* ---- Custom boxes ---- */
        .custom-row.is-off .custom-text { opacity: 0.45; }
        .row-move { display: flex; flex-direction: column; gap: 2px; flex-shrink: 0; }
        .btn-move { background: #2a2a2a; border: 1px solid #3a3a3a; color: #aaa; font-size: 0.55rem; line-height: 1; padding: 2px 6px; border-radius: 3px; cursor: pointer; }
        .btn-move:hover { background: #333; color: #fff; }
        .output-item-card { cursor: default; }
        .output-item-card:active { cursor: default; }
        .grid > .panel { min-width: 0; }
        @media (max-width: 1100px) { .grid { grid-template-columns: 1fr; } }
        @media (max-width: 700px) {
            .header { flex-wrap: wrap; gap: 12px; }
            .controls { flex-wrap: wrap; }
            .panel-header { flex-wrap: wrap; gap: 8px; }
            .ticker-speed-control { display: none; }
        }
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
                <button type="button" class="btn" id="btn-restart-cycle" title="Auto-refreshing in background every 15s. Click to restart/force cycle immediately." onclick="restartRefreshCycle();" style="display: inline-flex; align-items: center; gap: 8px;">
                    <span class="cycle-pulse-dot" id="cycle-pulse-dot" title="Background Auto-Refresh Active"></span>
                    <svg class="icon" id="cycle-refresh-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
                    <span id="cycle-status-text">Restart Cycle</span>
                </button>
                <a href="/feed-log" target="_blank" class="btn" title="Text history of every feed update (last 30 days)">
                    <svg class="icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="16" y2="17"/></svg>
                    <span>Feed Log</span>
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
            <!-- Panel 1: Live XML feed. Every item goes on air automatically, first. -->
            <div class="panel{% if not live_enabled %} is-off{% endif %}" id="live-panel">
                <div class="panel-header">
                    <h3>
                        <svg class="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4.9 19.1C1 15.2 1 8.8 4.9 4.9"/><path d="M7.8 16.2c-2.3-2.3-2.3-6.1 0-8.5"/><circle cx="12" cy="12" r="2"/><path d="M16.2 7.8c2.3 2.3 2.3 6.1 0 8.5"/><path d="M19.1 4.9C23 8.8 23 15.2 19.1 19.1"/></svg>
                        <span>Live XML Feed</span>
                    </h3>
                    <div style="display:flex; align-items:center; gap:10px;">
                        <span class="item-count-badge" id="live-count">{{ live_items|length }} Items</span>
                        <label class="switch switch-lg" title="Turn the live XML feed on or off air">
                            <input type="checkbox" id="live-enabled-toggle" {% if live_enabled %}checked{% endif %} onchange="setLiveEnabled(this.checked)">
                            <span class="switch-track"><span class="switch-thumb"></span></span>
                            <span class="switch-label" id="live-enabled-label">{% if live_enabled %}ON AIR{% else %}OFF{% endif %}</span>
                        </label>
                    </div>
                </div>
                <form action="/save_live_link" method="POST" style="margin-bottom: 12px; display: flex; gap: 8px;">
                    <input type="url" name="live_link" class="custom-input" value="{{ live_link }}" placeholder="Enter Live XML URL..." style="font-size: 0.85rem; padding: 6px 10px;">
                    <button type="submit" class="btn" style="padding: 6px 14px; font-size: 0.82rem; white-space: nowrap;" title="Save and load XML source URL">
                        <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
                        <span>Save URL</span>
                    </button>
                </form>

                <div class="instructions-hint" id="live-hint-on" {% if not live_enabled %}style="display:none;"{% endif %}>
                    Every item from this feed is on air automatically, in feed order, and refreshes every 15 seconds.
                </div>
                <div class="off-notice" id="live-hint-off" {% if live_enabled %}style="display:none;"{% endif %}>
                    The XML feed is <strong>off air</strong>. Only custom boxes that are switched on are in the ticker.
                </div>

                <div class="item-list" id="live-items-list">
                    {% for item in live_items %}
                        <div class="live-card">
                            <span class="card-index">{{ loop.index }}.</span>
                            <span class="card-text">{{ item.title }}</span>
                        </div>
                    {% else %}
                        <div class="list-empty">No live items currently available.</div>
                    {% endfor %}
                </div>
            </div>

            <!-- Panel 2: Custom boxes. Switched-on boxes go on air after the feed. -->
            <div class="panel" id="custom-panel">
                <div class="panel-header">
                    <h3>
                        <svg class="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#c084fc" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                        <span>Custom Boxes</span>
                    </h3>
                    <div style="display:flex; align-items:center; gap:8px;">
                        <span class="item-count-badge" id="save-status" style="background: transparent; color: #4ade80; font-size: 0.7rem; display: none;">✓ Saved</span>
                        <span class="item-count-badge" id="custom-count">0 On</span>
                    </div>
                </div>
                <div class="instructions-hint">
                    Shown <strong>after the live feed</strong>, top to bottom. Switch a box on to put it on air. Changes save automatically.
                </div>

                <div class="item-list" id="custom-items-container">
                    {% for item in custom_items %}
                        <div class="custom-row{% if not item.enabled %} is-off{% endif %}">
                            <label class="switch" title="Put this box on or off air">
                                <input type="checkbox" class="custom-enabled" {% if item.enabled %}checked{% endif %}>
                                <span class="switch-track"><span class="switch-thumb"></span></span>
                            </label>
                            <input type="text" class="custom-input custom-text" value="{{ item.text }}" placeholder="Custom ticker text..." maxlength="500">
                            <div class="row-move">
                                <button type="button" class="btn-move" data-dir="-1" title="Move up">&#9650;</button>
                                <button type="button" class="btn-move" data-dir="1" title="Move down">&#9660;</button>
                            </div>
                            <button type="button" class="btn-remove" title="Delete box">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                            </button>
                        </div>
                    {% endfor %}
                </div>
                <div class="list-empty" id="custom-empty" {% if custom_items %}style="display:none;"{% endif %}>No custom boxes yet.</div>

                <button type="button" class="btn-add" onclick="addCustomRow()">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                    <span>Add Custom Box</span>
                </button>
            </div>

            <!-- Panel 3: What is on air right now, plus ProPresenter -->
            <div class="panel panel-output">
                <div class="panel-header">
                    <h3>
                        <svg class="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#4ade80" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>
                        <span>On Air</span>
                    </h3>
                    <span class="item-count-badge" id="output-count" style="background:#0066cc; color:#fff;">{{ output_items|length }} Active</span>
                </div>
                <div class="instructions-hint">
                    Exactly what the RSS feed sends to ProPresenter, in order: live feed first, then custom boxes.
                </div>

                <div class="item-list" id="output-items-container">
                    {% for item in output_items %}
                        <div class="output-item-card">
                            <div class="card-content">
                                <span class="card-index">{{ loop.index }}.</span>
                                {% if item.source == 'live' %}
                                    <span class="badge-source badge-source-live">LIVE</span>
                                {% else %}
                                    <span class="badge-source badge-source-custom">TEXT</span>
                                {% endif %}
                                <span class="card-text">{{ item.text }}</span>
                            </div>
                        </div>
                    {% else %}
                        <div class="list-empty">Nothing on air. Turn on the XML feed or a custom box.</div>
                    {% endfor %}
                </div>

                <!-- ProPresenter auto-trigger -->
                <div class="pp-card">
                    <div class="pp-card-title">
                        <span>ProPresenter Auto-Refresh</span>
                        <span class="item-count-badge" id="pp-badge">Off</span>
                    </div>
                    <div class="pp-row">
                        <input type="text" id="pp-host" class="custom-input" placeholder="ProPresenter IP (e.g. 192.168.1.50)" style="flex:1;">
                        <input type="number" id="pp-port" class="custom-input pp-port" placeholder="Port" min="1" max="65535">
                        <button type="button" id="pp-test-btn" class="btn btn-sm" onclick="ppTestConnection()" title="Connect to ProPresenter and list props">Test Connection</button>
                    </div>
                    <div class="pp-row">
                        <select id="pp-prop" class="custom-input" title="Prop that holds the RSS scrolling text">
                            <option value="">— run Test Connection to list props —</option>
                        </select>
                    </div>
                    <div class="pp-modes" title="How ProPresenter reloads the ticker. Pick one, press Trigger Now to preview it live, then Save.">
                        <label class="pp-mode">
                            <input type="radio" name="pp-mode" value="trigger" checked>
                            <span>Trigger only</span>
                            <small>restarts scroll in place</small>
                        </label>
                        <label class="pp-mode">
                            <input type="radio" name="pp-mode" value="clear_trigger">
                            <span>Clear, then trigger</span>
                            <small>ticker blinks off and back (like manual)</small>
                        </label>
                        <label class="pp-mode">
                            <input type="radio" name="pp-mode" value="fade_trigger">
                            <span>Fade, then trigger</span>
                            <small>cross-fade over <input type="number" id="pp-fade-seconds" class="custom-input pp-fade" value="0.6" min="0.1" max="10" step="0.1"> s</small>
                        </label>
                    </div>
                    <div class="pp-toggles">
                        <label><input type="checkbox" id="pp-enabled"> Auto-trigger on changes</label>
                    </div>
                    <div class="pp-row" style="margin-bottom:4px;">
                        <button type="button" id="pp-save-btn" class="btn btn-sm" onclick="ppSaveSettings()">Save</button>
                        <button type="button" id="pp-trigger-btn" class="btn btn-sm" onclick="ppTriggerNow()" style="background:#1b6329; border:1px solid #2b8a3e;" title="Send a trigger to ProPresenter right now using the mode selected above (does not save)">Trigger Now</button>
                        <span class="pp-status" id="pp-status"></span>
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
        // ------------------------------------------------------------------
        // Ticker model: live XML items first (when the feed is on), then the
        // custom boxes that are switched on, top to bottom. The server builds
        // the real output; this page only edits settings and shows results.
        // ------------------------------------------------------------------
        let isFetchingLive = false;
        let refreshCycleInterval = null;

        function escapeHtml(s) {
            return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
        }

        // --- Live XML feed panel ---
        function renderLiveItems(items) {
            const list = document.getElementById('live-items-list');
            const badge = document.getElementById('live-count');
            if (badge) badge.textContent = `${items.length} Items`;
            if (!list) return;
            if (!items.length) {
                list.innerHTML = '<div class="list-empty">No live items currently available.</div>';
                return;
            }
            list.innerHTML = items.map((it, i) =>
                `<div class="live-card"><span class="card-index">${i + 1}.</span><span class="card-text">${escapeHtml(it.title)}</span></div>`
            ).join('');
        }

        function renderLiveEnabled(enabled) {
            const panel = document.getElementById('live-panel');
            const toggle = document.getElementById('live-enabled-toggle');
            const label = document.getElementById('live-enabled-label');
            if (panel) panel.classList.toggle('is-off', !enabled);
            if (toggle) toggle.checked = enabled;
            if (label) label.textContent = enabled ? 'ON AIR' : 'OFF';
            document.getElementById('live-hint-on').style.display = enabled ? '' : 'none';
            document.getElementById('live-hint-off').style.display = enabled ? 'none' : '';
        }

        async function setLiveEnabled(enabled) {
            renderLiveEnabled(enabled);
            try {
                const res = await fetch('/api/live_enabled', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled })
                });
                const data = await res.json();
                if (!res.ok || !data.ok) throw new Error(data.error || 'Save failed');
                applyState(data);
                flashSaved();
            } catch (err) {
                console.error('Failed to switch live feed:', err);
                renderLiveEnabled(!enabled);
                alert('Could not switch the XML feed: ' + err.message);
            }
        }

        // --- Custom boxes panel ---
        const ROW_HTML = `
            <label class="switch" title="Put this box on or off air">
                <input type="checkbox" class="custom-enabled" checked>
                <span class="switch-track"><span class="switch-thumb"></span></span>
            </label>
            <input type="text" class="custom-input custom-text" placeholder="Custom ticker text..." maxlength="500">
            <div class="row-move">
                <button type="button" class="btn-move" data-dir="-1" title="Move up">&#9650;</button>
                <button type="button" class="btn-move" data-dir="1" title="Move down">&#9660;</button>
            </div>
            <button type="button" class="btn-remove" title="Delete box">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>`;

        function customContainer() {
            return document.getElementById('custom-items-container');
        }

        function collectCustomItems() {
            return Array.from(customContainer().querySelectorAll('.custom-row')).map(row => ({
                text: row.querySelector('.custom-text').value,
                enabled: row.querySelector('.custom-enabled').checked
            }));
        }

        function updateCustomUI() {
            const rows = customContainer().querySelectorAll('.custom-row');
            let on = 0;
            rows.forEach(row => {
                const enabled = row.querySelector('.custom-enabled').checked;
                row.classList.toggle('is-off', !enabled);
                if (enabled && row.querySelector('.custom-text').value.trim()) on++;
            });
            const badge = document.getElementById('custom-count');
            if (badge) badge.textContent = `${on} On / ${rows.length}`;
            const empty = document.getElementById('custom-empty');
            if (empty) empty.style.display = rows.length ? 'none' : '';
        }

        function addCustomRow() {
            const row = document.createElement('div');
            row.className = 'custom-row';
            row.innerHTML = ROW_HTML;
            customContainer().appendChild(row);
            updateCustomUI();
            row.querySelector('.custom-text').focus();
            // An empty box is not on air, so there is nothing to save until text is typed.
        }

        let customSaveTimer = null;
        function scheduleCustomSave(delay) {
            if (customSaveTimer) clearTimeout(customSaveTimer);
            customSaveTimer = setTimeout(saveCustomItems, delay);
        }

        async function saveCustomItems() {
            customSaveTimer = null;
            try {
                const res = await fetch('/api/custom_items', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ items: collectCustomItems() })
                });
                const data = await res.json();
                if (!res.ok || !data.ok) throw new Error(data.error || 'Save failed');
                renderOutput(data.output_items, data.ticker);
                flashSaved();
            } catch (err) {
                console.error('Failed to save custom boxes:', err);
                const status = document.getElementById('save-status');
                if (status) {
                    status.textContent = '✗ Not saved';
                    status.style.color = '#f87171';
                    status.style.display = 'inline-block';
                }
            }
        }

        function flashSaved() {
            const status = document.getElementById('save-status');
            if (!status) return;
            status.textContent = '✓ Saved';
            status.style.color = '#4ade80';
            status.style.display = 'inline-block';
            clearTimeout(flashSaved._t);
            flashSaved._t = setTimeout(() => { status.style.display = 'none'; }, 1500);
        }

        function wireCustomPanel() {
            const box = customContainer();
            box.addEventListener('input', e => {
                if (e.target.classList.contains('custom-text')) {
                    updateCustomUI();
                    scheduleCustomSave(700);
                }
            });
            box.addEventListener('change', e => {
                if (e.target.classList.contains('custom-enabled')) {
                    updateCustomUI();
                    scheduleCustomSave(0);
                }
            });
            box.addEventListener('click', e => {
                const row = e.target.closest('.custom-row');
                if (!row) return;
                const move = e.target.closest('.btn-move');
                if (move) {
                    if (move.dataset.dir === '-1' && row.previousElementSibling) {
                        box.insertBefore(row, row.previousElementSibling);
                    } else if (move.dataset.dir === '1' && row.nextElementSibling) {
                        box.insertBefore(row.nextElementSibling, row);
                    } else {
                        return;
                    }
                    scheduleCustomSave(0);
                    return;
                }
                if (e.target.closest('.btn-remove')) {
                    const text = row.querySelector('.custom-text').value.trim();
                    if (text && !confirm(`Delete this box?\n\n${text}`)) return;
                    row.remove();
                    updateCustomUI();
                    scheduleCustomSave(0);
                }
            });
        }

        // --- On Air panel + ticker preview ---
        function renderOutput(items, ticker) {
            const list = document.getElementById('output-items-container');
            const badge = document.getElementById('output-count');
            if (badge) badge.textContent = `${items.length} Active`;
            if (list) {
                if (!items.length) {
                    list.innerHTML = '<div class="list-empty">Nothing on air. Turn on the XML feed or a custom box.</div>';
                } else {
                    list.innerHTML = items.map((it, i) => {
                        const badgeHtml = it.source === 'live'
                            ? '<span class="badge-source badge-source-live">LIVE</span>'
                            : '<span class="badge-source badge-source-custom">TEXT</span>';
                        return `<div class="output-item-card"><div class="card-content"><span class="card-index">${i + 1}.</span>${badgeHtml}<span class="card-text">${escapeHtml(it.text)}</span></div></div>`;
                    }).join('');
                }
            }
            updateTickerPreview(ticker);
        }

        function updateTickerPreview(combined) {
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

        function applyState(data) {
            if (Array.isArray(data.live_items)) renderLiveItems(data.live_items);
            if (typeof data.live_enabled === 'boolean') renderLiveEnabled(data.live_enabled);
            if (Array.isArray(data.output_items)) renderOutput(data.output_items, data.ticker || '');
        }

        async function refreshLiveItems(isManual = false) {
            if (isFetchingLive) return;
            // Don't overwrite the On Air list while a custom-box edit is waiting to save.
            if (customSaveTimer) return;
            isFetchingLive = true;
            try {
                const res = await fetch('/api/live_items');
                if (!res.ok) return;
                const data = await res.json();
                if (!customSaveTimer) applyState(data);
                updateCycleStatusUI(true, data.error);
            } catch (err) {
                console.error('Error refreshing live items:', err);
                updateCycleStatusUI(false, err.message);
            } finally {
                isFetchingLive = false;
            }
        }

        // --- ProPresenter integration ---
        function ppSetStatus(msg, kind) {
            const el = document.getElementById('pp-status');
            el.textContent = msg || '';
            el.className = 'pp-status' + (kind ? ' ' + kind : '');
        }

        function ppRenderBadge(settings, lastError) {
            const badge = document.getElementById('pp-badge');
            if (!settings.enabled) { badge.textContent = 'Off'; badge.style.background = ''; badge.style.color = ''; return; }
            if (lastError) { badge.textContent = 'Error'; badge.style.background = '#611e1e'; badge.style.color = '#fff'; return; }
            badge.textContent = 'On'; badge.style.background = '#1b6329'; badge.style.color = '#fff';
        }

        function ppFillPropSelect(props, selectedId, selectedName) {
            const sel = document.getElementById('pp-prop');
            sel.innerHTML = '';
            if (!props || props.length === 0) {
                const opt = document.createElement('option');
                opt.value = ''; opt.textContent = '— no props found —';
                sel.appendChild(opt);
                return;
            }
            props.forEach(p => {
                const opt = document.createElement('option');
                opt.value = p.uuid || p.name;
                opt.dataset.name = p.name;
                opt.textContent = p.name + (p.is_active ? '  (live)' : '');
                if ((selectedId && opt.value === selectedId) || (!selectedId && selectedName && p.name === selectedName)) opt.selected = true;
                sel.appendChild(opt);
            });
        }

        function ppGetMode() {
            const checked = document.querySelector('input[name="pp-mode"]:checked');
            return checked ? checked.value : 'trigger';
        }

        function ppSetMode(mode) {
            const radio = document.querySelector('input[name="pp-mode"][value="' + mode + '"]');
            if (radio) radio.checked = true;
        }

        function ppGetFadeSeconds() {
            const v = parseFloat(document.getElementById('pp-fade-seconds').value);
            return (isFinite(v) && v > 0) ? v : 0.6;
        }

        async function ppLoadStatus() {
            try {
                const res = await fetch('/api/propresenter/status');
                if (!res.ok) return;
                const data = await res.json();
                const s = data.settings;
                document.getElementById('pp-host').value = s.host || '';
                document.getElementById('pp-port').value = s.port || 1025;
                document.getElementById('pp-enabled').checked = !!s.enabled;
                ppSetMode(s.refresh_mode || 'trigger');
                document.getElementById('pp-fade-seconds').value = s.fade_seconds || 0.6;
                if (s.prop_id || s.prop_name) {
                    ppFillPropSelect([{ uuid: s.prop_id, name: s.prop_name || s.prop_id, is_active: false }], s.prop_id, s.prop_name);
                }
                ppRenderBadge(s, data.last_error);
                if (data.last_error) ppSetStatus('Last error: ' + data.last_error, 'err');
                else if (data.last_trigger_at) ppSetStatus('Last trigger ' + new Date(data.last_trigger_at * 1000).toLocaleTimeString(), 'ok');
            } catch (e) { console.error('ppLoadStatus', e); }
        }

        async function ppTestConnection() {
            const host = document.getElementById('pp-host').value.trim();
            const port = document.getElementById('pp-port').value.trim();
            if (!host) { ppSetStatus('Enter the ProPresenter IP first.', 'err'); return; }
            ppSetStatus('Connecting…');
            try {
                const res = await fetch('/api/propresenter/props?host=' + encodeURIComponent(host) + '&port=' + encodeURIComponent(port));
                const data = await res.json();
                if (!data.ok) { ppSetStatus(data.error, 'err'); return; }
                const sel = document.getElementById('pp-prop');
                const currentId = sel.value;
                ppFillPropSelect(data.props, currentId, null);
                ppSetStatus('Connected. ' + data.props.length + ' prop(s) found. Pick the ticker prop and Save.', 'ok');
            } catch (e) { ppSetStatus('Request failed: ' + e, 'err'); }
        }

        async function ppSaveSettings() {
            const sel = document.getElementById('pp-prop');
            const opt = sel.options[sel.selectedIndex];
            const body = {
                host: document.getElementById('pp-host').value.trim(),
                port: parseInt(document.getElementById('pp-port').value, 10) || 1025,
                prop_id: sel.value || '',
                prop_name: (opt && opt.dataset && opt.dataset.name) ? opt.dataset.name : '',
                enabled: document.getElementById('pp-enabled').checked,
                refresh_mode: ppGetMode(),
                fade_seconds: ppGetFadeSeconds(),
            };
            ppSetStatus('Saving…');
            try {
                const res = await fetch('/api/propresenter/settings', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
                });
                const data = await res.json();
                if (!data.ok) { ppSetStatus('Save failed.', 'err'); return; }
                ppRenderBadge(data.settings, '');
                ppSetStatus('Saved.', 'ok');
            } catch (e) { ppSetStatus('Save failed: ' + e, 'err'); }
        }

        async function ppTriggerNow() {
            // Uses the mode currently selected in the radios, even if not saved yet,
            // so the three modes can be compared live before committing to one.
            const mode = ppGetMode();
            ppSetStatus('Triggering (' + mode.replace('_', ' + ') + ')…');
            try {
                const res = await fetch('/api/propresenter/trigger', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ refresh_mode: mode, fade_seconds: ppGetFadeSeconds() })
                });
                const data = await res.json();
                if (!data.ok) { ppSetStatus(data.error, 'err'); return; }
                ppSetStatus('Trigger sent via ' + data.refresh_mode + ' at ' + new Date().toLocaleTimeString() + '. Press Save to keep this mode.', 'ok');
            } catch (e) { ppSetStatus('Trigger failed: ' + e, 'err'); }
        }

        async function restartRefreshCycle() {
            const btnText = document.getElementById('cycle-status-text');
            const btnIcon = document.getElementById('cycle-refresh-icon');
            const dot = document.getElementById('cycle-pulse-dot');
            
            if (btnIcon) btnIcon.classList.add('spin');
            if (btnText) btnText.textContent = 'Restarting...';

            // Reset client fetching lock & interval timer
            isFetchingLive = false;
            if (refreshCycleInterval) {
                clearInterval(refreshCycleInterval);
            }
            refreshCycleInterval = setInterval(refreshLiveItems, 15000);

            try {
                // Signal server background thread to immediately trigger & wake up
                await fetch('/api/restart_cycle', { method: 'POST' });
                await refreshLiveItems(true);
                
                if (btnText) btnText.textContent = 'Cycle Active ✓';
                if (dot) dot.classList.remove('error');
                setTimeout(() => {
                    if (btnText) btnText.textContent = 'Restart Cycle';
                }, 2500);
            } catch (err) {
                console.error('Failed to restart background cycle:', err);
                if (btnText) btnText.textContent = 'Retry Restart';
                if (dot) dot.classList.add('error');
            } finally {
                if (btnIcon) btnIcon.classList.remove('spin');
            }
        }

        function updateCycleStatusUI(isHealthy, errorMsg) {
            const dot = document.getElementById('cycle-pulse-dot');
            if (dot) {
                if (!isHealthy || errorMsg) {
                    dot.classList.add('error');
                    dot.title = 'Refresh error: ' + (errorMsg || 'Connection failed');
                } else {
                    dot.classList.remove('error');
                    dot.title = 'Background Auto-Refresh Active (every 15s)';
                }
            }
        }

        // Initialize the page and start the 15s auto-refresh
        document.addEventListener('DOMContentLoaded', () => {
            ppLoadStatus();
            wireCustomPanel();
            updateCustomUI();

            // Restore saved ticker speed
            try {
                const savedSpeed = localStorage.getItem('ticker_speed') || '35';
                const slider = document.getElementById('ticker-speed-slider');
                if (slider) slider.value = savedSpeed;
                setTickerSpeed(savedSpeed);
            } catch(e) {}

            // Automatically refresh live feed data every 15 seconds
            refreshCycleInterval = setInterval(refreshLiveItems, 15000);
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

def rebuild_output(config, live_items=None, error=None, refetched=True):
    """
    Recomputes output_items (live feed first, then enabled custom boxes) and
    saves config.json if anything changed. When refetched is False, or the
    fetch failed, the live part keeps the last stored live items.
    Returns (output_items, changed).
    """
    live_enabled, custom_items = ticker_settings(config)
    previous = config.get("output_items")
    output_items = build_output_items(
        live_enabled, live_items or [], custom_items, previous,
        live_ok=refetched and error is None,
    )
    changed = (
        output_items != previous
        or custom_items != config.get("custom_items")
        or config.get("live_enabled") is not live_enabled
    )
    if changed:
        config["live_enabled"] = live_enabled
        config["custom_items"] = custom_items
        config["output_items"] = output_items
        save_config(config)
    if output_items != previous:
        activity_log.log_feed_change([it["text"] for it in output_items])
    return output_items, changed


def refresh_from_feed():
    """Fetches the live feed (if on), rebuilds the ticker and returns the page state."""
    config = get_config()
    live_link = config.get("live_link") or DEFAULT_LIVE_LINK
    live_enabled, custom_items = ticker_settings(config)

    # Fetched even while the feed is off air, so the panel can still preview it.
    live_items, error = [], None
    if live_link and live_link.strip():
        live_items, _items_by_id, error = fetch_live_data(live_link)
        activity_log.log_live_items_change([it['title'] for it in live_items])

    output_items, changed = rebuild_output(config, live_items, error)
    return {
        "live_enabled": live_enabled,
        "live_link": live_link,
        "live_items": live_items,
        "custom_items": custom_items,
        "output_items": output_items,
        "ticker": ticker_text(output_items),
        "error": error,
        "changed": changed,
    }

# ==============================================================================
# BACKGROUND AUTO-REFRESH WORKER
# Runs 24/7 in the background to keep output_items updated with live data.
# ==============================================================================
BACKGROUND_REFRESH_INTERVAL = 15  # seconds
cycle_status_data = {
    "is_running": True,
    "last_refresh": None,
    "last_error": None,
    "refresh_count": 0
}
_refresh_event = threading.Event()

def run_single_refresh_cycle():
    """Performs one refresh cycle of live data and updates config.json if needed."""
    global cycle_status_data
    try:
        state = refresh_from_feed()
        if state["error"]:
            cycle_status_data["last_error"] = state["error"]
            return {"ok": False, "error": state["error"]}
        cycle_status_data["last_refresh"] = time.time()
        cycle_status_data["last_error"] = None
        cycle_status_data["refresh_count"] += 1
        return {"ok": True, "updated": state["changed"], "items_count": len(state["live_items"])}
    except Exception as e:
        cycle_status_data["last_error"] = str(e)
        return {"ok": False, "error": str(e)}

def background_refresh_worker():
    """Background daemon thread that runs continuous refresh cycles."""
    while True:
        run_single_refresh_cycle()
        _refresh_event.wait(timeout=BACKGROUND_REFRESH_INTERVAL)
        _refresh_event.clear()

_bg_thread_started = False
def ensure_background_worker_started():
    global _bg_thread_started
    if not _bg_thread_started:
        _bg_thread_started = True
        bg_thread = threading.Thread(target=background_refresh_worker, daemon=True, name="FeedRefreshWorker")
        bg_thread.start()

ensure_background_worker_started()

@app.route('/api/restart_cycle', methods=['POST', 'GET'])
def api_restart_cycle():
    """Triggers an immediate background refresh cycle and wakes the worker thread."""
    _refresh_event.set()
    res = run_single_refresh_cycle()
    return jsonify({
        "ok": True,
        "cycle_status": cycle_status_data,
        "result": res
    })

@app.route('/api/cycle_status')
def api_cycle_status():
    return jsonify({
        "is_running": cycle_status_data["is_running"],
        "last_refresh": cycle_status_data["last_refresh"],
        "last_error": cycle_status_data["last_error"],
        "refresh_count": cycle_status_data["refresh_count"],
        "interval_seconds": BACKGROUND_REFRESH_INTERVAL
    })

@app.route('/api/live_items')
def api_live_items():
    """Fetches the live feed, rebuilds the ticker, and returns everything the page shows."""
    state = refresh_from_feed()
    state.pop("changed", None)
    state["count"] = len(state["live_items"])
    state["cycle_status"] = cycle_status_data
    return jsonify(state)

@app.route('/')
def index():
    state = refresh_from_feed()
    config = get_config()
    return render_template_string(
        HTML_TEMPLATE,
        live_enabled=state["live_enabled"],
        live_items=state["live_items"],
        live_link=state["live_link"],
        custom_items=state["custom_items"],
        output_items=state["output_items"],
        combined_ticker=state["ticker"],
        error=state["error"],
        enable_spacer=config.get("enable_spacer", True),
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
    refresh_from_feed()
    ticker_watcher.notify_change()
    return redirect(url_for('index'))

@app.route('/toggle_spacer', methods=['POST'])
def toggle_spacer():
    config = get_config()
    config['enable_spacer'] = not config.get('enable_spacer', True)
    save_config(config)
    ticker_watcher.notify_change()
    return redirect(url_for('index'))

@app.route('/api/live_enabled', methods=['POST'])
def api_live_enabled():
    """Turns the live XML feed on or off air. JSON body: {"enabled": bool}."""
    data = request.get_json(silent=True) or {}
    enabled = _as_bool(data.get('enabled', True))
    config = get_config()
    _live, custom_items = ticker_settings(config)
    config['live_enabled'] = enabled
    config['custom_items'] = custom_items
    save_config(config)
    activity_log.log_live_toggle(enabled)
    state = refresh_from_feed()
    ticker_watcher.notify_change()
    state.pop("changed", None)
    return jsonify(dict(state, ok=True))

@app.route('/api/custom_items', methods=['POST'])
def api_custom_items():
    """
    Saves the custom boxes. JSON body: {"items": [{"text": str, "enabled": bool}, ...]}.
    Boxes that are switched on go on air after the live feed, in this order.
    Does not refetch the feed: the live part keeps the last fetched items.
    """
    data = request.get_json(silent=True) or {}
    raw_items = data.get('items')
    if not isinstance(raw_items, list):
        return jsonify({"ok": False, "error": "items must be a list"}), 400

    custom_items = []
    for it in raw_items:
        if isinstance(it, dict):
            text = str(it.get('text', '') or '')
            enabled = _as_bool(it.get('enabled', True))
        else:
            text, enabled = str(it or ''), True
        custom_items.append({"text": text[:500], "enabled": enabled})

    config = get_config()
    live_enabled, _custom = ticker_settings(config)
    config['live_enabled'] = live_enabled
    config['custom_items'] = custom_items
    output_items, _changed = rebuild_output(config, refetched=False)
    activity_log.log_txt_change([
        ("[on] " if b["enabled"] else "[off] ") + b["text"].strip()
        for b in custom_items if b["text"].strip()
    ])
    ticker_watcher.notify_change()
    return jsonify({
        "ok": True,
        "custom_items": custom_items,
        "output_items": output_items,
        "ticker": ticker_text(output_items),
    })

@app.route('/feed-log')
def feed_log_view():
    """Plain-text history of what /rss served, newest first (last 30 days)."""
    text = feed_log.read(feed_log.log_path(CONFIG_FILE))
    lines = text.splitlines()
    lines.reverse()
    header = "Feed updates, newest first (kept {} days)\n\n".format(feed_log.retention_days())
    body = "\n".join(lines) if lines else "No feed updates recorded yet."
    return Response(header + body + "\n", mimetype="text/plain; charset=utf-8")

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
    required_user, required_pass = get_auth_credentials(config)
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
    required_user, required_pass = get_auth_credentials(config)
    # If credentials have been added since the page was last loaded, go to login.
    if required_user and required_pass:
        return redirect(url_for('login'))
    return render_template_string(SETUP_TEMPLATE)

@app.route('/login', methods=['GET', 'POST'])
def login():
    config = get_config()
    required_user, required_pass = get_auth_credentials(config)

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
    ensure_background_worker_started()
    ticker_watcher.start()
    app.run(host=GUI_HOST, port=GUI_PORT)
