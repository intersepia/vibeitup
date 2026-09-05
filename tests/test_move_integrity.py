"""Independent byte-integrity tests for collisions, undo and filesystem failures.

Every test uses a temporary library. SHA-256 snapshots deliberately do not use
Folio's own SHA-1 index, so a stale index cannot conceal a lost or changed file.
"""

from __future__ import annotations

import errno
import hashlib
import os
import random
import shutil
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.config import MANAGED_ROOTS, Settings
from backend.main import create_app
from backend.services import library as operations
from backend.services.indexer import sha1_file
from backend.services.library import Library, transfer_no_replace
from backend.services.security import LibraryError
from tests.conftest import photo


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(base: Path) -> dict[str, str]:
    return {
        file.relative_to(base).as_posix(): fingerprint(file)
        for root in MANAGED_ROOTS
        for file in (base / root).rglob("*")
        if file.is_file() and not file.is_symlink()
    }


def prepare(tmp_path: Path) -> Settings:
    settings = Settings(tmp_path / "library")
    settings.initialize()
    return settings


def send(client: TestClient, files: list[str], action: str = "move", album: str = "Trips"):
    body = {"files": files}
    if action == "move":
        body["target_album"] = album
    return client.post(f"/api/action/{action}", json=body)


@pytest.mark.parametrize(
    "action,target", [("move", "alben/Trips"), ("trash", "trash"), ("duplicates", "duplikate")]
)
def test_three_equal_names_preserve_every_file_and_undo_after_restart(tmp_path, action, target):
    settings = prepare(tmp_path)
    base = settings.base_path
    sources = [f"zur_sortieren/{folder}/bild.jpg" for folder in ("A", "B", "C")]
    for path, color in zip(sources, ("red", "blue", "red"), strict=True):
        photo(base / path, color, (40, 30))
    photo(base / target / "bild.jpg", "white", (40, 30))
    photo(base / target / "bild_001.jpg", "black", (40, 30))
    if action == "duplicates":
        for index, source in enumerate(sources[:2]):
            destination = base / "alben/Existing" / f"original_{index}.jpg"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(base / source, destination)
    before = inventory(base)
    mtimes = {source: (base / source).stat().st_mtime_ns for source in sources}
    with TestClient(create_app(settings)) as client:
        response = send(client, sources, action)
        assert response.status_code == 200, response.text
        transaction = response.json()
        assert [item["destination"] for item in transaction["files"]] == [
            f"{target}/bild_00{counter}.jpg" for counter in (2, 3, 4)
        ]
        for item in transaction["files"]:
            assert fingerprint(base / item["destination"]) == before[item["source"]]
            assert (base / item["destination"]).stat().st_mtime_ns == mtimes[item["source"]]
        # Even two files with the SAME name AND bytes must both be retained.
        assert Counter(inventory(base).values()) == Counter(before.values())
        assert fingerprint(base / target / "bild.jpg") == before[f"{target}/bild.jpg"]
        assert fingerprint(base / target / "bild_001.jpg") == before[f"{target}/bild_001.jpg"]
    with TestClient(create_app(settings)) as restarted:
        result = restarted.post("/api/action/undo")
        assert result.status_code == 200, result.text
        assert result.json()["id"] == transaction["id"]
        assert inventory(base) == before
        assert restarted.get("/api/status").json()["can_undo"] is False
        assert restarted.post("/api/action/undo").status_code == 409


@pytest.mark.parametrize("name", ["Grüße vom See.JPG", "東京 & Urlaub.png", "Foto #1 (50%).jpg"])
def test_unicode_and_special_names_round_trip_exactly(tmp_path, name):
    settings = prepare(tmp_path)
    base = settings.base_path
    source = f"zur_sortieren/Frühling #1/{name}"
    photo(base / source, "green", (40, 30))
    photo(base / "alben/Natur & Draußen" / name, "purple", (40, 30))
    before = inventory(base)
    with TestClient(create_app(settings)) as client:
        response = send(client, [source], album="Natur & Draußen")
        assert response.status_code == 200, response.text
        path = response.json()["files"][0]["destination"]
        assert Path(path).name == f"{Path(name).stem}_001{Path(name).suffix}"
        assert fingerprint(base / path) == before[source]
        assert client.post("/api/action/undo").status_code == 200
    assert inventory(base) == before


