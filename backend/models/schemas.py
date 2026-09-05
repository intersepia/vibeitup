from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FileSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files: list[str] = Field(min_length=1, max_length=500)


class MoveRequest(FileSelection):
    target_album: str = Field(min_length=1, max_length=500)


class AlbumRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    parent: str = Field(
        default="",
        max_length=500,
        description="Existing parent folder relative to alben/. Empty for the album root.",
    )


class FolderNode(BaseModel):
    name: str
    path: str
    count: int
    direct_count: int
    children: list[FolderNode] = Field(default_factory=list)


class ImageInfo(BaseModel):
    path: str
    name: str
    size: int
    width: int | None = None
    height: int | None = None
    sha1: str
    is_duplicate: bool
    duplicate_of: list[str] = Field(default_factory=list)
    modified_at: str
    format: str


class ImageList(BaseModel):
    path: str
    images: list[ImageInfo]
    total: int
    total_size: int


class MoveInfo(BaseModel):
    source: str
    destination: str
    sha1: str
    size: int


class TransactionInfo(BaseModel):
    id: str
    action: str
    status: str
    created_at: str
    undone_at: str | None = None
    error: str | None = None
    files: list[MoveInfo]


class IndexReport(BaseModel):
    total: int
    hashed: int
    cached: int
    skipped: int
    duration_ms: int
    indexed_at: str | None


class LibraryStatus(BaseModel):
    base_path: str
    source_count: int
    source_size: int
    album_count: int
    album_images: int
    duplicate_count: int
    duplicate_files: int
    trash_count: int
    total_size: int
    can_undo: bool
    last_indexed_at: str | None
    skipped_files: int
    index_warning: str | None = None
    demo: bool
