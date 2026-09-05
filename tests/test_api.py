from __future__ import annotations

import errno
import hashlib
import io
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.config import Settings
from backend.main import create_app
from backend.services.indexer import sha1_file
from backend.services.library import Library, transfer_no_replace
from backend.services.security import LibraryError
from tests.conftest import photo


def move(client: TestClient, files: list[str] | None = None, album: str = "Trips"):
    return client.post(
        "/api/action/move", json={"files": files or ["zur_sortieren/one.jpg"], "target_album": album}
    )


def test_bootstrap_and_status(client, base):
    for directory in (
        "alben",
        "duplikate",
        "trash",
        "zur_sortieren",
        "temp/duplikat",
        "temp/trash",
        ".image-sorter/thumbnails",
    ):
        assert (base / directory).is_dir()
    status = client.get("/api/status").json()
    assert status["source_count"] == 4
    assert status["album_count"] == 1
    assert status["duplicate_count"] == 1
    assert not status["can_undo"]
    assert client.get("/api/health").json()["status"] == "ok"


def test_source_tree_and_recursive_listing(client):
    tree = client.get("/api/folders/source").json()
    assert (tree["count"], tree["direct_count"]) == (4, 3)
    assert tree["children"][0]["path"] == "zur_sortieren/travel"
    assert client.get("/api/images").json()["total"] == 3
    listing = client.get("/api/images", params={"path": "zur_sortieren", "recursive": True}).json()
    assert listing["total"] == 4
    assert listing["total_size"] == sum(image["size"] for image in listing["images"])
    assert client.get("/api/images", params={"path": "zur_sortieren/travel"}).json()["total"] == 1
    assert client.get("/api/images", params={"path": "zur_sortieren/one.jpg"}).status_code == 400


def test_hash_is_exact_and_persistent(client, base):
    entries = client.get("/api/images").json()["images"]
    duplicate = next(image for image in entries if image["is_duplicate"])
    assert duplicate["duplicate_of"] == ["alben/Trips/existing.jpg"]
    assert duplicate["sha1"] == hashlib.sha1((base / duplicate["path"]).read_bytes()).hexdigest()
    cache = json.loads((base / ".image-sorter/index.json").read_text())
    assert len(cache["files"]) == 5
    report = client.post("/api/index").json()
    assert report["hashed"] == 0
    assert report["cached"] == 5
    photo(base / "zur_sortieren/one.jpg", "purple")
    assert client.post("/api/index").json()["hashed"] == 1


def test_rebuild_discovers_and_removes_external_files(client, base):
    photo(base / "zur_sortieren/new.png")
    (base / "zur_sortieren/two.jpg").unlink()
    client.post("/api/index")
    names = [image["name"] for image in client.get("/api/images").json()["images"]]
    assert "new.png" in names and "two.jpg" not in names


def test_corrupt_index_is_rebuilt(base):
    metadata = base / ".image-sorter"
    metadata.mkdir()
    (metadata / "index.json").write_text('{"invalid":')
    with TestClient(create_app(Settings(base))) as client:
        assert client.get("/api/status").json()["source_count"] == 4
    assert json.loads((metadata / "index.json").read_text())["version"] == 1


@pytest.mark.parametrize(
    "path",
    [
        "../",
        "/etc/passwd",
        "zur_sortieren/../alben",
        "zur_sortieren/../../secret",
        "zur_sortieren\\..\\secret",
        "C:/secret",
        "zur_sortieren/.hidden",
        ".image-sorter",
        "temp",
        "zur_sortieren//travel",
        "zur_sortieren/./travel",
        "zur_sortieren/\x00.jpg",
    ],
)
def test_path_traversal_rejected(client, path):
    assert client.get("/api/images", params={"path": path}).status_code == 400


@pytest.mark.parametrize(
    "album",
    [
        "../out",
        "A/B",
        "..",
        ".secret",
        "C:\\out",
        "CON",
        "NUL.txt",
        "LPT1",
        "bad*name",
        "bad?name",
        "bad:name",
        "bad|name",
        "bad\x00name",
    ],
)
def test_unsafe_album_names_rejected(client, album):
    assert client.post("/api/folders/albums", json={"name": album}).status_code == 400