@pytest.mark.parametrize("occupied,incoming", [("BILD.JPG", "bild.jpg"), ("Café.jpg", "Cafe\u0301.jpg")])
def test_case_and_unicode_equivalent_target_names_get_a_counter(tmp_path, occupied, incoming):
    settings = prepare(tmp_path)
    base = settings.base_path
    source = f"zur_sortieren/A/{incoming}"
    photo(base / source, "red", (40, 30))
    photo(base / "alben/Trips" / occupied, "blue", (40, 30))
    before = inventory(base)
    with TestClient(create_app(settings)) as client:
        response = send(client, [source])
        assert response.status_code == 200, response.text
        destination = response.json()["files"][0]["destination"]
        assert Path(destination).name == f"{Path(incoming).stem}_001{Path(incoming).suffix}"
        assert client.post("/api/action/undo").status_code == 200
    assert inventory(base) == before


def test_case_equivalent_names_in_one_batch_do_not_collide(tmp_path):
    settings = prepare(tmp_path)
    base = settings.base_path
    sources = ["zur_sortieren/A/Bild.jpg", "zur_sortieren/B/bild.JPG"]
    for source, color in zip(sources, ("red", "blue"), strict=True):
        photo(base / source, color, (40, 30))
    (base / "alben/Trips").mkdir()
    before = inventory(base)
    with TestClient(create_app(settings)) as client:
        response = send(client, sources)
        assert response.status_code == 200, response.text
        targets = [Path(item["destination"]).name for item in response.json()["files"]]
        assert targets == ["Bild.jpg", "bild_001.JPG"]
        assert len({unicodedata.normalize("NFC", name).casefold() for name in targets}) == 2
        assert client.post("/api/action/undo").status_code == 200
    assert inventory(base) == before


@pytest.mark.parametrize("stem", ["a" * 251, "é" * 125, "山" * 83])
def test_long_colliding_names_are_shortened_without_losing_the_extension(tmp_path, stem):
    settings = prepare(tmp_path)
    base = settings.base_path
    name = f"{stem}.jpg"
    source = f"zur_sortieren/{name}"
    try:
        photo(base / source, "red", (40, 30))
        photo(base / "alben/Trips" / name, "blue", (40, 30))
    except OSError as exc:
        if exc.errno == errno.ENAMETOOLONG or getattr(exc, "winerror", None) == 206:
            pytest.skip("This platform does not support the long source path")
        raise
    before = inventory(base)
    with TestClient(create_app(settings)) as client:
        response = send(client, [source])
        assert response.status_code == 200, response.text
        destination = response.json()["files"][0]["destination"]
        assert Path(destination).name.endswith("_001.jpg")
        assert len(Path(destination).name.encode("utf-8")) <= 255
        assert fingerprint(base / destination) == before[source]
        assert client.post("/api/action/undo").status_code == 200
    assert inventory(base) == before


def test_directories_and_dangling_links_also_reserve_target_names(tmp_path):
    settings = prepare(tmp_path)
    base = settings.base_path
    source = "zur_sortieren/bild.jpg"
    photo(base / source, "red", (40, 30))
    (base / "alben/Trips/bild.jpg").mkdir(parents=True)
    photo(base / "alben/Trips/bild.jpg/inside.jpg", "blue", (40, 30))
    try:
        (base / "alben/Trips/bild_001.jpg").symlink_to(base / "does-not-exist.jpg")
    except OSError:
        pytest.skip("Symlinks unavailable on this platform")
    before = inventory(base)
    with TestClient(create_app(settings)) as client:
        response = send(client, [source])
        assert response.status_code == 200, response.text
        assert response.json()["files"][0]["destination"] == "alben/Trips/bild_002.jpg"
        assert client.post("/api/action/undo").status_code == 200
    assert (base / "alben/Trips/bild_001.jpg").is_symlink()
    assert inventory(base) == before


