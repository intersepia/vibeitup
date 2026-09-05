"""Native configuration, independent of the current working directory."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANAGED_ROOTS = ("zur_sortieren", "alben", "duplikate", "trash")
IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".avif"})


@dataclass(frozen=True)
class Settings:
    base_path: Path
    host: str = "127.0.0.1"
    port: int = 8000
    index_on_startup: bool = True
    thumbnail_size: int = 400

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_path", Path(self.base_path).expanduser().resolve())

    @property
    def metadata_path(self) -> Path:
        return self.base_path / ".image-sorter"

    @classmethod
    def load(cls, config_path: Path | None = None) -> Settings:
        default = PROJECT_ROOT / "config.local.yaml"
        if not default.exists():
            default = PROJECT_ROOT / "config.yaml"
        path = Path(config_path or os.environ.get("IMAGE_SORTER_CONFIG", default)).expanduser().resolve()
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("Die Konfiguration muss ein YAML-Objekt sein.")
        base_value = os.environ.get("IMAGE_SORTER_BASE_PATH", raw.get("base_path", "./data"))
        if not isinstance(base_value, str) or not base_value.strip():
            raise ValueError("base_path muss ein nichtleerer Pfad sein.")
        base = Path(base_value).expanduser()
        if not base.is_absolute():
            base = path.parent / base
        server = raw.get("server", {})
        if not isinstance(server, dict):
            raise ValueError("server muss ein YAML-Objekt sein.")
        port = int(os.environ.get("PORT", server.get("port", 8000)))
        if not 1 <= port <= 65535:
            raise ValueError("Der Port muss zwischen 1 und 65535 liegen.")
        size = int(raw.get("thumbnail_size", 400))
        if not 32 <= size <= 400:
            raise ValueError("thumbnail_size muss zwischen 32 und 400 liegen.")
        on_startup = raw.get("index_on_startup", True)
        if not isinstance(on_startup, bool):
            raise ValueError("index_on_startup muss true oder false sein.")
        return cls(
            base_path=base.resolve(),
            host=os.environ.get("HOST", str(server.get("host", "127.0.0.1"))),
            port=port,
            index_on_startup=on_startup,
            thumbnail_size=size,
        )

    def initialize(self) -> None:
        self.base_path.mkdir(parents=True, exist_ok=True)
        # Do not follow links in any application-owned directory.
        for relative in (
            *MANAGED_ROOTS,
            "temp",
            "temp/duplikat",
            "temp/trash",
            ".image-sorter",
            ".image-sorter/thumbnails",
        ):
            current = self.base_path
            for part in Path(relative).parts:
                current = current / part
                if current.is_symlink() or not current.resolve().is_relative_to(self.base_path):
                    raise ValueError(f"Verknüpfungen in verwalteten Ordnern sind nicht erlaubt: {relative}")
                current.mkdir(exist_ok=True)
        for name in ("index.json", "journal.sqlite3", "journal.sqlite3-wal", "journal.sqlite3-shm"):
            if (self.metadata_path / name).is_symlink():
                raise ValueError("Metadaten dürfen keine symbolischen Links sein.")
