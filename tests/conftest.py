from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.config import Settings
from backend.main import create_app


def photo(path: Path, color: str = "#729479", size: tuple[int, int] = (800, 600)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


@pytest.fixture
def base(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    photo(root / "zur_sortieren/one.jpg", "red")
    photo(root / "zur_sortieren/two.jpg", "blue")
    photo(root / "zur_sortieren/travel/three.jpg", "green")
    photo(root / "alben/Trips/existing.jpg", "yellow")
    shutil.copy2(root / "alben/Trips/existing.jpg", root / "zur_sortieren/duplicate.jpg")
    return root


@pytest.fixture
def client(base: Path) -> Iterator[TestClient]:
    with TestClient(create_app(Settings(base))) as connection:
        yield connection
