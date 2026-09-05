"""Album creation stays relative to the album root and preserves existing files."""

from __future__ import annotations

import errno
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.conftest import photo


def create(client, name="Sommer & Meer", parent=""):
    return client.post("/api/folders/albums", json={"name": name, "parent": parent})


@pytest.mark.parametrize("parent", ["", "Trips", "Trips/2026", "Natur & Draußen/Reisen #1"])
def test_create_at_selected_existing_parent(client, base, parent):
    (base / "alben" / parent).mkdir(parents=True, exist_ok=True)
    before = {path: path.read_bytes() for path in base.rglob("*.jpg")}
    response = create(client, parent=parent)
    assert response.status_code == 201, response.text
    relative = "/".join(part for part in ("alben", parent, "Sommer & Meer") if part)
    assert response.json() == {
        "name": "Sommer & Meer",
        "path": relative,
        "count": 0,
        "direct_count": 0,
        "children": [],
    }
    assert (base / relative).is_dir()
    if parent:
        assert not (base / "alben/Sommer & Meer").exists()
    assert {path: path.read_bytes() for path in base.rglob("*.jpg")} == before
    assert client.get("/api/logs").json() == []


def test_same_leaf_allowed_in_other_parents_but_not_same_parent(client, base):
    (base / "alben/Other").mkdir()
    assert create(client, "Favoriten").status_code == 201
    assert create(client, "Favoriten", "Trips").status_code == 201
    assert create(client, "Favoriten", "Other").status_code == 201
    assert create(client, "Favoriten", "Trips").status_code == 409
    assert create(client, "FAVORITEN", "Trips").status_code == 409
    assert client.get("/api/folders/albums").status_code == 200


def test_unicode_equivalent_sibling_names_are_not_ambiguous(client, base):
    assert create(client, "Café", "Trips").status_code == 201
    assert create(client, "Cafe\u0301", "Trips").status_code == 409
    assert (base / "alben/Trips/Café").is_dir()


@pytest.mark.parametrize(
    "parent",
    [
        "..",
        "../zur_sortieren",
        "Trips/../..",
        "/tmp",
        "C:/Pictures",
        "Trips\\2026",
        ".image-sorter",
        "Trips/.hidden",
        "Trips//2026",
        "Trips/./2026",
        "Trips/",
        "Trips/\x00",
        "NUL",
    ],
)
def test_parent_traversal_and_unsafe_paths_rejected(client, base, parent):
    before = {path.relative_to(base) for path in base.rglob("*") if path.is_dir()}
    assert create(client, parent=parent).status_code == 400
    assert {path.relative_to(base) for path in base.rglob("*") if path.is_dir()} == before


def test_missing_parent_is_not_implicitly_created_or_replaced_with_root(client, base):
    response = create(client, parent="Trips/Does-not-exist")
    assert response.status_code == 404
    assert not (base / "alben/Trips/Does-not-exist").exists()
    assert not (base / "alben/Sommer & Meer").exists()


def test_file_is_not_a_valid_parent_and_is_not_overwritten(client, base):
    original = (base / "alben/Trips/existing.jpg").read_bytes()
    assert create(client, parent="Trips/existing.jpg").status_code == 400
    assert (base / "alben/Trips/existing.jpg").read_bytes() == original
    assert not (base / "alben/Sommer & Meer").exists()
    assert create(client, "existing.jpg", "Trips").status_code == 409
    assert (base / "alben/Trips/existing.jpg").read_bytes() == original


@pytest.mark.parametrize("inside", [True, False])
def test_symlink_parent_is_rejected_even_when_pointing_inside_library(client, base, tmp_path, inside):
    target = base / "alben/Trips" if inside else tmp_path / "outside"
    target.mkdir(exist_ok=True)
    try:
        (base / "alben/Linked").symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks unavailable on this platform")
    assert create(client, parent="Linked").status_code == 400
    assert not (target / "Sommer & Meer").exists()


@pytest.mark.parametrize("parent", [None, 42, ["Trips"]])
def test_parent_must_be_a_string(client, parent):
    assert create(client, parent=parent).status_code == 422


def test_deep_created_album_is_a_real_move_target_and_undo_keeps_the_album(client, base):
    (base / "alben/Trips/2026").mkdir()
    protected = photo(base / "alben/Favoriten/one.jpg", "purple").read_bytes()
    original = (base / "zur_sortieren/one.jpg").read_bytes()
    response = create(client, "Favoriten", "Trips/2026")
    assert response.status_code == 201
    destination_album = response.json()["path"]
    assert destination_album == "alben/Trips/2026/Favoriten"
    response = client.post(
        "/api/action/move",
        json={"files": ["zur_sortieren/one.jpg"], "target_album": destination_album.removeprefix("alben/")},
    )
    assert response.status_code == 200
    destination = response.json()["files"][0]["destination"]
    assert destination == f"{destination_album}/one.jpg"
    assert (base / destination).read_bytes() == original
    assert (base / "alben/Favoriten/one.jpg").read_bytes() == protected
    assert client.post("/api/action/undo").status_code == 200
    assert (base / "zur_sortieren/one.jpg").read_bytes() == original
    assert (base / destination_album).is_dir()
    assert list((base / destination_album).iterdir()) == []


def test_creating_a_nested_album_does_not_reset_existing_undo_history(client, base):
    original = (base / "zur_sortieren/one.jpg").read_bytes()
    moved = client.post(
        "/api/action/move", json={"files": ["zur_sortieren/one.jpg"], "target_album": "Trips"}
    )
    assert moved.status_code == 200
    assert create(client, "2026", "Trips").status_code == 201
    assert client.get("/api/status").json()["can_undo"]
    restored = client.post("/api/action/undo")
    assert restored.status_code == 200
    assert restored.json()["id"] == moved.json()["id"]
    assert (base / "zur_sortieren/one.jpg").read_bytes() == original
    assert (base / "alben/Trips/2026").is_dir()


@pytest.mark.parametrize("parent_length,expected", [(498, 201), (499, 400)])
def test_created_path_must_remain_within_move_api_length_limit(client, base, parent_length, expected):
    parent = "/".join(["a" * 99] * 4 + ["b" * (parent_length - 400)])
    assert len(parent) == parent_length
    try:
        (base / "alben" / parent).mkdir(parents=True)
    except OSError as exc:
        if exc.errno == errno.ENAMETOOLONG or getattr(exc, "winerror", None) == 206:
            pytest.skip("Platform does not support this long parent path")
        raise
    assert create(client, "X", parent).status_code == expected
    assert (base / "alben" / parent / "X").exists() == (expected == 201)


def test_concurrent_creation_of_same_child_is_no_clobber(client, base):
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: create(client, "Summer", "Trips"), range(2)))
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert (base / "alben/Trips/Summer").is_dir()
