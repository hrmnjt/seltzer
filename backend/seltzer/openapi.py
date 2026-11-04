"""Print the OpenAPI schema: `python -m seltzer.openapi > ../frontend/openapi.json`.

The frontend generates its TypeScript types from this file, and CI fails if
the committed copy drifts from the backend.
"""

from __future__ import annotations

import json
import sys

from seltzer.config import Settings
from seltzer.main import create_app


def main() -> None:
    app = create_app(Settings(seltzer_env="local", seltzer_run_migrations=False))
    json.dump(app.openapi(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
