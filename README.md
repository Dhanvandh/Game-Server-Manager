# Game Server Manager

Web dashboard to manage Docker-based game servers (for example Minecraft): start/stop containers, stream logs over WebSockets, view CPU/RAM charts, read config files (admins can edit), manage bans (admins), and authenticate with JWT plus optional Google OAuth2. **Admin** creates server profiles and assigns an **owner** (a **member** account). **Owners** start/stop their servers from the dashboard. **Shared viewers** (optional list per profile) only see those servers on the dashboard and cannot start or stop them.

## Stack

- **Frontend:** React, TypeScript, TailwindCSS, Socket.IO client, Chart.js (`react-chartjs-2`)
- **Backend:** Flask, Flask-SocketIO (eventlet), Docker SDK, Flask-JWT-Extended, Authlib (Google), SQLAlchemy, PostgreSQL
- **Deploy:** Docker Compose (frontend nginx, backend, Postgres); backend mounts the Docker socket to control game containers

## Quick start (Docker Compose)

Run all `docker compose` commands from the **`game-server-manager` directory** (where `docker-compose.yml` lives). If you see `no configuration file provided: not found`, you are in the wrong folder.

1. Copy environment template and set secrets (required for any real deployment):

   ```bash
   cp .env.example .env
   ```

   Edit `.env`. For a quick local trial, Compose provides weak default JWT/Flask secrets if variables are unset; **change them for production**.

2. Start everything:

   ```bash
   docker compose up --build
   ```

3. Open **http://localhost** (frontend). The UI proxies `/api` and `/socket.io` to the backend.

4. Log in:

   - Set `ADMIN_EMAIL` and `ADMIN_PASSWORD` in `.env` before the first `up` to seed an admin user, **or**
   - Register at **http://localhost/register** (member account), then have an existing admin promote you or assign you as a profile owner, **or**
   - Configure Google OAuth (see below).

### Google OAuth2

