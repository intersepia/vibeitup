"""Portable, non-destructive filename allocation for a whole move batch."""

from __future__ import annotations

import os
import unicodedata
from pathlib import Path

from backend.services.security import LibraryError


def name_key(name: str) -> str:
    # Reserve equivalent spellings even on case-sensitive Linux filesystems.
    # This also avoids intra-batch collisions on macOS/Windows target volumes.
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", name).casefold())


class DestinationNames:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.occupied = {name_key(child.name) for child in directory.iterdir()}
        self.max_bytes = 255
        if hasattr(os, "pathconf"):
            try:
                limit = os.pathconf(directory, "PC_NAME_MAX")
                if limit > 0:
                    self.max_bytes = min(self.max_bytes, limit)
            except (OSError, ValueError):
                # Windows and some filesystems do not expose a name limit.
                pass

    def _fits(self, name: str) -> bool:
        return len(os.fsencode(name)) <= self.max_bytes and len(name.encode("utf-16-le")) // 2 <= 255

    def _numbered(self, name: str, counter: int) -> str:
        path = Path(name)
        ending = f"_{counter:03d}{path.suffix}"
        stem = path.stem
        while stem and not self._fits(stem + ending):
            # Trim complete Unicode code points, never encoded byte sequences.
            stem = stem[:-1]
        if not stem:
            raise LibraryError("Für diesen Dateinamen ist auf dem Zieldatenträger nicht genug Platz.", 409)
        return stem + ending

    def allocate(self, name: str) -> Path:
        candidate = name
        counter = 0
        while True:
            if self._fits(candidate):
                path = self.directory / candidate
                key = name_key(candidate)
                if key not in self.occupied and not path.exists() and not path.is_symlink():
                    self.occupied.add(key)
                    return path
                self.occupied.add(key)
            counter += 1
            candidate = self._numbered(name, counter)
