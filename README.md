# rss-converter

A small data-to-RSS converter for a scrolling ticker in ProPresenter, with its own web control panel.

Two Flask apps share one `config.json`:

| App | Port | Purpose |
|---|---|---|
| `app.py` | 5000 | Serves `/rss`, the feed ProPresenter reads. No login. |
| `gui.py` | 5001 | Control panel: pick live items and custom text, order the ticker, configure ProPresenter. Login required. |

## Run

```bash
pip install -r requirements.txt
python app.py &      # feed
python gui.py        # control panel
```

Open http://localhost:5001. On first run the GUI shows a setup page: add `auth_username` and `auth_password` to `config.json` by hand, then reload. Set `XML_URL` in the environment or paste the live XML URL in the panel.

## ProPresenter auto-refresh

ProPresenter loads an RSS Linked Text source only when its prop is triggered and never re-polls. This tool re-triggers the prop for you whenever the ticker content changes.

1. In ProPresenter: Settings > Network, turn on **Enable Network**, note the IP and port.
2. In ProPresenter: build the ticker as a **Prop** with a Scrolling Text object whose Linked Text is RSS pointing at `http://<this-machine>:5000/rss`.
3. In the control panel, under the live URL: enter the IP and port, click **Test Connection**, choose the ticker prop.
4. Pick a refresh mode and press **Trigger Now** to preview each one live on the output screen. Trigger Now uses whatever mode is selected, saved or not, so you can compare all three in a minute:
   - **Trigger only**: the scroll restarts from the first item in place.
   - **Clear, then trigger**: the ticker blinks off and back, exactly like clearing and re-clicking by hand.
   - **Fade, then trigger**: the ticker cross-fades into the restarted version over the number of seconds you set. The prop must already have a transition assigned in ProPresenter (any type, any duration); the tool only changes the duration.
5. Tick **Auto-trigger on changes** and click **Save**.

The background watcher polls the live feed every 15 seconds, saves score changes into `config.json` so `/rss` stays current with no browser open, and sends one trigger 3 seconds after the last change using the saved mode. Every reload restarts the scroll from the first item; that is how ProPresenter reloads Linked Text.

Activity is logged to `rss_changes.log`. ProPresenter events are tagged `[PP]`.

## Development

```bash
pip install -r requirements-dev.txt
pytest -q
```

## License

This project is licensed under the [PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0). Commercial use requires a separate, paid agreement.
