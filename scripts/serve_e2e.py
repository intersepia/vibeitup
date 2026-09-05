"""Run a disposable test library; browser tests never touch the configured library."""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from backend.config import Settings  # noqa: E402
from backend.main import create_app  # noqa: E402
from scripts.seed_demo import seed_demo  # noqa: E402


def create_test_app() -> FastAPI:
    temporary = TemporaryDirectory(prefix="folio-e2e-")
    try:
        base = Path(temporary.name) / "library"
        seed_demo(base)
        app = create_app(Settings(base))
    except Exception:
        temporary.cleanup()
        raise
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            async with original_lifespan(application):
                yield
        finally:
            # Cleanup in ASGI shutdown, before Uvicorn re-raises SIGTERM.
            # Waiting until process exit would leak test libraries on some versions.
            temporary.cleanup()

    app.router.lifespan_context = lifespan
    return app


if __name__ == "__main__":
    uvicorn.run(
        create_test_app(), host="0.0.0.0", port=int(os.environ.get("E2E_PORT", "8010")), log_level="warning"
    )