def test_create_album_and_duplicate_name(client, base):
    assert client.post("/api/folders/albums", json={"name": "Natur & Draußen"}).status_code == 201
    assert (base / "alben/Natur & Draußen").is_dir()
    assert client.post("/api/folders/albums", json={"name": "Natur & Draußen"}).status_code == 409
    assert client.post("/api/folders/albums", json={"name": " "}).status_code == 400


def test_move_collision_counter_and_undo(client, base):
    photo(base / "alben/Trips/one.jpg", "white")
    photo(base / "alben/Trips/one_001.jpg", "black")
    protected = (base / "alben/Trips/one.jpg").read_bytes()
    original = (base / "zur_sortieren/one.jpg").read_bytes()
    response = move(client)
    assert response.status_code == 200
    destination = response.json()["files"][0]["destination"]
    assert destination == "alben/Trips/one_002.jpg"
    assert (base / destination).read_bytes() == original
    assert (base / "alben/Trips/one.jpg").read_bytes() == protected
    assert not (base / "zur_sortieren/one.jpg").exists()
    assert client.get("/api/status").json()["can_undo"]
    assert client.post("/api/action/undo").status_code == 200
    assert (base / "zur_sortieren/one.jpg").read_bytes() == original
    assert not (base / destination).exists()
    assert client.get("/api/logs").json()[0]["status"] == "undone"


def test_same_filename_batch_and_nested_target(client, base):
    photo(base / "zur_sortieren/travel/one.jpg", "pink")
    (base / "alben/Trips/2025").mkdir()
    response = move(client, ["zur_sortieren/one.jpg", "zur_sortieren/travel/one.jpg"], "Trips/2025")
    assert response.status_code == 200
    assert [item["destination"] for item in response.json()["files"]] == [
        "alben/Trips/2025/one.jpg",
        "alben/Trips/2025/one_001.jpg",
    ]
    assert client.post("/api/action/undo").status_code == 200
    assert (base / "zur_sortieren/travel/one.jpg").exists()


def test_batch_preflight_does_not_partially_move(client, base):
    response = move(client, ["zur_sortieren/one.jpg", "zur_sortieren/missing.jpg"])
    assert response.status_code == 404
    assert (base / "zur_sortieren/one.jpg").exists()
    assert client.get("/api/logs").json() == []


def test_batch_failure_rolls_back(client, base):
    from backend.services import library

    original_transfer = library.transfer_no_replace

    def fail_second(source, destination, digest):
        if source.name == "two.jpg":
            raise OSError("Simulated disk failure")
        return original_transfer(source, destination, digest)

    with patch.object(library, "transfer_no_replace", side_effect=fail_second):
        assert move(client, ["zur_sortieren/one.jpg", "zur_sortieren/two.jpg"]).status_code == 409
    assert (base / "zur_sortieren/one.jpg").exists()
    assert (base / "zur_sortieren/two.jpg").exists()
    assert not (base / "alben/Trips/one.jpg").exists()
    assert client.get("/api/logs").json()[0]["status"] == "rolled_back"


def test_undo_conflict_never_overwrites(client, base):
    move(client, ["zur_sortieren/one.jpg", "zur_sortieren/two.jpg"])
    photo(base / "zur_sortieren/two.jpg", "orange")
    replacement = (base / "zur_sortieren/two.jpg").read_bytes()
    response = client.post("/api/action/undo")
    assert response.status_code == 409
    assert (base / "alben/Trips/one.jpg").exists()
    assert (base / "alben/Trips/two.jpg").exists()
    assert (base / "zur_sortieren/two.jpg").read_bytes() == replacement


def test_undo_rejects_modified_destination(client, base):
    move(client)
    photo(base / "alben/Trips/one.jpg", "pink")
    assert client.post("/api/action/undo").status_code == 409
    assert not (base / "zur_sortieren/one.jpg").exists()


