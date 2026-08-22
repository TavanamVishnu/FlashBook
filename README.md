# FlashBook

A concurrent seat-booking engine — FastAPI + PostgreSQL + Redis + JWT +
APScheduler. See [`design.md`](design.md) for the full build story, and
`FlashBook_Project_Report.docx` for the original project write-up.

## Run it

1. **Start Postgres + Redis:**
   ```
   docker compose up -d
   ```

2. **Set up the backend:**
   ```
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r backend/requirements.txt
   cp .env.example .env
   ```

3. **Start the API** (creates tables automatically on first run):
   ```
   cd backend
   set -a; source ../.env; set +a
   uvicorn app.main:app --reload --port 8000
   ```
   API docs: http://127.0.0.1:8000/docs

4. **Serve the frontend** (any static file server works):
   ```
   cd frontend
   python3 -m http.server 5500
   ```
   Open http://127.0.0.1:5500/index.html — sign up, then use the
   [Admin panel](http://127.0.0.1:5500/admin.html) (password: `admin123` by
   default) to create your first event.

5. **Prove the no-double-booking claim:**
   ```
   cd backend
   python tests/load_test.py --requests 300 --seat-id <some available seat id>
   ```

## Project layout

```
backend/app/       FastAPI app: models, routes, auth, Redis lock, worker
backend/tests/     load_test.py — the concurrency proof
frontend/          plain HTML/CSS/JS, no build step (edit these files)
docs/              a copy of frontend/, served by GitHub Pages (see below)
docker-compose.yml Postgres (port 5544) + Redis (port 6380)
```

## Hosting it from GitHub

GitHub itself only serves static files, so the plain HTML/CSS/JS frontend can
live on **GitHub Pages** — but the FastAPI backend, Postgres, and Redis need a
real server to run on. Here's the simplest split:

### 1. Frontend — GitHub Pages

This repo's `docs/` folder is a plain copy of `frontend/` (GitHub Pages can
only serve from a repo's root or its `docs/` folder, so that's the one it
points at). In the repo on GitHub: **Settings → Pages → Source → Deploy from
a branch → branch `rebuild`, folder `/docs`**. After a minute or two your
site is live at `https://<your-username>.github.io/FlashBook/`.

If you change anything in `frontend/`, copy it into `docs/` again before
pushing:
```
rm -rf docs && cp -r frontend docs
```

### 2. Backend — a small always-on host (Render, Railway, etc.)

Free options change over time, so check current pricing when you set this
up, but the general steps on a host like Render or Railway are the same:

1. Create a new **Web Service**, connect this GitHub repo, branch `rebuild`.
2. Root directory: `backend`. Build command: `pip install -r requirements.txt`.
   Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
3. Add a managed **PostgreSQL** database and a managed **Redis** instance
   (Upstash's free Redis works well too), and set these environment
   variables on the web service from `.env.example`:
   - `DATABASE_URL` — use the `postgresql+psycopg://...` form (see `.env.example`)
   - `REDIS_URL`
   - `JWT_SECRET` — set this to something random, not the example value
   - `ADMIN_PASSWORD`
4. Once it's deployed, you'll have a live backend URL. Put that URL into
   `API_BASE` in `frontend/js/api.js` (and `docs/js/api.js`), then commit
   and push — GitHub Pages will pick up the change automatically.