def test_concurrent_equal_names_and_concurrent_undo_keep_every_byte(tmp_path):
    settings = prepare(tmp_path)
    base = settings.base_path
    sources = [f"zur_sortieren/{index}/bild.jpg" for index in range(8)]
    for index, path in enumerate(sources):
        photo(base / path, f"#{index + 10:02x}6070", (40, 30))
    (base / "alben/Trips").mkdir()
    before = inventory(base)
    with TestClient(create_app(settings)) as client:
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(lambda path: send(client, [path]), sources))
        assert all(response.status_code == 200 for response in responses)
        targets = [response.json()["files"][0]["destination"] for response in responses]
        assert len(set(targets)) == len(sources)
        for response in responses:
            item = response.json()["files"][0]
            assert fingerprint(base / item["destination"]) == before[item["source"]]
        assert Counter(inventory(base).values()) == Counter(before.values())
        with ThreadPoolExecutor(max_workers=8) as pool:
            undos = list(pool.map(lambda _: client.post("/api/action/undo"), range(8)))
        assert all(response.status_code == 200 for response in undos)
        assert len({response.json()["id"] for response in undos}) == 8
        assert not client.get("/api/status").json()["can_undo"]
    assert inventory(base) == before


def test_randomized_moves_and_undo_preserve_the_entire_library(tmp_path):
    settings = prepare(tmp_path)
    base = settings.base_path
    for index in range(24):
        photo(base / f"zur_sortieren/{index // 3}/bild_{index % 3}.jpg", f"#{index + 20:02x}7050", (30, 20))
    for album in ("Trips", "Nature"):
        photo(base / f"alben/{album}/bild_0.jpg", "purple", (30, 20))
    library = Library(settings)
    library.rebuild()
    before = inventory(base)
    counts = Counter(before.values())
    rng = random.Random(20260905)
    for _ in range(60):
        sources = sorted(path for path in inventory(base) if path.startswith("zur_sortieren/"))
        if library.journal.latest() and (not sources or rng.random() < 0.4):
            library.undo()
        elif sources:
            files = rng.sample(sources, k=min(len(sources), rng.randint(1, 5)))
            action = rng.choice(["move", "move", "trash"])
            library.move(files, action, rng.choice(["Trips", "Nature"]))
        assert Counter(inventory(base).values()) == counts
        for name in ("alben/Trips/bild_0.jpg", "alben/Nature/bild_0.jpg"):
            assert fingerprint(base / name) == before[name]
    while library.journal.latest():
        library.undo()
    assert inventory(base) == before


def test_failed_completion_journal_write_rolls_back_all_files(tmp_path):
    settings = prepare(tmp_path)
    base = settings.base_path
    source = "zur_sortieren/bild.jpg"
    photo(base / source, "red", (40, 30))
    (base / "alben/Trips").mkdir()
    library = Library(settings)
    library.rebuild()
    before = inventory(base)
    update = library.journal.update

    def fail_completion(identifier, status, error=None):
        if status == "completed":
            raise OSError("Simulated journal write failure")
        return update(identifier, status, error)

    with patch.object(library.journal, "update", side_effect=fail_completion), pytest.raises(LibraryError):
        library.move([source], "move", "Trips")
    assert inventory(base) == before
    assert library.journal.list()[0]["status"] == "rolled_back"


