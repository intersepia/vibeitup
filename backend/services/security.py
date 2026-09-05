"""All browser paths are relative, POSIX-style paths beneath the library."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from backend.config import IMAGE_EXTENSIONS, MANAGED_ROOTS


class LibraryError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class SafePaths:
    def __init__(self, base: Path) -> None:
        self.base = base.resolve()

    def resolve(self, value: str, *, roots: tuple[str, ...] = MANAGED_ROOTS, exists: bool = True) -> Path:
        if not value or "\\" in value or ":" in value or "\x00" in value or value.startswith("/"):
            raise LibraryError("Ungültiger relativer Pfad.")
        parts = value.split("/")
        if any(part in ("", ".", "..") or part.startswith(".") for part in parts):
            raise LibraryError("Versteckte Pfade und Pfad-Traversal sind nicht erlaubt.")
        if parts[0] not in roots:
            raise LibraryError("Dieser Ordner ist für die Aktion nicht freigegeben.")
        current = self.base
        for part in parts:
            current = current / part
            # Check every component, including links that point back inside the base.
            if current.is_symlink():
                raise LibraryError("Symbolische Links sind nicht erlaubt.")
        resolved = current.resolve()
        if not resolved.is_relative_to(self.base):
            raise LibraryError("Der Pfad liegt außerhalb der Bibliothek.")
        if exists and not resolved.exists():
            raise LibraryError("Die Datei oder der Ordner wurde nicht gefunden. Bitte neu einlesen.", 404)
        return resolved

    def image(self, value: str, *, roots: tuple[str, ...] = MANAGED_ROOTS) -> Path:
        path = self.resolve(value, roots=roots)
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            raise LibraryError("Der Pfad ist keine unterstützte Bilddatei.", 415)
        return path

    def relative(self, path: Path) -> str:
        return path.relative_to(self.base).as_posix()

    @staticmethod
    def album_name(value: str) -> str:
        name = value.strip()
        # Apply Windows restrictions on every platform for portable libraries.
        if not name or len(name) > 100 or name.startswith(".") or name.endswith((".", " ")):
            raise LibraryError("Bitte einen Albumnamen mit 1–100 Zeichen ohne führenden Punkt verwenden.")
        if re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or name in (".", ".."):
            raise LibraryError("Der Albumname enthält unzulässige Zeichen.")
        stem = name.split(".")[0].upper()
        if stem in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(10)),
            *(f"LPT{i}" for i in range(10)),
        }:
            raise LibraryError("Dieser Albumname ist vom Betriebssystem reserviert.")
        return name

    def album(self, value: str) -> Path:
        if not value or value.startswith("/"):
            raise LibraryError("Bitte ein Zielalbum auswählen.")
        # Nested existing albums are supported; the API uses names relative to alben/.
        for part in PurePosixPath(value).parts:
            self.album_name(part)
        path = self.resolve(f"alben/{value}", roots=("alben",))
        if not path.is_dir():
            raise LibraryError("Das Zielalbum ist kein Ordner.")
        return path
