# Seltzer

Kanban for issues and ideas that runs entirely inside Databricks. Cards land in **Maybe?**, get
triaged into coloured columns, and close into **Done**; anything nobody touches drifts into
**Not Now** on its own. Golden tickets, stamps, stacked notifications and search included.

- **App**: FastAPI + React on Databricks Apps, signed in through the workspace.
- **Data**: Lakebase Postgres (Autoscaling); attachments in a Unity Catalog volume.
- **Jobs**: an hourly Lakeflow Job auto-postpones idle cards.
- **Deploy**: one bundle (`databricks.yml`) with `dev` and `prod` targets.

The spec, decisions and open spikes are in [docs/spec.md](docs/spec.md).

## Run it locally

You need Docker (or any Postgres 16), [uv](https://docs.astral.sh/uv/) and Node 22.

```sh
docker compose up -d                       # Postgres with seltzer and seltzer_test databases

cd frontend && npm ci && npm run build && cd ..

cd backend
cp .env.example .env                       # pick the email you want to be
uv sync
uv run python -m seltzer.serve             # http://localhost:8000
uv run python scripts/seed.py              # optional: a demo board (in another shell)
```

For UI work, run `npm run dev` in `frontend/` as well and open http://localhost:5173.

Locally there is no Databricks proxy, so `SELTZER_DEV_USER_EMAIL` says who you are. Emails in
`SELTZER_DEV_OWNER_EMAILS` count as members of the owner group. Both are ignored outside
`SELTZER_ENV=local`.

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

CI (`.github/workflows/ci.yml`) deploys to `dev` on every merge to `main`, using
`DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` from the `dev`
environment. Prod deploys are manual.

## Credits

Seltzer's ideas come from Fizzy and Kan; no code does. See [NOTICE](NOTICE).