def test_undo_survives_restart_and_is_lifo(base):
    with TestClient(create_app(Settings(base))) as client:
        move(client)
        client.post("/api/action/trash", json={"files": ["zur_sortieren/two.jpg"]})
    with TestClient(create_app(Settings(base))) as client:
        assert client.post("/api/action/undo").json()["action"] == "trash"
        assert (base / "alben/Trips/one.jpg").exists()
        assert (base / "zur_sortieren/two.jpg").exists()
        assert client.post("/api/action/undo").json()["action"] == "move"
        assert client.post("/api/action/undo").status_code == 409


def test_trash_only_moves_and_is_reversible(client, base):
    before = (base / "zur_sortieren/one.jpg").read_bytes()
    assert client.post("/api/action/trash", json={"files": ["zur_sortieren/one.jpg"]}).status_code == 200
    assert (base / "trash/one.jpg").read_bytes() == before
    assert client.post("/api/action/undo").status_code == 200
    assert (base / "zur_sortieren/one.jpg").read_bytes() == before


def test_only_confirmed_duplicates_can_be_filed(client, base):
    assert client.post("/api/action/duplicates", json={"files": ["zur_sortieren/one.jpg"]}).status_code == 409
    assert (
        client.post("/api/action/duplicates", json={"files": ["zur_sortieren/duplicate.jpg"]}).status_code
        == 200
    )
    assert (base / "duplikate/duplicate.jpg").is_file()
    assert client.post("/api/action/undo").status_code == 200
    photo(base / "alben/Trips/existing.jpg", "black")
    assert (
        client.post("/api/action/duplicates", json={"files": ["zur_sortieren/duplicate.jpg"]}).status_code
        == 409
    )


@pytest.mark.parametrize(
    "path", ["alben/Trips/existing.jpg", "../secret.jpg", "zur_sortieren/../alben/Trips/existing.jpg"]
)
def test_move_must_originate_in_inbox(client, path):
    assert move(client, [path]).status_code == 400


def test_selection_validation(client):
    assert client.post("/api/action/trash", json={"files": []}).status_code == 422
    assert client.post("/api/action/trash", json={"files": ["a"] * 501}).status_code == 422
    assert move(client, ["zur_sortieren/one.jpg", "zur_sortieren/one.jpg"]).status_code == 400
    assert (
        client.post(
            "/api/action/move",
            json={"files": ["zur_sortieren/one.jpg"], "target_album": "Trips", "unexpected": True},
        ).status_code
        == 422
    )


def test_thumbnail_bounds_and_no_original_changes(client, base):
    original = (base / "zur_sortieren/one.jpg").read_bytes()
    result = client.get("/api/thumb/zur_sortieren/one.jpg")
    assert result.status_code == 200
    assert result.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(result.content)) as image:
        assert image.size == (400, 300)
    assert (base / "zur_sortieren/one.jpg").read_bytes() == original
    cache = list((base / ".image-sorter/thumbnails").glob("*.jpg"))
    assert len(cache) == 1
    assert client.get("/api/thumb/zur_sortieren/one.jpg").content == result.content
    photo(base / "zur_sortieren/one.jpg", "cyan")
    assert client.get("/api/thumb/zur_sortieren/one.jpg").content != result.content


def test_rgba_exif_and_corrupt_images(client, base):
    transparent = base / "zur_sortieren/alpha.png"
    Image.new("RGBA", (600, 900), (255, 10, 10, 0)).save(transparent)
    result = client.get("/api/thumb/zur_sortieren/alpha.png")
    assert result.status_code == 200
    with Image.open(io.BytesIO(result.content)) as image:
        assert image.mode == "RGB" and max(image.size) <= 400
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (800, 600), "red").save(base / "zur_sortieren/exif.jpg", exif=exif)
    with Image.open(io.BytesIO(client.get("/api/thumb/zur_sortieren/exif.jpg").content)) as image:
        assert image.size == (300, 400)
    (base / "zur_sortieren/broken.jpg").write_text("not an image")
    assert client.get("/api/thumb/zur_sortieren/broken.jpg").status_code == 422
    assert client.get("/api/image/.image-sorter/index.json").status_code == 400


