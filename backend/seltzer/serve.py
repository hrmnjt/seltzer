"""Entry point for Databricks Apps: `python -m seltzer.serve`.

Apps tell the process which port to listen on through DATABRICKS_APP_PORT.
"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    port = int(os.environ.get("DATABRICKS_APP_PORT", "8000"))
    uvicorn.run(
        "seltzer.main:app",
        host="0.0.0.0",
        port=port,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_level=os.environ.get("SELTZER_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
