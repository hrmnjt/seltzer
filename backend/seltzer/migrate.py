"""Run Alembic migrations under a Postgres advisory lock, so when several app
instances start at once only one migrates and the rest wait for it."""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, text

from seltzer.config import Settings
from seltzer.db.engine import make_sync_engine

log = logging.getLogger(__name__)

MIGRATION_LOCK = 0x5E17_0001
BACKEND_DIR = Path(__file__).resolve().parent.parent


def alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


def grant(conn: Connection, role: str) -> None:
    """Let another Postgres role (such as the sweep job's) read and write Seltzer's tables."""
    quoted = conn.dialect.identifier_preparer.quote(role)
    for stmt in (
        f"GRANT USAGE ON SCHEMA public TO {quoted}",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {quoted}",
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {quoted}",
    ):
        conn.execute(text(stmt))
    log.info("granted table access to %s", role)


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
                for role in settings.grant_roles:
                    grant(conn, role)
                conn.commit()
            finally:
                conn.execute(text("select pg_advisory_unlock(:k)"), {"k": MIGRATION_LOCK})
                conn.commit()
    finally:
        engine.dispose()
    log.info("database is at %s", revision)
