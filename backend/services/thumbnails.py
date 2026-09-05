from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import threading
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from backend.config import Settings
from backend.services.indexer import signature
from backend.services.security import LibraryError, SafePaths

logger = logging.getLogger(__name__)


class Thumbnails:
    def __init__(self, settings: Settings, paths: SafePaths) -> None:
        self.paths = paths
        self.size = settings.thumbnail_size
        self.cache = settings.metadata_path / "thumbnails"
        self.lock = threading.Lock()

    def get(self, relative: str) -> Path:
        return self._render(relative, self.size)

    def preview(self, relative: str) -> Path:
        # Browser-safe previews also work for TIFF, CMYK and unsupported codecs.
        return self._render(relative, 1920)

    def _render(self, relative: str, size: int) -> Path:
        source = self.paths.image(relative)
        stat = signature(source)
        key = hashlib.sha1(f"{relative}:{stat}:{size}:v1".encode(), usedforsecurity=False).hexdigest()
        target = self.cache / f"{key}.jpg"
        with self.lock:
            if target.is_symlink():
                raise LibraryError("Ungültige Thumbnail-Datei.")
            if target.is_file():
                return target
            fd, temporary = tempfile.mkstemp(prefix="thumb-", suffix=".jpg", dir=self.cache)
            os.close(fd)
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(source) as original:
                        # JPEG draft decoding keeps memory usage low for large photos.
                        original.draft("RGB", (size * 2, size * 2))
                        image = ImageOps.exif_transpose(original)
                        image.thumbnail((size, size), Image.Resampling.LANCZOS)
                        if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                            rgba = image.convert("RGBA")
                            background = Image.new("RGB", rgba.size, "#f4f4f0")
                            background.paste(rgba, mask=rgba.getchannel("A"))
                            image = background
                        else:
                            image = image.convert("RGB")
                        image.save(temporary, format="JPEG", quality=86, optimize=True)
                if signature(source) != stat:
                    raise LibraryError("Bild wurde während der Vorschau-Erstellung verändert.", 409)
                os.replace(temporary, target)
                return target
            except (
                UnidentifiedImageError,
                OSError,
                ValueError,
                Image.DecompressionBombError,
                Image.DecompressionBombWarning,
            ) as exc:
                logger.warning("Vorschau nicht verfügbar: %s", relative)
                raise LibraryError(
                    "Für diese beschädigte oder zu große Bilddatei ist keine Vorschau verfügbar.", 422
                ) from exc
            finally:
                Path(temporary).unlink(missing_ok=True)
