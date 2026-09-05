"""Persistent, incremental SHA-1 indexing. No shell tools or external services."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import time
from collections import defaultdict
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from backend.config import IMAGE_EXTENSIONS, MANAGED_ROOTS
from backend.services.security import LibraryError, SafePaths

logger = logging.getLogger(__name__)
INDEX_VERSION = 1


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def signature(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "ctime_ns": stat.st_ctime_ns}


def sha1_file(path: Path) -> str:
    """Read in bounded chunks; SHA-1 is used for exact identity, not security."""
    digest = hashlib.sha1(usedforsecurity=False)
    before = signature(path)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if signature(path) != before:
        raise LibraryError("Eine Datei wurde während des Lesens verändert. Bitte erneut versuchen.", 409)
    return digest.hexdigest()


def iter_images(root: Path) -> Iterator[Path]:
    """Never follow symlinks, hidden directories, or directory junctions outside root."""
    for directory, folders, files in os.walk(root, followlinks=False):
        folders[:] = sorted(
            name
            for name in folders
            if not name.startswith(".")
            and not (Path(directory) / name).is_symlink()
            and (Path(directory) / name).resolve().is_relative_to(root.resolve())
        )
        for name in sorted(files):
            path = Path(directory) / name
            if not name.startswith(".") and path.suffix.lower() in IMAGE_EXTENSIONS and not path.is_symlink():
                yield path


class ImageIndex:
    def __init__(self, paths: SafePaths, index_path: Path) -> None:
        self.paths = paths
        self.path = index_path
        self.entries: dict[str, dict[str, Any]] = {}
        self.album_hashes: dict[str, list[str]] = {}
        self.indexed_at: str | None = None
        self.skipped = 0
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("version") != INDEX_VERSION or not isinstance(data.get("files"), dict):
                raise ValueError("Invalid index version or structure")
            # Cache is untrusted. Only accept valid metadata, never paths for file operations.
            entries = data["files"]
            for key, entry in entries.items():
                if not isinstance(key, str) or not isinstance(entry, dict):
                    raise ValueError("Invalid cache entry")
                if not all(isinstance(entry.get(field), int) for field in ("size", "mtime_ns", "ctime_ns")):
                    raise ValueError("Invalid file signature")
                if not isinstance(entry.get("sha1"), str) or not re.fullmatch(r"[a-f0-9]{40}", entry["sha1"]):
                    raise ValueError("Invalid hash")
                if any(
                    entry.get(field) is not None and (not isinstance(entry[field], int) or entry[field] <= 0)
                    for field in ("width", "height")
                ):
                    raise ValueError("Invalid image dimensions")
                self.paths.resolve(key, exists=False)
            self.entries = entries
            self.indexed_at = data.get("indexed_at")
            self._album_lookup()
        except (OSError, ValueError, TypeError, AttributeError, LibraryError):
            logger.warning("Index unlesbar; er wird neu aufgebaut.", exc_info=True)
            self.entries = {}

    def _album_lookup(self) -> None:
        lookup: dict[str, list[str]] = defaultdict(list)
        for path, entry in self.entries.items():
            if path.startswith("alben/"):
                lookup[entry["sha1"]].append(path)
        self.album_hashes = dict(lookup)

    def rebuild(self) -> dict[str, Any]:
        started = time.monotonic()
        next_entries: dict[str, dict[str, Any]] = {}
        hashed = cached = skipped = 0
        for root in MANAGED_ROOTS:
            directory = self.paths.resolve(root)
            for path in iter_images(directory):
                try:
                    relative = self.paths.relative(path)
                    self.paths.image(relative)
                    stat = signature(path)
                    old = self.entries.get(relative)
                    if old and all(old.get(key) == value for key, value in stat.items()):
                        entry = old
                        cached += 1
                    else:
                        digest = sha1_file(path)
                        width = height = None
                        try:
                            with Image.open(path) as image:
                                width, height = image.size
                                if image.getexif().get(274, 1) in (5, 6, 7, 8):
                                    width, height = height, width
                        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
                            logger.info("Keine lesbare Bildvorschau: %s", relative)
                        if signature(path) != stat:
                            raise LibraryError("Datei während der Indexierung verändert.", 409)
                        entry = {**stat, "sha1": digest, "width": width, "height": height}
                        hashed += 1
                    next_entries[relative] = entry
                except (OSError, LibraryError):
                    skipped += 1
                    logger.warning("Bild konnte nicht indexiert werden: %s", path, exc_info=True)
        timestamp = utc_now()
        # Publish the completed scan even if persisting the cache fails (e.g. disk full).
        # File operations and their journal are independent of this regenerable cache.
        self.entries = next_entries
        self.indexed_at = timestamp
        self.skipped = skipped
        self._album_lookup()
        payload = {"version": INDEX_VERSION, "indexed_at": timestamp, "files": next_entries}
        fd, temporary = tempfile.mkstemp(prefix="index-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        report = {
            "total": len(next_entries),
            "hashed": hashed,
            "cached": cached,
            "skipped": skipped,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "indexed_at": timestamp,
        }
        logger.info("Index aktualisiert: %s", report)
        return report

    def duplicates(self, path: str) -> list[str]:
        entry = self.entries.get(path)
        if not entry or not path.startswith("zur_sortieren/"):
            return []
        return self.album_hashes.get(entry["sha1"], [])