def test_a_target_created_after_planning_is_never_overwritten(tmp_path):
    settings = prepare(tmp_path)
    base = settings.base_path
    source = "zur_sortieren/bild.jpg"
    photo(base / source, "red", (40, 30))
    target = base / "alben/Trips/bild.jpg"
    target.parent.mkdir()
    expected_source = fingerprint(base / source)
    library = Library(settings)
    original = operations.transfer_no_replace

    def other_program_arrives(first, second, digest):
        photo(target, "blue", (40, 30))
        return original(first, second, digest)

    with (
        patch.object(operations, "transfer_no_replace", side_effect=other_program_arrives),
        pytest.raises(LibraryError),
    ):
        library.move([source], "move", "Trips")
    expected_external = fingerprint(target)
    assert fingerprint(base / source) == expected_source
    assert expected_external != expected_source
    result = library.move([source], "move", "Trips")
    assert result["files"][0]["destination"] == "alben/Trips/bild_001.jpg"
    assert fingerprint(target) == expected_external
    library.undo()
    assert fingerprint(base / source) == expected_source
    assert fingerprint(target) == expected_external


def test_source_replaced_immediately_after_hashing_is_not_moved(tmp_path):
    source = photo(tmp_path / "source.jpg", "red", (40, 30))
    destination = tmp_path / "destination.jpg"
    replacement = photo(tmp_path / "replacement.jpg", "blue", (40, 30))
    expected = sha1_file(source)
    replacement_bytes = replacement.read_bytes()
    original_hash = operations.sha1_file

    def replace_after_hash(path):
        result = original_hash(path)
        if path == source:
            os.replace(replacement, source)
        return result

    with patch.object(operations, "sha1_file", side_effect=replace_after_hash), pytest.raises(LibraryError):
        transfer_no_replace(source, destination, expected)
    assert source.read_bytes() == replacement_bytes
    assert not destination.exists()


def test_failed_copy_must_not_delete_a_replaced_destination(tmp_path):
    source = photo(tmp_path / "source.jpg", "red", (40, 30))
    destination = tmp_path / "destination.jpg"
    replacement = photo(tmp_path / "replacement.jpg", "blue", (40, 30))
    expected_source = source.read_bytes()
    expected_replacement = replacement.read_bytes()

    def replace_destination_and_fail(original, target, length):
        target.write(b"unfinished copy")
        target.flush()
        try:
            os.replace(replacement, destination)
        except PermissionError:
            pytest.skip("This platform prevents replacing an open destination")
        raise OSError("External replacement during failed copy")

    with (
        patch.object(operations.os, "link", side_effect=OSError(errno.EXDEV, "Different volume")),
        patch.object(operations.shutil, "copyfileobj", side_effect=replace_destination_and_fail),
        pytest.raises(OSError),
    ):
        transfer_no_replace(source, destination, sha1_file(source))
    assert source.read_bytes() == expected_source
    assert destination.exists(), "An external program's replacement must never be cleaned up as our copy"
    assert destination.read_bytes() == expected_replacement


@pytest.mark.parametrize("error", [OSError("Cache disk full"), LibraryError("A folder disappeared", 404)])
def test_completed_move_is_not_reported_as_failed_when_index_refresh_fails(tmp_path, error):
    settings = prepare(tmp_path)
    base = settings.base_path
    source = "zur_sortieren/bild.jpg"
    photo(base / source, "red", (40, 30))
    (base / "alben/Trips").mkdir()
    before = inventory(base)
    with TestClient(create_app(settings)) as client:
        library = client.app.state.library
        with patch.object(library.index, "rebuild", side_effect=error):
            response = send(client, [source])
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "completed"
        assert fingerprint(base / "alben/Trips/bild.jpg") == before[source]
        status = client.get("/api/status").json()
        assert status["can_undo"] and status["index_warning"]
        assert client.post("/api/action/undo").status_code == 200
        assert client.get("/api/status").json()["index_warning"] is None
    assert inventory(base) == before


def test_failed_cache_save_keeps_fresh_in_memory_counts_and_valid_old_cache(tmp_path):
    settings = prepare(tmp_path)
    base = settings.base_path
    source = "zur_sortieren/bild.jpg"
    photo(base / source, "red", (40, 30))
    (base / "alben/Trips").mkdir()
    with TestClient(create_app(settings)) as client:
        cache = base / ".image-sorter/index.json"
        old_cache = cache.read_bytes()
        with patch("backend.services.indexer.tempfile.mkstemp", side_effect=OSError("Cache disk full")):
            response = send(client, [source])
        assert response.status_code == 200
        assert cache.read_bytes() == old_cache
        status = client.get("/api/status").json()
        assert status["source_count"] == 0 and status["album_images"] == 1
        assert status["index_warning"]
        assert client.get("/api/images", params={"path": "alben/Trips"}).json()["total"] == 1
        assert client.post("/api/index").status_code == 200
        assert client.get("/api/status").json()["index_warning"] is None
        assert client.post("/api/action/undo").status_code == 200


