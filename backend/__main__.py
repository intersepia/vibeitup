"""python -m backend: the native single-process application."""

import uvicorn

from backend.config import Settings

if __name__ == "__main__":
    settings = Settings.load()
    uvicorn.run("backend.main:app", host=settings.host, port=settings.port, workers=1)
