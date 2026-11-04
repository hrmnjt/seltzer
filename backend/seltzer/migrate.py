"""Run Alembic migrations under a Postgres advisory lock, so when several app
instances start at once only one migrates and the rest wait for it."""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from seltzer.config import Settings
from seltzer.db.engine import make_sync_engine

log = logging.getLogger(__name__)

MIGRATION_LOCK = 0x5E17_0001
BACKEND_DIR = Path(__file__).resolve().parent.parent


def alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


def upgrade(settings: Settings, revision: str = "head") -> None:
    engine = make_sync_engine(settings)
    try:
        with engine.connect() as conn:
            conn.execute(text("select pg_advisory_lock(:k)"), {"k": MIGRATION_LOCK})
            conn.commit()
            try:
                cfg = alembic_config()
                cfg.attributes["connection"] = conn
                command.upgrade(cfg, revision)
                conn.commit()
            finally:
                conn.execute(text("select pg_advisory_unlock(:k)"), {"k": MIGRATION_LOCK})
                conn.commit()
    finally:
        engine.dispose()
    log.info("database is at %s", revision)