@pytest.mark.parametrize("phase", ["move", "undo"])
def test_real_process_exit_mid_batch_is_recovered_without_data_loss(tmp_path, phase):
    import subprocess
    import sys

    settings = prepare(tmp_path)
    base = settings.base_path
    sources = ["zur_sortieren/A/bild.jpg", "zur_sortieren/B/bild.jpg"]
    for source, color in zip(sources, ("red", "blue"), strict=True):
        photo(base / source, color, (40, 30))
    photo(base / "alben/Trips/bild.jpg", "green", (40, 30))
    before = inventory(base)
    # Exit AFTER a real filesystem step, without finally blocks or graceful shutdown.
    child = r"""
import os, sys
from pathlib import Path
from backend.config import Settings
from backend.services import library as operations
from backend.services.library import Library
from backend.services.process_lock import LibraryProcessLock
settings = Settings(Path(sys.argv[1]))
lock = LibraryProcessLock(settings.metadata_path / "instance.lock")
lock.acquire()
library = Library(settings)
sources = ["zur_sortieren/A/bild.jpg", "zur_sortieren/B/bild.jpg"]
if sys.argv[2] == "undo":
    library.move(sources, "move", "Trips")
original = operations.transfer_no_replace
def exit_after_one_step(source, destination, digest):
    original(source, destination, digest)
    os._exit(77)
operations.transfer_no_replace = exit_after_one_step
if sys.argv[2] == "undo":
    library.undo()
else:
    library.move(sources, "move", "Trips")
"""
    result = subprocess.run(
        [sys.executable, "-c", child, str(base), phase],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 77, result.stderr
    assert inventory(base) != before  # Demonstrate that the interrupted step really happened.
    with TestClient(create_app(settings)) as restarted:
        assert inventory(base) == before
        assert not restarted.get("/api/status").json()["can_undo"]
        status = restarted.get("/api/logs").json()[0]["status"]
        assert status == ("rolled_back" if phase == "move" else "undone")


def test_real_cross_filesystem_move_and_return(tmp_path):
    from tempfile import TemporaryDirectory

    shared_memory = Path("/dev/shm")
    if not shared_memory.is_dir() or not os.access(shared_memory, os.W_OK):
        pytest.skip("A second writable filesystem is not available on this platform")
    if shared_memory.stat().st_dev == tmp_path.stat().st_dev:
        pytest.skip("Temporary directories are on the same filesystem")
    source = photo(tmp_path / "original.jpg", "purple", (40, 30))
    before = source.read_bytes()
    modified = source.stat().st_mtime_ns
    with TemporaryDirectory(prefix="folio-cross-volume-", dir=shared_memory) as temporary:
        destination = Path(temporary) / "original.jpg"
        digest = sha1_file(source)
        transfer_no_replace(source, destination, digest)
        assert not source.exists()
        assert destination.read_bytes() == before
        assert destination.stat().st_mtime_ns == modified
        transfer_no_replace(destination, source, digest)
        assert not destination.exists()
    assert source.read_bytes() == before
    assert source.stat().st_mtime_ns == modified


def test_maximum_500_file_batch_with_equal_names_can_be_undone(tmp_path):
    settings = prepare(tmp_path)
    base = settings.base_path
    sources = [f"zur_sortieren/{index:03}/bild.jpg" for index in range(500)]
    first = photo(base / sources[0], "red", (20, 20))
    for source in sources[1:]:
        target = base / source
        target.parent.mkdir()
        shutil.copy2(first, target)
    photo(base / "alben/Trips/bild.jpg", "blue", (20, 20))
    before = inventory(base)
    with TestClient(create_app(settings)) as client:
        response = send(client, sources)
        assert response.status_code == 200, response.text
        items = response.json()["files"]
        assert len(items) == 500
        assert items[-1]["destination"] == "alben/Trips/bild_500.jpg"
        assert Counter(inventory(base).values()) == Counter(before.values())
        assert client.post("/api/action/undo").status_code == 200
    assert inventory(base) == before


def test_a_last_good_copy_is_kept_if_source_is_replaced_during_copy(tmp_path):
    settings = prepare(tmp_path)
    base = settings.base_path
    source = photo(base / "zur_sortieren/bild.jpg", "red", (40, 30))
    destination = base / "alben/Trips/bild.jpg"
    destination.parent.mkdir()
    replacement = photo(tmp_path / "replacement.jpg", "blue", (40, 30))
    before = source.read_bytes()
    updated = replacement.read_bytes()
    original_copy = operations.shutil.copyfileobj
    library = Library(settings)

    def replace_source_after_copy(original, target, length):
        original_copy(original, target, length)
        try:
            os.replace(replacement, source)
        except PermissionError:
            pytest.skip("This platform prevents replacing an open source")

    with (
        patch.object(operations.os, "link", side_effect=OSError(errno.EXDEV, "Different volume")),
        patch.object(operations.shutil, "copyfileobj", side_effect=replace_source_after_copy),
        pytest.raises(LibraryError),
    ):
        library.move(["zur_sortieren/bild.jpg"], "move", "Trips")
    assert source.read_bytes() == updated
    assert destination.read_bytes() == before
    assert library.journal.list()[0]["status"] == "interrupted"


def test_failed_cleanup_is_visible_as_interrupted_not_as_successful_rollback(tmp_path):
    settings = prepare(tmp_path)
    base = settings.base_path
    source = photo(base / "zur_sortieren/bild.jpg", "red", (40, 30))
    destination = base / "alben/Trips/bild.jpg"
    destination.parent.mkdir()
    before = source.read_bytes()
    library = Library(settings)
    original_unlink = Path.unlink

    def cannot_unlink(path, *args, **kwargs):
        if path in (source, destination):
            raise PermissionError("File locked by another program")
        return original_unlink(path, *args, **kwargs)

    with patch.object(Path, "unlink", cannot_unlink), pytest.raises(LibraryError):
        library.move(["zur_sortieren/bild.jpg"], "move", "Trips")
    assert source.read_bytes() == destination.read_bytes() == before
    assert library.journal.list()[0]["status"] == "interrupted"


@pytest.mark.parametrize("change", ["remove", "modify"])
def test_changed_or_missing_destination_blocks_the_whole_undo_batch(tmp_path, change):
    settings = prepare(tmp_path)
    base = settings.base_path
    sources = ["zur_sortieren/A/bild.jpg", "zur_sortieren/B/bild.jpg"]
    for source, color in zip(sources, ("red", "blue"), strict=True):
        photo(base / source, color, (40, 30))
    (base / "alben/Trips").mkdir()
    before = inventory(base)
    with TestClient(create_app(settings)) as client:
        response = send(client, sources)
        assert response.status_code == 200
        destination = base / response.json()["files"][1]["destination"]
        original = destination.read_bytes()
        if change == "remove":
            outside = tmp_path / "externally-moved.jpg"
            destination.rename(outside)
        else:
            photo(destination, "purple", (40, 30))
        before_failed_undo = inventory(base)
        result = client.post("/api/action/undo")
        assert result.status_code == (404 if change == "remove" else 409)
        assert inventory(base) == before_failed_undo
        assert all(not (base / source).exists() for source in sources)
        assert client.get("/api/logs").json()[0]["status"] == "completed"
        if change == "remove":
            assert outside.read_bytes() == original
            outside.rename(destination)
        else:
            destination.write_bytes(original)
        assert client.post("/api/action/undo").status_code == 200
    assert inventory(base) == before
