"""Runtime settings, read from the environment (app.yaml in Databricks, .env locally)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # "local" enables fake identity headers and the local attachment store.
    seltzer_env: Literal["local", "test", "dev", "prod"] = "prod"

    # Postgres. In Databricks Apps the Lakebase resource sets the PG* variables;
    # ENDPOINT_NAME (projects/{p}/branches/{b}/endpoints/{e}) is set in app.yaml.
    pghost: str = "localhost"
    pgport: int = 5432
    pgdatabase: str = "seltzer"
    pguser: str = "postgres"
    pgpassword: str | None = None
    pgsslmode: str = "prefer"
    endpoint_name: str | None = None
    db_pool_size: int = 5
    db_max_overflow: int = 5

    # Identity. Members of this Databricks group become Seltzer owners on sign-in.
    seltzer_owner_group: str = "admins"
    # Local only: who you are when no proxy headers arrive, and who counts as
    # a member of the owner group.
    seltzer_dev_user_email: str | None = None
    seltzer_dev_owner_emails: str = ""

    # Attachments. In Databricks this is the UC volume, as "catalog.schema.volume" (what an
    # app resource's value_from gives) or as a /Volumes/<catalog>/<schema>/<volume> path.
    seltzer_volume: str | None = None
    seltzer_local_files_dir: str = ".seltzer-files"
    seltzer_max_upload_mb: int = 25

    seltzer_run_migrations: bool = True
    # Postgres roles (comma-separated) granted read/write on Seltzer's tables after each
    # migration, e.g. the role the sweep job connects as when it isn't the app's own.
    seltzer_db_grant_roles: str = ""
    seltzer_static_dir: str | None = None

    # Lists and pages
    page_size: int = Field(default=50, ge=1, le=200)

    @property
    def is_local(self) -> bool:
        return self.seltzer_env in ("local", "test")

    @property
    def uses_lakebase_tokens(self) -> bool:
        return self.endpoint_name is not None and self.pgpassword is None

    @property
    def volume_root(self) -> str | None:
        v = (self.seltzer_volume or "").strip().rstrip("/")
        if not v:
            return None
        if v.startswith("/"):
            return v
        parts = v.split(".")
        if len(parts) != 3 or not all(parts):
            raise ValueError("SELTZER_VOLUME must be catalog.schema.volume or a /Volumes path")
        return "/Volumes/" + "/".join(parts)

    @property
    def grant_roles(self) -> list[str]:
        return [r.strip() for r in self.seltzer_db_grant_roles.split(",") if r.strip()]

    @property
    def dev_owner_emails(self) -> set[str]:
        return {e.strip().lower() for e in self.seltzer_dev_owner_emails.split(",") if e.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
