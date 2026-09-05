import pytest

from backend.config import Settings
from scripts.seed_demo import seed_demo


def test_relative_config_is_independent_of_cwd(tmp_path, monkeypatch):
    config = tmp_path / "settings.yaml"
    config.write_text("base_path: photos\nserver:\n  port: 9001\nthumbnail_size: 320\n")
    monkeypatch.chdir(tmp_path.parent)
    settings = Settings.load(config)
    assert settings.base_path == tmp_path / "photos"
    assert settings.port == 9001
    assert settings.thumbnail_size == 320


def test_environment_overrides_config(tmp_path, monkeypatch):
    config = tmp_path / "settings.yaml"
    config.write_text("base_path: photos\n")
    monkeypatch.setenv("IMAGE_SORTER_BASE_PATH", str(tmp_path / "other"))
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "8123")
    settings = Settings.load(config)
    assert settings.base_path == tmp_path / "other"
    assert settings.host == "0.0.0.0"
    assert settings.port == 8123


@pytest.mark.parametrize(
    "content", ["thumbnail_size: 900", "index_on_startup: 'yes'", "server:\n  port: 99999", "- one\n- two"]
)
def test_invalid_configuration(tmp_path, content):
    config = tmp_path / "settings.yaml"
    config.write_text(content)
    with pytest.raises(ValueError):
        Settings.load(config)


def test_demo_is_explicit_and_never_overwrites(tmp_path):
    base = tmp_path / "demo"
    assert seed_demo(base)
    assert len(list((base / "zur_sortieren").rglob("*.jpg"))) == 18
    assert len(list((base / "alben").rglob("*.jpg"))) == 5
    first = base / "zur_sortieren/01_atlantikkueste.jpg"
    first.write_bytes(b"User changed this file")
    assert not seed_demo(base)
    assert first.read_bytes() == b"User changed this file"
    real = tmp_path / "real"
    real.mkdir()
    (real / "precious.jpg").write_bytes(b"do not overwrite")
    with pytest.raises(ValueError):
        seed_demo(real)
    assert (real / "precious.jpg").read_bytes() == b"do not overwrite"


def test_browser_test_library_is_deleted_after_shutdown():
    from pathlib import Path

    from fastapi.testclient import TestClient

    from scripts.serve_e2e import create_test_app

    with TestClient(create_test_app()) as client:
        status = client.get("/api/status").json()
        base = Path(status["base_path"])
        assert status["demo"] and status["source_count"] == 18
        assert base.is_dir()
    assert not base.parent.exists()
