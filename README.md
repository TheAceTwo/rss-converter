# rss-converter

A small data-to-RSS converter for a scrolling ticker in ProPresenter, with its own web control panel.

Two Flask apps share one `config.json`:

| App | Port | Purpose |
|---|---|---|
| `app.py` | 5050 (`FEED_PORT`) | Serves `/rss`, the feed ProPresenter reads. No login. |
| `gui.py` | 5001 (`GUI_PORT`) | Control panel: turn the live XML feed on or off, manage custom text boxes, configure ProPresenter. Login required. |

The feed uses 5050 rather than Flask's usual 5000 because AirPlay Receiver holds port 5000 on macOS 12 and later.

## Ports and settings

| Port / setting | Default | Used for |
|---|---|---|
| `FEED_PORT` | 5050 | RSS feed, `http://<host>:5050/rss`. Point ProPresenter's Linked Text here. |
| `GUI_PORT` | 5001 | Control panel, `http://<host>:5001` |
| `FEED_HOST` / `GUI_HOST` | `0.0.0.0` | Address each app listens on. `127.0.0.1` keeps it local to the machine. |
| ProPresenter API port | set in ProPresenter | Entered in the control panel; ProPresenter > Settings > Network |
| `SECRET_KEY` | random, saved as `.secret_key` | Signs login cookies. Leave blank to auto-generate. |
| `AUTH_USERNAME` / `AUTH_PASSWORD` | empty | Control panel login, used when `config.json` doesn't set `auth_username` / `auth_password` |
| `RSS_LOG_FILE` | `rss_changes.log` next to the code | Activity log location |
| `XML_URL` | empty | Optional default live XML source |
| `RSS_CONFIG_FILE` | `config.json` next to the code | Shared config for both apps |

## Run on a Mac (recommended)

The Mac scripts create a virtualenv, generate `rss-converter.env` with the settings above, and can install
launchd agents so both apps start at login:

```bash
mac/run.sh                 # run in this Terminal window (Ctrl+C to stop)
mac/install-launchd.sh     # start at login and restart on crash
mac/uninstall-launchd.sh   # remove the login services
```

Full step-by-step setup, including firewall, sleep, and ProPresenter settings: [docs/MAC_SETUP.md](docs/MAC_SETUP.md).

The earlier Docker-based deployment is preserved on the [`docker-deploy`](https://github.com/TheAceTwo/rss-converter/tree/docker-deploy) branch.

## Run with Docker / Portainer

`main` also deploys as a Portainer stack straight from this GitHub repo (Stacks > Add stack > Repository,
compose path `docker-compose.yml`). The stack runs the feed (`rss-converter`, port **5000**), the control
panel (`rss-gui`, port 5001) and a Cloudflare Tunnel (`cloudflared`). Settings live in a Portainer-managed
volume; set `AUTH_USERNAME`, `AUTH_PASSWORD` and `TUNNEL_TOKEN` as stack environment variables, then put
the XML link in through the control panel.

Full steps, variables and tunnel routes: [docs/DOCKER.md](docs/DOCKER.md).

| | Mac (`mac/` scripts) | Docker / Portainer |
|---|---|---|
| Feed URL for ProPresenter | `http://<mac>:5050/rss` | `http://<docker-host>:5000/rss` |
| Control panel | `http://<mac>:5001` | `http://<docker-host>:5001` |
| Settings | `rss-converter.env` | stack environment variables |
| `config.json` + activity log | project folder | `rss-data` volume (managed by Portainer) |

## Run manually (any OS)

```bash
pip install -r requirements.txt
python app.py &      # feed, port 5050
python gui.py        # control panel, port 5001
```

Open http://localhost:5001. On first run the GUI shows a setup page: add `auth_username` and `auth_password` to `config.json` by hand, then reload. Set `XML_URL` in the environment or paste the live XML URL in the panel.

## Using the control panel

The ticker is always built in this order:

1. **Live XML feed**: every item from the feed, in feed order, refreshed every 15 seconds. Nothing to pick or drag: when the feed is on, all of it is on air.
2. **Custom boxes**: each box that is switched on, top to bottom.

| Panel | What it does |
|---|---|
| **Live XML Feed** | Feed URL, plus an **ON AIR / OFF** switch. Off takes the whole feed out of the ticker so only custom boxes run; the panel still previews the feed, greyed out. |
| **Custom Boxes** | Text boxes with their own on/off switch, ▲▼ to reorder, ✕ to delete, and **Add Custom Box**. Everything saves automatically. |
| **On Air** | Read-only view of exactly what `/rss` is sending, with LIVE and TEXT tags, plus the ProPresenter settings. |

If the feed can't be reached, the last fetched scores stay on air until it comes back.

Configs from older versions upgrade automatically: custom presets that were on air start switched on, the rest start switched off.

## ProPresenter auto-refresh

ProPresenter loads an RSS Linked Text source only when its prop is triggered and never re-polls. This tool re-triggers the prop for you whenever the ticker content changes.

1. In ProPresenter: Settings > Network, turn on **Enable Network**, note the IP and port.
2. In ProPresenter: build the ticker as a **Prop** with a Scrolling Text object whose Linked Text is RSS pointing at `http://<this-machine>:5050/rss` (Mac) or `http://<docker-host>:5000/rss` (Docker).
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