**1. Google Cloud Console** ([Credentials](https://console.cloud.google.com/apis/credentials))

- Create **OAuth client ID** → Application type **Web application**.
- **Authorized JavaScript origins**: `http://localhost` (production: add `https://your-domain`).
- **Authorized redirect URIs** (must match `OAUTH_REDIRECT_URI` **exactly**):  
  `http://localhost/api/auth/google/callback`
- Copy **Client ID** and **Client secret** into `.env` (see `.env.example`), then `docker compose up --build`.

**2. `.env` variables**

| Variable | Purpose |
|----------|---------|
| `GOOGLE_CLIENT_ID` | Web client ID from Google |
| `GOOGLE_CLIENT_SECRET` | Web client secret |
| `OAUTH_REDIRECT_URI` | Same URI you registered (e.g. `http://localhost/api/auth/google/callback`) |
| `FRONTEND_URL` | Where users open the UI (e.g. `http://localhost`) — used after login redirect |

**3. Using Google as a client (browser flow)**

1. Go to **Login** on your app (`FRONTEND_URL`).
2. If Google is configured, the button says **Continue with Google**; click it (navigates to `FRONTEND_URL`’s same host → `/api/auth/google` via nginx).
3. Sign in with Google; you return to **`/api/auth/google/callback`**, then the app redirects to **`/oauth-callback?access_token=...`** and you are logged in.
4. First-time Google users are **members**; an **admin** can change the role under **Admin** and assign server ownership.

**4. Optional check**

- `GET /api/auth/google/enabled` returns `{"enabled": true|false}` (login page uses this to show or disable the button).

### Game server containers

- Each **server profile** maps to one container name `gsm-server-<id>`.
- Data is stored under the `server_volumes` Docker volume, mounted in the backend at `/data/servers`. If `volume_path` on the profile is **not** absolute, it is resolved as `/data/servers/<id>` after creation.
- The host directory is bind-mounted into the game container at `/data`.
- Default image in the UI is `itzg/minecraft-server:latest` with `EULA=TRUE` and `MEMORY=2G` in `env_vars` (adjust per game).

The machine running Docker Compose must allow the backend service to use the mounted Docker socket (Linux, Docker Desktop on Windows/macOS).

## Local development (without full stack)

**Backend** (Postgres required, or set `DATABASE_URL`):

```bash
cd backend
pip install -r requirements.txt
set FLASK_APP=run.py
set DATABASE_URL=postgresql+psycopg://...
set JWT_SECRET_KEY=your-32+-char-secret
set JWT_REFRESH_SECRET_KEY=another-secret
set FLASK_SECRET_KEY=session-secret
set SOCKETIO_ASYNC_MODE=threading
python -c "from app import create_app; create_app()"  # creates tables if needed
# optional: gunicorn as in Docker
gunicorn --worker-class eventlet -w 1 -b 127.0.0.1:5000 run:app
```

**Frontend:**

```bash
cd frontend
npm install
npm run dev
```

Vite proxies `/api` and `/socket.io` to `http://127.0.0.1:5000`.

## API overview

- `POST /api/auth/register`, `POST /api/auth/login` — access token in JSON; refresh token in HttpOnly cookie
- `POST /api/auth/refresh` — cookie-only refresh
- `GET /api/auth/me` — current user (Bearer access token)
- `GET/POST/PATCH/DELETE /api/servers` — profiles; create/update/delete admin-only; members see profiles they **own** or that are **shared** with them
- `GET/PUT /api/servers/<id>/access` — owner or admin: who can **view** (read-only) the profile
- `GET /api/servers/<id>/stats` — CPU/RAM snapshot from Docker stats
- `GET /api/servers/<id>/config` / `GET .../config/files` — read config (anyone with access); `PUT .../config` — **admin only**
- Socket.IO: connect with `token` (query or `auth`), emit `join_console` with `{ profile_id }` for log lines (`log_line`)
- Bans under `/api/servers/<id>/bans` — list for anyone with access; mutations **admin only**

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs backend tests, frontend lint/build, and Docker image builds on pushes to `main` and on pull requests.

## “No container” right after Start

After **Start** returns `202`, the backend creates the container in a **background thread**. Until `docker pull` / `docker run` finishes, **`docker ps` and `docker compose exec … list` can be empty** — that is normal for several minutes. Watch **`docker compose logs -f backend`**. If creation fails, the UI shows **`last_docker_error`** on the server detail page after the next refresh.

## Troubleshooting: `launchermeta.mojang.com` / `Connection refused` / SSL errors in logs

The `itzg/minecraft-server` image **must download** version metadata and the server jar from **Mojang over HTTPS**. If logs show:

- `Connection refused: launchermeta.mojang.com:443`
- `SSLHandshakeException` / `Connection closed while SSL/TLS handshake was in progress`

then **outbound HTTPS from inside the game container** is blocked or broken. This is a **network environment** issue, not a bug in the dashboard.

**Try in order:**

1. **Host test** (PowerShell):  
   `Invoke-WebRequest -Uri "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json" -UseBasicParsing`  
   If this fails on the host, fix VPN, firewall, or ISP before debugging Docker.

2. **Disable VPN** and pause **antivirus HTTPS scanning** / **SSL inspection** for a test (some tools break Java’s TLS inside containers).

3. **Custom DNS for game containers** — in `.env` set:  
   `GAME_CONTAINER_DNS=8.8.8.8,1.1.1.1`  
   Then `docker compose up -d --build` and **Remove container** → **Start** again so the new container picks up DNS.

4. **Corporate proxy** — set proxy variables on the **server profile** `env_vars` (via API `PATCH /api/servers/<id>`) if your org requires it, e.g. `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY` as supported by the image/your policy.

5. **Docker Desktop** → Settings → **Resources / Network**: try resetting to defaults or updating Docker Desktop.

## Troubleshooting: Minecraft container stuck on `Restarting`

1. See why it exited: `docker logs --tail 80 gsm-server-1` (replace `1` with your profile id).
2. Common causes: missing **`EULA=TRUE`**, missing **`TYPE`** (e.g. `VANILLA`), or too little **`MEMORY`** for the JVM.
3. In the UI (server detail), use **Remove container** (calls `POST /api/servers/<id>/container/remove`), then **Start** again. Your world under the profile volume is not deleted. CLI equivalent: `docker rm -f gsm-server-<id>`.
4. Ensure **Docker Desktop** has enough RAM (e.g. 4 GB+) in Settings → Resources.

## License

MIT (or your choice; this sample project ships without a formal license file unless you add one).
