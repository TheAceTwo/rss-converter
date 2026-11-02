# Running rss-converter with Docker / Portainer

`main` can be deployed two ways from the same code:

- **On a Mac** with the scripts in `mac/`: see [MAC_SETUP.md](MAC_SETUP.md).
- **In Docker**, for example as a Portainer stack built straight from this GitHub repo (this page).

> The old `main` from before the Mac changes is kept on the
> [`docker-deploy`](https://github.com/TheAceTwo/rss-converter/tree/docker-deploy) branch if you ever need it.

## What gets deployed

`docker-compose.yml` builds one image from the `Dockerfile` and runs it as two services:

| Service | Runs | Container port | Host port (default) | Variable for host port |
|---|---|---|---|---|
| `feed` | `app.py`, the RSS feed for ProPresenter | 5050 | **5000** | `FEED_HOST_PORT` |
| `gui` | `gui.py`, the control panel + background watcher | 5001 | **5001** | `GUI_HOST_PORT` |

The feed's host port defaults to **5000** in Docker so an existing ProPresenter Linked Text URL of
`http://<docker-host>:5000/rss` keeps working. (On a Mac the feed uses 5050 because macOS's AirPlay
Receiver holds 5000.)

Both services share a named volume, `rss-data`, mounted at `/data`. It holds `config.json` (feed URL,
custom boxes, ProPresenter settings) and `rss_changes.log`, so settings survive redeploys and image updates.

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `SECRET_KEY` | **yes** | none (deploy fails without it) | Signs control panel login cookies. Use a long random string. |
| `AUTH_USERNAME` | yes, unless set in `config.json` | empty | Control panel username |
| `AUTH_PASSWORD` | yes, unless set in `config.json` | empty | Control panel password |
| `FEED_HOST_PORT` | no | `5000` | Host port for the RSS feed |
| `GUI_HOST_PORT` | no | `5001` | Host port for the control panel |
| `XML_URL` | no | empty | Default live XML source (the URL saved in the panel takes priority) |

If `auth_username` and `auth_password` are both set in `config.json`, those win over the environment variables.

## Deploy in Portainer from GitHub

1. **Stacks → Add stack.** Name it, for example, `rss-converter`.
2. Build method: **Repository**.
3. Repository URL: `https://github.com/TheAceTwo/rss-converter`
   - If the repo is private, turn on **Authentication** and use your GitHub username and a personal access token with read access to the repo.
4. Repository reference: `refs/heads/main`
5. Compose path: `docker-compose.yml`
6. **Environment variables:** add `SECRET_KEY`, `AUTH_USERNAME` and `AUTH_PASSWORD` (and any others from the table above).
7. Optional: turn on **GitOps updates** (polling or webhook) so Portainer redeploys when `main` changes.
   Turn on **Re-pull image and redeploy** / force rebuild if offered, so code changes are rebuilt.
8. **Deploy the stack.**

Then open `http://<docker-host>:5001`, log in, and paste the live XML URL into the panel.
Point ProPresenter's Linked Text at `http://<docker-host>:5000/rss` (or your `FEED_HOST_PORT`).

### Updating

- With GitOps updates on: push to `main` and Portainer redeploys on its own.
- Otherwise: open the stack and click **Pull and redeploy**.

Your settings in the `rss-data` volume are kept either way.

### Coming from an older Portainer stack

If your existing stack used its own compose file pasted into Portainer's web editor, replace it with
the repository method above. Two things to check:

- **Ports:** the feed now listens on 5050 *inside* the container. This compose file maps it to host
  port 5000 for you; if you keep your own compose file, map `5000:5050` (or set `FEED_PORT=5000` in the container).
- **Config location:** the image stores `config.json` in `/data`. To keep your old settings, copy your
  old `config.json` into the new `rss-data` volume (or mount your old folder at `/data`). Older
  configs upgrade automatically on first start.

## Plain Docker Compose (no Portainer)

```bash
git clone https://github.com/TheAceTwo/rss-converter.git
cd rss-converter
cat > .env <<'ENV'
SECRET_KEY=change-me-to-something-long-and-random
AUTH_USERNAME=admin
AUTH_PASSWORD=choose-a-password
ENV
docker compose up -d --build
```

Logs: `docker compose logs -f`. Activity log: `docker compose exec gui cat /data/rss_changes.log`.
