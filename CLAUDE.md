# Seltzer: build brief

Seltzer is a kanban tracker for issues and ideas that feels like Fizzy and runs entirely inside
Databricks: FastAPI + React on Databricks Apps, Lakebase Postgres, a UC volume for attachments and
an hourly Lakeflow Job. The full spec, decisions and open spikes are in `docs/spec.md`; read the
relevant section before changing behaviour.

## Stack

- Backend (`backend/`): Python 3.11+, FastAPI, Pydantic 2, SQLAlchemy 2 (async, psycopg 3),
  Alembic, databricks-sdk. Managed with uv.
- Frontend (`frontend/`): React 19, TypeScript, Vite, TanStack Router and Query, dnd-kit, Tiptap,
  Radix UI, Tailwind 4 on our own tokens (`src/styles.css`).
- Deploy: `databricks.yml` (Declarative Automation Bundle), targets `dev` and `prod`.

## Commands

```sh
docker compose up -d                       # Postgres 16 on :5432 (seltzer / seltzer_test DBs)
cd backend && cp .env.example .env
uv sync
uv run python -m seltzer.serve             # API + built UI on :8000 (migrates on start)
uv run python scripts/seed.py              # demo board
uv run pytest                              # needs Postgres; uses the seltzer_test DB
uv run ruff check . && uv run ruff format --check . && uv run mypy seltzer
uv run alembic revision --autogenerate -m "…" && uv run alembic check

cd frontend && npm ci
npm run dev                                # Vite on :5173, proxies /api to :8000
npm run typecheck && npm test && npm run build   # build lands in backend/seltzer/static
```

After changing an API schema: `cd backend && uv run python -m seltzer.openapi > ../frontend/openapi.json`,
then `cd frontend && npm run api:types`. After changing backend dependencies: re-export
`backend/requirements.txt` (the command is in its first line). CI fails on drift in all three.

## How the code is organised

- `seltzer/domain/` holds every rule. Routers in `seltzer/api/` resolve the user, call one domain
  function, build the response and commit. Don't put rules in routers.
- Every change worth a stamp goes through `domain/activity.record()` in the same transaction: it
  writes the event, touches the card (resets auto-postpone), bumps the board version and fans out
  notifications. A write that changes the board screen without an event still calls
  `ctx.bump_board()`.
- Cards are never positioned. Every lane (Maybe?, a column, Not Now, Done) lists golden cards first,
  then by `last_active_at`; a move records an event, which touches the card, so it lands on top.
  The board keeps Maybe? open beside one focused lane (`components/BoardCanvas.tsx`), as Fizzy does.
- Columns, steps and pins use fractional keys (`seltzer/ordering.py`, mirrored in
  `frontend/src/lib/ordering.ts`). Place them with `domain/positions.place()` using neighbour ids.
- Permissions live in `domain/permissions.py` (`get_board`, `get_card`, `visible_boards`). Every
  endpoint that takes an id goes through one of them.
- Rich text is Tiptap JSON, validated by `seltzer/richtext.py`. The UI renders it with
  `RichTextView`, never as an HTML string.
- Tests hit a real Postgres through the HTTP API (`tests/conftest.py` has `Api` helpers and
  fixtures for several users). Add a test with every rule change.

## Clean-room rules

Fizzy (O'Saasy license) and Kan (AGPL-3.0) are references for behaviour and UX only.

- Never copy code, templates, CSS, icons, illustrations or long UI copy from either project.
  Short common labels such as "Not Now" and "Maybe?" are fine.
- Reading their source to understand a rule is fine; writing code from it line by line is not.
- Every component, style and asset here is written for Seltzer. `NOTICE` credits both as
  inspiration.

## Current milestone

v1 (`docs/spec.md`, Scope) is built and tested locally. Next:

1. Run the Lakebase and job-identity spikes in a dev workspace; adjust the bundle variables.
2. `databricks bundle deploy -t dev`, sign in through the Apps proxy, and run the sweep job once.
3. Then the Later items, starting with stalled-card detection and webhooks.
