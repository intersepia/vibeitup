"""FastAPI application and optional production Vue SPA, served from one origin."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config import PROJECT_ROOT, Settings
from backend.routers.api import router
from backend.services.library import Library
from backend.services.process_lock import LibraryProcessLock
from backend.services.security import LibraryError
from backend.services.thumbnails import Thumbnails

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, frontend_path: Path | None = None) -> FastAPI:
    config = settings or Settings.load()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await run_in_threadpool(config.initialize)
        process_lock = LibraryProcessLock(config.metadata_path / "instance.lock")
        await run_in_threadpool(process_lock.acquire)
        try:
            library = await run_in_threadpool(Library, config)
            app.state.library = library
            app.state.thumbnails = Thumbnails(config, library.paths)
            if config.index_on_startup:
                await run_in_threadpool(library.rebuild)
            yield
        finally:
            await run_in_threadpool(process_lock.release)

    app = FastAPI(title="Folio · Image Sorting System", version="1.0.0", lifespan=lifespan)

    @app.exception_handler(LibraryError)
    async def library_error_handler(request: Request, exc: LibraryError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @app.exception_handler(OSError)
    async def filesystem_error_handler(request: Request, exc: OSError):
        logger.error("Dateisystemfehler bei %s", request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Dateisystem nicht verfügbar. Bitte Zugriffsrechte und freien Speicher prüfen."
            },
        )

    @app.middleware("http")
    async def same_origin_and_security(request: Request, call_next):
        # No permissive CORS. Reject browser mutations from unrelated origins,
        # while allowing same-origin reverse proxies and native CLI clients.
        if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if request.headers.get("sec-fetch-site") == "cross-site" or (
                origin and urlparse(origin).netloc != request.headers.get("host", "")
            ):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Zugriff von einer fremden Website ist nicht erlaubt."},
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    app.include_router(router)
    build = frontend_path or PROJECT_ROOT / "frontend" / "dist"
    if (build / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=build / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        # Unknown API endpoints must return JSON 404, never the SPA shell.
        if path == "api" or path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "API-Endpunkt nicht gefunden."})
        if (build / "index.html").is_file():
            if path == "favicon.svg" and (build / "favicon.svg").is_file():
                return FileResponse(build / "favicon.svg", media_type="image/svg+xml")
            return FileResponse(build / "index.html", headers={"Cache-Control": "no-cache"})
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Frontend noch nicht gebaut. Bitte ./start.sh starten oder npm run dev im frontend-Ordner ausführen.",
                "api_docs": "/docs",
            },
        )

    return app


app = create_app()
