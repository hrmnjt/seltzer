# Seltzer

Kanban for issues and ideas that runs entirely inside Databricks. Cards land in **Maybe?**, get
triaged into coloured columns, and close into **Done**; anything nobody touches drifts into
**Not Now** on its own. Golden tickets, stamps, stacked notifications and search included.

- **App**: FastAPI + React on Databricks Apps, signed in through the workspace.
- **Data**: Lakebase Postgres (Autoscaling); attachments in a Unity Catalog volume.
- **Jobs**: an hourly Lakeflow Job auto-postpones idle cards.
- **Deploy**: one bundle (`databricks.yml`) with `dev` and `prod` targets.

The spec, decisions and open spikes are in [docs/spec.md](docs/spec.md).

## Run it on a Mac

**Just look at the UI.** No database needed: this runs the real interface on sample data in
your browser, with changes reset on reload.

```sh
brew install node
cd frontend && npm ci && npm run dev:demo  # opens http://localhost:5173/demo.html
```

**Run the whole app.** You need [Docker Desktop](https://www.docker.com/products/docker-desktop/)
(or OrbStack) for Postgres, plus `brew install uv node`. uv fetches Python 3.11+ itself.

```sh
docker compose up -d                       # Postgres 16 with seltzer and seltzer_test databases

cd frontend && npm ci && npm run build && cd ..   # the UI, built into the backend

cd backend
cp .env.example .env                       # set SELTZER_DEV_USER_EMAIL to your email
uv sync
uv run python -m seltzer.serve             # http://localhost:8000 (runs migrations on start)
```

In a second terminal, from `backend/`:

```sh
uv run python scripts/seed.py              # a demo board with four people
uv run seltzer-sweep                       # run the hourly auto-postpone job once
```

For UI work, also run `npm run dev` in `frontend/` and open http://localhost:5173. It reloads on
save and forwards `/api` to port 8000.

Notes:

- Locally there is no Databricks proxy, so `SELTZER_DEV_USER_EMAIL` says who you are, and emails
  in `SELTZER_DEV_OWNER_EMAILS` count as members of the owner group. To act as someone else,
  change the email and restart, or send an `X-Seltzer-Dev-User` header. All of this is ignored
  unless `SELTZER_ENV=local`.
- Port 5432 taken by Postgres.app or Homebrew Postgres? Stop it, or change the port in
  `docker-compose.yml` and set `PGPORT` in `.env`.
- Attachments land in `backend/.seltzer-files/` instead of a Unity Catalog volume.

## Test

```sh
cd backend && uv run pytest && uv run ruff check . && uv run mypy seltzer
cd frontend && npm run typecheck && npm test
```

Backend tests run against the `seltzer_test` database (override with `TEST_PG*` variables).

## Deploy

```sh
npm --prefix frontend run build            # the UI ships inside the app's source
databricks bundle validate -t dev
databricks bundle deploy -t dev
databricks bundle run seltzer -t dev
```

Before the first deploy, create the `seltzer` schema in your catalog (or set `--var schema=…`) and
a `seltzer-users` group for the people who should get in. Bundle variables, defaults and the
spikes still to confirm in a real workspace are listed in `databricks.yml` and
[docs/spec.md](docs/spec.md#open-questions-and-spikes).

CI (`.github/workflows/ci.yml`) deploys to `dev` on every merge to `main` once the repository has
a `DATABRICKS_HOST` variable; until then that step is skipped. It authenticates with
`DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` from the `dev` environment. Prod deploys
are manual.

## Credits

Seltzer's ideas come from Fizzy and Kan; no code does. See [NOTICE](NOTICE).
