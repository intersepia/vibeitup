from __future__ import annotations

import mimetypes
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse

from backend.models.schemas import (
    AlbumRequest,
    FileSelection,
    FolderNode,
    ImageList,
    IndexReport,
    LibraryStatus,
    MoveRequest,
    TransactionInfo,
)
from backend.services.library import Library

router = APIRouter(prefix="/api")


def get_library(request: Request) -> Library:
    return request.app.state.library


LibraryDependency = Annotated[Library, Depends(get_library)]


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "application": "folio"}


@router.get("/status", response_model=LibraryStatus)
def status(library: LibraryDependency) -> dict[str, Any]:
    return library.status()


@router.get("/folders/source", response_model=FolderNode)
def source_folders(library: LibraryDependency) -> dict[str, Any]:
    return library.folder("zur_sortieren")


@router.get("/folders/albums", response_model=list[FolderNode])
def albums(library: LibraryDependency) -> list[dict[str, Any]]:
    return library.albums()


@router.post("/folders/albums", response_model=FolderNode, status_code=201)
def create_album(body: AlbumRequest, library: LibraryDependency) -> dict[str, Any]:
    return library.create_album(body.name, body.parent)


@router.get("/images", response_model=ImageList)
def images(
    library: LibraryDependency, path: str = "zur_sortieren", recursive: bool = False
) -> dict[str, Any]:
    return library.images(path, recursive)


@router.get("/thumb/{path:path}")
def thumbnail(path: str, request: Request) -> FileResponse:
    target = request.app.state.thumbnails.get(path)
    return FileResponse(
        target, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=0, must-revalidate"}
    )


@router.get("/preview/{path:path}")
def preview(path: str, request: Request) -> FileResponse:
    target = request.app.state.thumbnails.preview(path)
    return FileResponse(
        target, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=0, must-revalidate"}
    )


@router.get("/image/{path:path}")
def original(path: str, library: LibraryDependency) -> FileResponse:
    file = library.paths.image(path)
    return FileResponse(
        file,
        media_type=mimetypes.guess_type(file.name)[0] or "application/octet-stream",
        headers={"Cache-Control": "private, no-cache", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/index", response_model=IndexReport)
def rebuild_index(library: LibraryDependency) -> dict[str, Any]:
    return library.rebuild()


@router.post("/action/move", response_model=TransactionInfo)
def move(body: MoveRequest, library: LibraryDependency) -> dict[str, Any]:
    return library.move(body.files, "move", body.target_album)


@router.post("/action/trash", response_model=TransactionInfo)
def trash(body: FileSelection, library: LibraryDependency) -> dict[str, Any]:
    return library.move(body.files, "trash")


@router.post("/action/duplicates", response_model=TransactionInfo)
def duplicates(body: FileSelection, library: LibraryDependency) -> dict[str, Any]:
    return library.move(body.files, "duplicates")


@router.post("/action/undo", response_model=TransactionInfo)
def undo(library: LibraryDependency) -> dict[str, Any]:
    return library.undo()


@router.get("/logs", response_model=list[TransactionInfo])
def logs(
    library: LibraryDependency, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)
) -> list[dict[str, Any]]:
    return library.journal.list(limit, offset)
