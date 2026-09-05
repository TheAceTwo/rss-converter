"""
watcher.py - Background watcher that keeps the RSS output fresh and pushes a
prop trigger to ProPresenter whenever the ticker text changes.

Why this exists: ProPresenter reads an RSS Linked Text source only when the
prop is triggered. It never re-polls. So this tool has to (1) notice the
ticker content changed and (2) re-trigger the prop over ProPresenter's HTTP
API. It also persists live score updates into config.json so app.py's /rss
is current even when nobody has the control panel open in a browser.
"""

import threading
import time

import logger as activity_log
import propresenter
from output_resolver import resolve_output_items, ticker_text


class TickerWatcher:
    def __init__(self, get_config, save_config, fetch_live_data, get_settings,
                 poll_seconds=15, debounce_seconds=3.0, trigger_fn=propresenter.trigger_prop):
        self.get_config = get_config
        self.save_config = save_config
        self.fetch_live_data = fetch_live_data
        self.get_settings = get_settings
        self.poll_seconds = poll_seconds
        self.debounce_seconds = debounce_seconds
        self.trigger_fn = trigger_fn

        self.last_status = {"last_trigger_at": None, "last_error": "", "last_text": None}
        self._lock = threading.Lock()
        self._debounce_timer = None
        self._stop_event = threading.Event()
        self._thread = None

    # ------------------------------------------------------------------ polling
    def check_once(self):
        """One poll cycle. Returns True if the combined ticker text changed."""
        config = self.get_config()
        live_link = config.get("live_link") or ""
        raw_output = config.get("output_items")
        if raw_output is None:
            raw_output = list(config.get("custom_items") or [])

        live_items, items_by_id, error = self.fetch_live_data(live_link)
        if error:
            self.last_status["last_error"] = error
        activity_log.log_live_items_change([it["title"] for it in live_items])

        resolved = resolve_output_items(raw_output, live_items, items_by_id)
        if resolved != raw_output:
            config["output_items"] = resolved
            try:
                self.save_config(config)
            except OSError as e:
                self.last_status["last_error"] = "Could not save config: {}".format(e)

        text = ticker_text(resolved)
        previous = self.last_status["last_text"]
        self.last_status["last_text"] = text

        if previous is None:
            return False            # first observation: prime only, never trigger
        if text != previous:
            self._schedule_trigger()
            return True
        return False

    # ------------------------------------------------------------- notifications
    def notify_change(self):
        """Call after a user edits the output. Debounced like feed changes."""
        self._schedule_trigger()

    def _schedule_trigger(self):
        with self._lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            self._debounce_timer = threading.Timer(self.debounce_seconds, self._fire_trigger)
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

    def _fire_trigger(self):
        settings = self.get_settings(self.get_config())
        if not settings["enabled"]:
            return
        prop = settings["prop_id"] or settings["prop_name"]
        try:
            self.trigger_fn(settings["host"], settings["port"], prop,
                            mode=settings["refresh_mode"], fade_seconds=settings["fade_seconds"])
            self.last_status["last_trigger_at"] = time.time()
            self.last_status["last_error"] = ""
            activity_log.log_propresenter("triggered prop {} via {} ({}:{})".format(
                settings["prop_name"] or prop, settings["refresh_mode"], settings["host"], settings["port"]))
        except propresenter.ProPresenterError as e:
            self.last_status["last_error"] = str(e)
            activity_log.log_propresenter("trigger FAILED: {}".format(e))
        except Exception as e:  # never let the timer thread die silently
            self.last_status["last_error"] = "Unexpected error: {}".format(e)
            activity_log.log_propresenter("trigger FAILED unexpectedly: {}".format(e))

    # ---------------------------------------------------------------- lifecycle
    def _run(self):
        while not self._stop_event.is_set():
            try:
                self.check_once()
            except Exception as e:  # keep the loop alive no matter what
                self.last_status["last_error"] = "Watcher error: {}".format(e)
            self._stop_event.wait(self.poll_seconds)

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="ticker-watcher", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        with self._lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
        if self._thread is not None:
            self._thread.join(timeout=2)
