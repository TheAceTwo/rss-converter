# Running rss-converter with Docker / Portainer

`main` can be deployed two ways from the same code:

- **On a Mac** with the scripts in `mac/`: see [MAC_SETUP.md](MAC_SETUP.md).
- **In Docker**, as a Portainer stack built straight from this GitHub repo (this page).

> The old `main` from before the Mac changes is kept on the
> [`docker-deploy`](https://github.com/TheAceTwo/rss-converter/tree/docker-deploy) branch if you ever need it.

## What gets deployed

`docker-compose.yml` builds one image from the `Dockerfile` and runs three containers:

| Container | Runs | Port inside the stack | Published on the host (default) |
|---|---|---|---|
| `rss-converter` | `app.py`, the RSS feed ProPresenter reads | 5000 | `5000` (`FEED_HOST_PORT`) |
| `rss-gui` | `gui.py`, the control panel + background watcher | 5001 | `5001` (`GUI_HOST_PORT`) |
| `cloudflared` | Cloudflare Tunnel | none | none |

Everything the app saves lives in the **`rss-data` volume**, which Portainer manages:
`config.json` (XML link, custom boxes, ProPresenter settings), `rss_changes.log`, and `.secret_key`.
It survives redeploys and image rebuilds. A new volume starts with an empty config, so after the first
deploy you log in and paste the XML link into the control panel.

## Environment variables

Set these on the stack in Portainer (**Environment variables** section). All are optional except where noted.

| Variable | Default | Purpose |
|---|---|---|
| `AUTH_USERNAME` | empty | Control panel username. **Set this** (or the panel shows a setup page). |
| `AUTH_PASSWORD` | empty | Control panel password. **Set this.** |
| `TUNNEL_TOKEN` | empty | Cloudflare Tunnel token. **Required** for the `cloudflared` container. If you don't use a tunnel, delete that service from the compose file. |
| `SECRET_KEY` | random | Signs login cookies. Leave it out and a random key is generated once and kept in the volume. If you set it, use letters and digits only (64 is plenty). |
| `XML_URL` | empty | Default live XML link. The link saved in the control panel takes priority. |
| `FEED_HOST_PORT` | `5000` | Host port for the RSS feed (`http://<server>:5000/rss`). |
| `GUI_HOST_PORT` | `5001` | Host port for the control panel. Use `127.0.0.1:5001` to keep it reachable only from the server itself, e.g. when Cloudflare Tunnel publishes it. |

## Cloudflare Tunnel routes

Inside the stack, containers reach each other by name. In the Cloudflare Zero Trust dashboard
(Networks > Tunnels > your tunnel > Public hostnames), point the hostnames at:

- Control panel: `http://rss-gui:5001`
- RSS feed (if you publish it): `http://rss-converter:5000`

These are the same names the old hand-written stack used, so existing routes keep working.

`cloudflared` runs with `--no-autoupdate` on purpose: it can't update itself inside a container.
Update it by re-pulling the image (see **Updating**).

## Deploy in Portainer from GitHub

1. **Remove the old stack first** if you have one (Stacks > old stack > Delete). The new stack uses the
   same container names and ports, so both can't run at once. Your old `C:\docker\rss-converter` folder
   is left untouched.
2. **Stacks > Add stack.** Name it, for example, `rss-converter`.
3. Build method: **Repository**.
4. Repository URL: `https://github.com/TheAceTwo/rss-converter`
   - If the repo is private, turn on **Authentication** with your GitHub username and a personal access
     token that can read the repo.
5. Repository reference: `refs/heads/main`
6. Compose path: `docker-compose.yml`
7. **Environment variables:** add `AUTH_USERNAME`, `AUTH_PASSWORD`, `TUNNEL_TOKEN`, and
   `GUI_HOST_PORT=127.0.0.1:5001` if the panel should only be reachable through the tunnel. Add any others
   from the table above.
8. Optional: turn on **GitOps updates** (polling or webhook) so Portainer redeploys when `main` changes.
9. **Deploy the stack.** The first deploy builds the image, which takes a minute.

Then:

1. Open the control panel (`http://localhost:5001` on the server, or your tunnel hostname) and log in.
2. Paste the live XML link and click **Save URL**. Add custom boxes and ProPresenter settings as needed.
3. Point ProPresenter's Linked Text at `http://<server>:5000/rss`.

## Updating

- **App code:** with GitOps updates on, push to `main` and Portainer redeploys by itself. Otherwise open
  the stack and click **Pull and redeploy**. The compose file sets `pull_policy: build`, so every deploy
  rebuilds the image from the latest code.
- **cloudflared:** in the stack editor, click **Update the stack** with **Re-pull image and redeploy**
  turned on. Every month or two is enough; do it on a quiet day, not right before an event.

Your settings in the `rss-data` volume are kept either way.

## Backing up or editing the config

The config lives in the volume, not on a Windows folder. To look at it or copy it out:

```bash
docker exec rss-gui cat /data/config.json
docker cp rss-gui:/data/config.json ./config-backup.json
docker exec rss-gui cat /data/rss_changes.log
```

Or in Portainer: Volumes > `<stack>_rss-data` > Browse (where available).

## Plain Docker Compose (no Portainer)

```bash
git clone https://github.com/TheAceTwo/rss-converter.git
cd rss-converter
cat > .env <<'ENV'
AUTH_USERNAME=admin
AUTH_PASSWORD=choose-a-password
TUNNEL_TOKEN=your-tunnel-token
ENV
docker compose up -d --build
```

No tunnel? Delete the `cloudflared` service from `docker-compose.yml` first, or start only the app:
`docker compose up -d --build rss-converter rss-gui`.