def test_symlinks_are_not_followed(client, base, tmp_path):
    outside = photo(tmp_path / "secret.jpg", "purple")
    try:
        (base / "zur_sortieren/link.jpg").symlink_to(outside)
        (base / "zur_sortieren/linked-folder").symlink_to(tmp_path, target_is_directory=True)
        (base / "alben/Linked").symlink_to(base / "alben/Trips", target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks unavailable for this platform/user")
    client.post("/api/index")
    assert client.get("/api/status").json()["source_count"] == 4
    assert move(client, ["zur_sortieren/link.jpg"]).status_code == 400
    assert move(client, album="Linked").status_code == 400
    assert client.get("/api/thumb/zur_sortieren/link.jpg").status_code == 400
    assert client.get("/api/images", params={"path": "zur_sortieren/linked-folder"}).status_code == 400
    assert outside.exists()


def test_root_symlink_rejected(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (base / "alben").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks unavailable")
    with pytest.raises(ValueError):
        Settings(base).initialize()


def test_cross_volume_move_and_no_clobber(tmp_path):
    source = photo(tmp_path / "source.jpg")
    destination = tmp_path / "other/target.jpg"
    destination.parent.mkdir()
    digest = sha1_file(source)
    with patch("backend.services.library.os.link", side_effect=OSError(errno.EXDEV, "Cross-device")):
        transfer_no_replace(source, destination, digest)
    assert not source.exists() and sha1_file(destination) == digest
    source = photo(tmp_path / "source.jpg", "blue")
    with pytest.raises(LibraryError):
        transfer_no_replace(source, destination, sha1_file(source))
    assert source.exists() and sha1_file(destination) == digest


def test_interrupted_transaction_recovers_at_startup(base):
    library = Library(Settings(base))
    source = base / "zur_sortieren/one.jpg"
    digest = sha1_file(source)
    target = base / "alben/Trips/one.jpg"
    identifier = library.journal.begin(
        "move",
        [
            {
                "source": "zur_sortieren/one.jpg",
                "destination": "alben/Trips/one.jpg",
                "sha1": digest,
                "size": source.stat().st_size,
            }
        ],
    )
    transfer_no_replace(source, target, digest)
    restarted = Library(Settings(base))
    assert source.exists() and not target.exists()
    assert restarted.journal.get(identifier)["status"] == "rolled_back"


def test_recovery_conflict_keeps_both_files(base):
    library = Library(Settings(base))
    source = base / "zur_sortieren/one.jpg"
    digest = sha1_file(source)
    target = base / "alben/Trips/one.jpg"
    identifier = library.journal.begin(
        "move",
        [
            {
                "source": "zur_sortieren/one.jpg",
                "destination": "alben/Trips/one.jpg",
                "sha1": digest,
                "size": source.stat().st_size,
            }
        ],
    )
    shutil.copy2(source, target)
    restarted = Library(Settings(base))
    assert source.exists() and target.exists()
    assert restarted.journal.get(identifier)["status"] == "interrupted"


def test_concurrent_move_requests_are_serialized(client, base):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: move(client).status_code, range(2)))
    assert sorted(results) == [200, 404]
    assert len(client.get("/api/logs").json()) == 1
    assert (base / "alben/Trips/one.jpg").exists()


def test_same_origin_mutations_and_unknown_routes(client):
    assert client.post("/api/index", headers={"origin": "https://unrelated.example"}).status_code == 403
    assert client.post("/api/index", headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert client.post("/api/index", headers={"origin": "http://testserver"}).status_code == 200
    assert client.get("/api/does-not-exist").status_code == 404
    assert client.get("/api/does-not-exist").headers["content-type"] == "application/json"
    assert client.get("/api/logs?limit=0").status_code == 422


def test_large_preview_is_browser_compatible(client, base):
    photo(base / "zur_sortieren/scanned.tiff", size=(2400, 3000))
    result = client.get("/api/preview/zur_sortieren/scanned.tiff")
    assert result.status_code == 200
    assert result.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(result.content)) as image:
        assert image.size == (1536, 1920)
    assert (
        client.get("/api/image/zur_sortieren/scanned.tiff").content
        == (base / "zur_sortieren/scanned.tiff").read_bytes()
    )


def test_multiple_app_instances_cannot_share_library(client, base):
    with pytest.raises(RuntimeError, match="anderen Folio-Prozess"):
        with TestClient(create_app(Settings(base))):
            pass
    # A rejected second instance must not release the first one's lock.
    assert client.get("/api/health").status_code == 200


