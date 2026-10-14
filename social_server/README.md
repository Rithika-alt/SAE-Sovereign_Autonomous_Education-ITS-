# SAE Social Server

The one piece of shared infrastructure in an otherwise fully local-first
system. One deployment serves every student's friend requests, presence,
and messages. It never sees lesson content, AI interactions, progress, or
knowledge-graph data — that all stays on each student's own machine.

## Run it

```bash
cd social_server
cp .env.example .env   # only needed for local `uvicorn` runs outside Docker
docker compose up -d
```

API is available at `http://localhost:8000` (interactive docs at `/docs`).
Point every student's `sae_system/.env` at wherever you deploy this:

```env
SOCIAL_SERVER_URL=https://your-deployed-host:8000
```

## Deploying for real students (not just localhost)

Any small VPS or free-tier host that can run two Docker containers works —
Railway, Render, Fly.io, a $5/mo VPS. Put it behind HTTPS (a reverse proxy
like Caddy or the platform's built-in TLS) since students' passwords and
messages travel over this connection. Change `SOCIAL_DB_PASSWORD` in
production — the default in `docker-compose.yml` is a placeholder.

## Scope

- `social_accounts` / `sessions` — a student's *social* identity, entirely
  separate from their local `student_id`. Linking the two is just "same
  email" — this server has no knowledge of local progress/auth data beyond
  what a student explicitly opts to share (see `discoverable`,
  `current_domain`, `current_module` on `PATCH /accounts/me`).
- `friendships` — request/accept/reject.
- `messages` / `rooms` / `room_members` — 1:1 and group chat. Delivery is
  REST + polling (`GET /messages?with=...&since=...`) — no WebSockets in
  this MVP, see the root plan doc for why.
