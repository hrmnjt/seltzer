"""The Seltzer app: the JSON API under /api plus the built React app."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from seltzer.api import activity, boards, cards, people
from seltzer.config import Settings, get_settings
from seltzer.db.engine import Database, make_async_engine
from seltzer.domain.errors import Problem
from seltzer.files import make_store
from seltzer.identity import make_directory

log = logging.getLogger("seltzer")
PROBLEM = "application/problem+json"
DEFAULT_STATIC = Path(__file__).resolve().parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.seltzer_run_migrations:
            from seltzer.migrate import upgrade

            await run_in_threadpool(upgrade, settings)
        app.state.db = Database(make_async_engine(settings))
        app.state.store = make_store(settings)
        app.state.directory = make_directory(settings)
        yield
        await app.state.db.dispose()

    app = FastAPI(
        title="Seltzer",
        version="0.1.0",
        summary="Kanban for issues and ideas, on Databricks.",
        lifespan=lifespan,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.settings = settings

    @app.exception_handler(Problem)
    async def problem_handler(request: Request, exc: Problem) -> JSONResponse:
        return JSONResponse(exc.body(), status_code=exc.status, media_type=PROBLEM)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        body = {"type": "about:blank", "title": "Invalid request", "status": 422, "errors": errors}
        return JSONResponse(body, status_code=422, media_type=PROBLEM)

    @app.exception_handler(HTTPException)
    async def http_handler(request: Request, exc: HTTPException) -> JSONResponse:
        body = {"type": "about:blank", "title": str(exc.detail), "status": exc.status_code}
        return JSONResponse(body, status_code=exc.status_code, media_type=PROBLEM)

    for router in (people.router, boards.router, cards.router, activity.router):
        app.include_router(router, prefix="/api")

    @app.get("/api/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    _mount_frontend(
        app, Path(settings.seltzer_static_dir) if settings.seltzer_static_dir else DEFAULT_STATIC
    )
    return app


def _mount_frontend(app: FastAPI, static: Path) -> None:
    """Serve the Vite build; unknown non-API paths get index.html for client routing."""
    index = static / "index.html"
    if not index.exists():
        log.info("no frontend build at %s; serving the API only", static)
        return
    if (static / "assets").exists():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:  # sync: file checks run in the threadpool
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (static / path).resolve()
        if path and candidate.is_file() and static.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


app = create_app()