def test_process_lock_is_released_after_shutdown(base):
    for _ in range(2):
        with TestClient(create_app(Settings(base))) as client:
            assert client.get("/api/health").status_code == 200


def test_failed_undo_rolls_back_already_restored_files(client, base):
    from backend.services import library

    assert move(client, ["zur_sortieren/one.jpg", "zur_sortieren/two.jpg"]).status_code == 200
    original_transfer = library.transfer_no_replace

    def fail_one_restoration(source, destination, digest):
        if source.name == "one.jpg" and source.parent.name == "Trips":
            raise OSError("Simulated restore failure")
        return original_transfer(source, destination, digest)

    with patch.object(library, "transfer_no_replace", side_effect=fail_one_restoration):
        assert client.post("/api/action/undo").status_code == 409
    for name in ("one.jpg", "two.jpg"):
        assert (base / "alben/Trips" / name).exists()
        assert not (base / "zur_sortieren" / name).exists()
    assert client.get("/api/logs").json()[0]["status"] == "completed"
    assert client.post("/api/action/undo").status_code == 200


def test_interrupted_undo_is_completed_on_restart(base):
    library = Library(Settings(base))
    result = library.move(["zur_sortieren/one.jpg", "zur_sortieren/two.jpg"], "move", "Trips")
    library.journal.update(result["id"], "undoing")
    item = result["files"][0]
    transfer_no_replace(base / item["destination"], base / item["source"], item["sha1"])
    restarted = Library(Settings(base))
    assert restarted.journal.get(result["id"])["status"] == "undone"
    assert (base / "zur_sortieren/one.jpg").exists()
    assert (base / "zur_sortieren/two.jpg").exists()
    assert not (base / "alben/Trips/one.jpg").exists()
    assert not (base / "alben/Trips/two.jpg").exists()


def test_undo_recreates_removed_source_directory(client, base):
    assert move(client, ["zur_sortieren/travel/three.jpg"]).status_code == 200
    (base / "zur_sortieren/travel").rmdir()
    assert client.post("/api/action/undo").status_code == 200
    assert (base / "zur_sortieren/travel/three.jpg").is_file()


def test_cross_volume_copy_failure_keeps_original(tmp_path):
    source = photo(tmp_path / "original.jpg")
    destination = tmp_path / "copy.jpg"
    digest = sha1_file(source)

    def disk_full(original, target, length):
        target.write(b"incomplete")
        raise OSError("Disk full")

    with (
        patch("backend.services.library.os.link", side_effect=OSError(errno.EXDEV, "Cross-device")),
        patch("backend.services.library.shutil.copyfileobj", side_effect=disk_full),
        pytest.raises(OSError),
    ):
        transfer_no_replace(source, destination, digest)
    assert source.exists() and sha1_file(source) == digest
    assert not destination.exists()


def test_hashing_rejects_files_changed_while_reading(tmp_path):
    path = photo(tmp_path / "changing.jpg")
    with (
        patch("backend.services.indexer.signature", side_effect=[{"mtime_ns": 1}, {"mtime_ns": 2}]),
        pytest.raises(LibraryError, match="während des Lesens"),
    ):
        sha1_file(path)


def test_invalid_cached_dimensions_trigger_full_rebuild(base):
    library = Library(Settings(base))
    library.rebuild()
    path = base / ".image-sorter/index.json"
    cache = json.loads(path.read_text())
    cache["files"]["zur_sortieren/one.jpg"]["width"] = "corrupt"
    path.write_text(json.dumps(cache))
    with TestClient(create_app(Settings(base))) as client:
        response = client.get("/api/images")
        assert response.status_code == 200
        one = next(image for image in response.json()["images"] if image["name"] == "one.jpg")
        assert one["width"] == 800


def test_oversized_decompression_is_rejected(client, base):
    photo(base / "zur_sortieren/large.png", size=(30, 30))
    with patch.object(Image, "MAX_IMAGE_PIXELS", 100):
        assert client.get("/api/thumb/zur_sortieren/large.png").status_code == 422
