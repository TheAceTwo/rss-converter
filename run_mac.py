"""
run_mac.py - Single entry point for the packaged (PyInstaller) app.

Starts the RSS feed server (FEED_PORT, default 5000) in a background thread and
the control panel (GUI_PORT, default 5001) in the main thread, plus the ticker
watcher. From source you can still run `python app.py` and `python gui.py`.
"""

import os
import socket
import sys
import threading

import app as feed_app
import gui
import paths

HOST = '0.0.0.0'


def _port(env_name, default):
    raw = os.environ.get(env_name, str(default))
    try:
        return int(raw)
    except ValueError:
        sys.exit("{} must be a number, got {!r}".format(env_name, raw))


def _require_free(port, env_name, label):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((HOST, port))
        except OSError:
            hint = ""
            if sys.platform == "darwin" and port == 5000:
                hint = (" On macOS this is usually AirPlay Receiver: turn it off in"
                        " System Settings > General > AirDrop & Handoff.")
            sys.exit("Port {} ({}) is already in use.{} Or pick another port with {}=<port>."
                     .format(port, label, hint, env_name))


def main():
    feed_port = _port('FEED_PORT', 5000)
    gui_port = _port('GUI_PORT', 5001)
    _require_free(feed_port, 'FEED_PORT', 'RSS feed')
    _require_free(gui_port, 'GUI_PORT', 'control panel')

    threading.Thread(
        target=lambda: feed_app.app.run(host=HOST, port=feed_port, threaded=True, use_reloader=False),
        name='feed-server', daemon=True,
    ).start()

    gui.ensure_background_worker_started()
    gui.ticker_watcher.start()

    print("rss-converter: feed on http://localhost:{}/rss, control panel on http://localhost:{}"
          .format(feed_port, gui_port), flush=True)
    print("rss-converter: data folder {}".format(paths.data_dir() or os.getcwd()), flush=True)
    gui.app.run(host=HOST, port=gui_port, use_reloader=False)


if __name__ == '__main__':
    main()
