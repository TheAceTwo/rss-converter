# Running rss-converter on a Mac

This guide sets up one Mac to host both parts of rss-converter:

- the **feed** (`app.py`), which ProPresenter reads, and
- the **control panel** (`gui.py`), the web page used to run the ticker.

Once installed, both start automatically when you log in to the Mac and restart if they crash.

> The previous Docker-based version of the project is kept on the
> [`docker-deploy`](https://github.com/TheAceTwo/rss-converter/tree/docker-deploy) branch.

## Ports

| What | Default port | URL | Setting |
|---|---|---|---|
| RSS feed (`app.py`) | **5050** | `http://<mac>:5050/rss` | `FEED_PORT` |
| Control panel (`gui.py`) | **5001** | `http://<mac>:5001` | `GUI_PORT` |
| ProPresenter network API (on the ProPresenter machine) | set in ProPresenter, e.g. 50001 | `http://<propresenter>:<port>` | entered in the control panel |

`<mac>` is `localhost` on the Mac itself, or the Mac's IP address from another computer
(System Settings → Wi-Fi or Network → Details → IP address).

**Why 5050 and not 5000?** On macOS 12 (Monterey) and later, AirPlay Receiver listens on port 5000,
so the feed would fail to start or another service would answer. The feed defaults to 5050 instead.

All settings live in `rss-converter.env` in the project folder (created on first run, not committed to git):

| Setting | Default | Meaning |
|---|---|---|
| `FEED_PORT` | `5050` | Port for the RSS feed |
| `GUI_PORT` | `5001` | Port for the control panel |
| `FEED_HOST` / `GUI_HOST` | `0.0.0.0` | `0.0.0.0` = reachable from other machines; `127.0.0.1` = this Mac only |
| `SECRET_KEY` | random | Signs control panel login cookies. Generated for you |
| `XML_URL` | empty | Optional default live XML source |

After changing a setting, run `mac/install-launchd.sh` again (or restart `mac/run.sh`).

## 1. Install Python 3

Check whether it is already there:

```bash
python3 --version
```

If it is missing, or macOS offers to install the Command Line Tools, either accept that, or install
Python from <https://www.python.org/downloads/macos/>, or with Homebrew: `brew install python`.

## 2. Get the code

Put the project somewhere **outside** Desktop, Documents and Downloads. macOS privacy protection
can block background services from reading those folders.

```bash
cd ~
git clone https://github.com/TheAceTwo/rss-converter.git
cd rss-converter
```

To update later: `git pull`, then `mac/install-launchd.sh` to restart with the new code.

## 3. Try it in a Terminal window

```bash
mac/run.sh
```

The first run creates a Python virtual environment in `.venv`, installs the requirements, and creates
`rss-converter.env`. It then starts both apps and prints their URLs. Press Ctrl+C to stop.

If macOS asks **"Do you want the application python3 to accept incoming network connections?"**,
click **Allow**. ProPresenter needs this when it runs on a different computer.

## 4. Set up the control panel login

Open <http://localhost:5001>. On first run it shows a setup page. Edit `config.json` in the project
folder and add your credentials:

```json
"auth_username": "admin",
"auth_password": "choose-a-password"
```

Reload the page and log in. Paste the live XML URL into the panel (or set `XML_URL` in
`rss-converter.env`).

## 5. Start automatically at login

Stop `mac/run.sh` with Ctrl+C, then:

```bash
mac/install-launchd.sh
```

This installs two launchd agents in `~/Library/LaunchAgents/`:

- `com.rss-converter.feed` runs `app.py`
- `com.rss-converter.gui` runs `gui.py`

Both start now and at every login, and launchd restarts them if they exit.

Useful commands:

```bash
launchctl print gui/$(id -u)/com.rss-converter.feed | grep state   # is it running?
tail -f logs/feed.err.log logs/gui.err.log                          # service output
mac/install-launchd.sh                                              # restart both
mac/uninstall-launchd.sh                                            # stop and remove
```

The ticker activity log is still `rss_changes.log` in the project folder.

## 6. Keep the Mac awake and logged in

The agents run only while your user is logged in, and pause while the Mac sleeps.

- System Settings → Users & Groups → **Automatically log in as** your user (requires FileVault off), or log in after each restart.
- System Settings → Energy (or Battery → Options) → turn on **Prevent automatic sleeping when the display is off**.
- System Settings → General → Software Update → consider turning off automatic macOS updates during events.

## 7. Connect ProPresenter

In the ProPresenter prop's Scrolling Text, set Linked Text → RSS to:

- `http://localhost:5050/rss` if ProPresenter runs on this Mac, or
- `http://<mac-ip>:5050/rss` if it runs on another computer.

Then follow the "ProPresenter auto-refresh" steps in the [README](../README.md#propresenter-auto-refresh).

Give the Mac a fixed IP address (a DHCP reservation in your router, or System Settings → Network →
Details → TCP/IP → Configure IPv4: Manually) so this URL keeps working.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Address already in use` | Another program uses the port. Change `FEED_PORT` / `GUI_PORT` in `rss-converter.env` and rerun `mac/install-launchd.sh`. Find the culprit with `lsof -i :5050`. |
| Feed works on the Mac but not from ProPresenter's computer | Allow python3 in System Settings → Network → Firewall → Options; check `FEED_HOST=0.0.0.0`; use the Mac's current IP. |
| Services do not start; `Operation not permitted` in `logs/*.err.log` | The project is in Desktop/Documents/Downloads. Move it (e.g. to `~/rss-converter`) and rerun `mac/install-launchd.sh`. |
| `python3 not found` | Install Python 3 (step 1). |
