"""Filesystem operations, serialized in one native application process."""

from __future__ import annotations

import errno
import logging
import os
import shutil
import stat
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.config import Settings
from backend.services.filenames import DestinationNames, name_key
from backend.services.indexer import ImageIndex, sha1_file
from backend.services.journal import Journal
from backend.services.security import LibraryError, SafePaths

logger = logging.getLogger(__name__)


class IncompleteTransferError(LibraryError):
    """A transfer left a file that is unsafe to remove automatically."""

    def __init__(self) -> None:
        super().__init__(
            "Eine unvollständige Verschiebung muss geprüft werden. Dateien bleiben erhalten; siehe Protokoll.",
            409,
        )


def _file_state(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _owns_file(path: Path, created: os.stat_result) -> bool:
    try:
        current = path.lstat()
    except FileNotFoundError:
        return False
    # Do not follow a replacement symlink, or guess ownership without a file ID.
    return bool(created.st_ino) and stat.S_ISREG(current.st_mode) and os.path.samestat(current, created)


def transfer_no_replace(source: Path, destination: Path, expected_hash: str) -> None:
    """Move without overwrite, verifying identity as well as content.

    Use hard link + unlink on one volume; otherwise fsync an exclusively created
    copy. An inode/file ID captured from our open handle prevents cleanup from
    deleting an unrelated replacement at the destination path.
    """
    initial = source.lstat()
    if not stat.S_ISREG(initial.st_mode):
        raise LibraryError("Die Quelle ist keine reguläre Bilddatei.", 415)
    if sha1_file(source) != expected_hash or _file_state(source.lstat()) != _file_state(initial):
        raise LibraryError("Die Quelldatei wurde verändert. Bitte neu einlesen.", 409)
    created: os.stat_result | None = None
    linked = False
    try:
        try:
            os.link(source, destination, follow_symlinks=False)
            linked = True
            created = initial
        except FileExistsError as exc:
            raise LibraryError(
                "Eine Zieldatei wurde zwischenzeitlich angelegt. Nichts wird überschrieben.", 409
            ) from exc
        except OSError as exc:
            if exc.errno not in {
                errno.EXDEV,
                errno.EPERM,
                errno.EACCES,
                errno.ENOSYS,
                errno.ENOTSUP,
                errno.EOPNOTSUPP,
            }:
                raise
            with destination.open("xb") as target:
                created = os.fstat(target.fileno())
                with source.open("rb") as original:
                    if _file_state(os.fstat(original.fileno())) != _file_state(initial):
                        raise LibraryError("Die Quelldatei wurde zwischenzeitlich ersetzt.", 409)
                    shutil.copyfileobj(original, target, length=1024 * 1024)
                target.flush()
                os.fsync(target.fileno())
        if not _owns_file(destination, created):
            raise LibraryError("Die Zieldatei wurde von einem anderen Programm ersetzt.", 409)
        if not linked:
            shutil.copystat(source, destination, follow_symlinks=False)
        if sha1_file(destination) != expected_hash:
            raise LibraryError(
                "Die Zieldatei konnte nicht verifiziert werden. Die Quelle bleibt erhalten.", 409
            )
        current = source.lstat()
        # Creating a hard link changes ctime; identity, size and mtime must remain stable.
        if not stat.S_ISREG(current.st_mode) or _file_state(current)[:4] != _file_state(initial)[:4]:
            raise LibraryError("Die Quelldatei wurde während des Verschiebens verändert.", 409)
        if not _owns_file(destination, created):
            raise LibraryError("Die Zieldatei wurde zwischenzeitlich ersetzt.", 409)
        source.unlink()
    except BaseException as exc:
        incomplete = False
        if created is not None:
            try:
                if _owns_file(destination, created):
                    # Retain a possible last good copy if the source was replaced/deleted.
                    if _owns_file(source, initial) and sha1_file(source) == expected_hash:
                        destination.unlink()
                    else:
                        incomplete = True
                        logger.warning("Zieldatei bleibt zur Prüfung erhalten: %s", destination)
            except (OSError, LibraryError):
                incomplete = True
                logger.exception("Unvollständige Zieldatei bleibt zur Prüfung erhalten: %s", destination)
        if incomplete and isinstance(exc, Exception):
            raise IncompleteTransferError() from exc
        raise


class Library:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        settings.initialize()
        self.paths = SafePaths(settings.base_path)
        self.lock = threading.RLock()
        self.index_warning: str | None = None
        self.journal = Journal(settings.metadata_path / "journal.sqlite3")
        self.index = ImageIndex(self.paths, settings.metadata_path / "index.json")
        self.recover()

    def rebuild(self) -> dict[str, Any]:
        with self.lock:
            try:
                report = self.index.rebuild()
            except Exception:
                self.index_warning = (
                    "Der Index konnte nicht aktualisiert oder gespeichert werden. "
                    "Abgeschlossene Aktionen bleiben gültig; die Ansicht kann veraltet sein. "
                    "Bitte Ordner neu einlesen."
                )
                raise
            self.index_warning = None
            return report

    def folder(self, relative: str) -> dict[str, Any]:
        with self.lock:
            directory = self.paths.resolve(relative)
            if not directory.is_dir():
                raise LibraryError("Der Quellpfad ist kein Ordner.", 400)
            prefix = relative + "/"
            matches = [path for path in self.index.entries if path.startswith(prefix)]
            children = []
            for child in sorted(directory.iterdir(), key=lambda item: item.name.casefold()):
                if child.name.startswith(".") or child.is_symlink() or not child.is_dir():
                    continue
                try:
                    children.append(self.folder(self.paths.relative(child)))
                except (LibraryError, OSError):
                    logger.warning("Ordner wird übersprungen: %s", child)
            return {
                "name": directory.name,
                "path": relative,
                "count": len(matches),
                "direct_count": sum("/" not in path[len(prefix) :] for path in matches),
                "children": children,
            }

    def albums(self) -> list[dict[str, Any]]:
        return self.folder("alben")["children"]

    def images(self, relative: str, recursive: bool = False) -> dict[str, Any]:
        with self.lock:
            folder = self.paths.resolve(relative)
            if not folder.is_dir():
                raise LibraryError("Der angeforderte Pfad ist kein Ordner.")
            images = []
            prefix = relative + "/"
            for path, entry in sorted(self.index.entries.items(), key=lambda item: item[0].casefold()):
                if not path.startswith(prefix) or (not recursive and "/" in path[len(prefix) :]):
                    continue
                try:
                    self.paths.image(path)
                except LibraryError:
                    continue
                duplicates = self.index.duplicates(path)
                images.append(
                    {
                        "path": path,
                        "name": Path(path).name,
                        "size": entry["size"],
                        "width": entry.get("width"),
                        "height": entry.get("height"),
                        "sha1": entry["sha1"],
                        "is_duplicate": bool(duplicates),
                        "duplicate_of": duplicates,
                        "modified_at": datetime.fromtimestamp(entry["mtime_ns"] / 1e9, UTC).isoformat(),
                        "format": Path(path).suffix[1:].upper(),
                    }
                )
            return {
                "path": relative,
                "images": images,
                "total": len(images),
                "total_size": sum(i["size"] for i in images),
            }

    def status(self) -> dict[str, Any]:
        with self.lock:
            entries = self.index.entries
            source = [entry for path, entry in entries.items() if path.startswith("zur_sortieren/")]

            def count(prefix: str) -> int:
                return sum(path.startswith(prefix + "/") for path in entries)

            def count_albums(nodes: list[dict[str, Any]]) -> int:
                return sum(1 + count_albums(node["children"]) for node in nodes)

            return {
                "base_path": str(self.settings.base_path),
                "source_count": len(source),
                "source_size": sum(entry["size"] for entry in source),
                "album_count": count_albums(self.albums()),
                "album_images": count("alben"),
                "duplicate_count": sum(bool(self.index.duplicates(path)) for path in entries),
                "duplicate_files": count("duplikate"),
                "trash_count": count("trash"),
                "total_size": sum(entry["size"] for entry in entries.values()),
                "can_undo": self.journal.latest() is not None,
                "last_indexed_at": self.index.indexed_at,
                "skipped_files": self.index.skipped,
                "index_warning": self.index_warning,
                "demo": (self.settings.base_path / ".folio-demo.json").is_file(),
            }

    def create_album(self, name: str, parent: str = "") -> dict[str, Any]:
        """Create one album beneath an existing, album-root-relative parent.

        The default keeps old API clients working. Do not mkdir missing parents:
        a stale selection must never silently create a different folder tree.
        """
        with self.lock:
            name = self.paths.album_name(name)
            directory = self.paths.album(parent) if parent else self.paths.resolve("alben", roots=("alben",))
            relative = f"{self.paths.relative(directory)}/{name}"
            if len(relative.removeprefix("alben/")) > 500:
                raise LibraryError("Der relative Album-Pfad darf höchstens 500 Zeichen lang sein.")
            path = self.paths.resolve(relative, roots=("alben",), exists=False)
            conflict = "Im ausgewählten Ordner existiert bereits ein Album oder eine Datei mit diesem Namen."
            # Consistent with portable image naming; equal names in DIFFERENT
            # parents are allowed, but equivalent siblings are not ambiguous.
            key = name_key(name)
            if any(name_key(child.name) == key for child in directory.iterdir()):
                raise LibraryError(conflict, 409)
            try:
                path.mkdir()
            except FileExistsError as exc:
                raise LibraryError(conflict, 409) from exc
            logger.info("Album erstellt: %s", relative)
            return self.folder(relative)

    def move(self, files: list[str], action: str, target_album: str | None = None) -> dict[str, Any]:
        with self.lock:
            if not files or len(files) > 500 or len(files) != len(set(files)):
                raise LibraryError("Bitte 1–500 unterschiedliche Bilder auswählen.")
            if action == "move":
                destination = self.paths.album(target_album or "")
            elif action in ("trash", "duplicates"):
                destination = self.paths.resolve("trash" if action == "trash" else "duplikate")
            else:
                raise LibraryError("Unbekannte Aktion.")
            if action == "duplicates":
                # Verify against the current on-disk album contents, not a stale cache.
                self.rebuild()
            plan: list[dict[str, Any]] = []
            names = DestinationNames(destination)
            for relative in files:
                source = self.paths.image(relative, roots=("zur_sortieren",))
                digest = sha1_file(source)
                if action == "duplicates" and digest not in self.index.album_hashes:
                    raise LibraryError(f"{source.name} ist kein bestätigtes Duplikat eines Albums.", 409)
                target = names.allocate(source.name)
                self.paths.resolve(self.paths.relative(target), exists=False)
                plan.append(
                    {
                        "source": relative,
                        "destination": self.paths.relative(target),
                        "sha1": digest,
                        "size": source.stat().st_size,
                    }
                )
            identifier = self.journal.begin(action, plan)
            finished: list[dict[str, Any]] = []
            try:
                for item in plan:
                    source = self.paths.image(item["source"], roots=("zur_sortieren",))
                    target = self.paths.resolve(item["destination"], exists=False)
                    transfer_no_replace(source, target, item["sha1"])
                    finished.append(item)
                self.journal.update(identifier, "completed")
            except Exception as exc:
                rollback_error = self._rollback(finished, undo=False)
                rollback_error = rollback_error or isinstance(exc, IncompleteTransferError)
                self.journal.update(identifier, "interrupted" if rollback_error else "rolled_back", str(exc))
                self._refresh_after_action()
                if rollback_error:
                    raise LibraryError(
                        "Aktion unterbrochen. Dateien bleiben erhalten; bitte das Protokoll und die Pfade prüfen.",
                        409,
                    ) from exc
                if isinstance(exc, LibraryError):
                    raise
                logger.exception("Verschieben fehlgeschlagen; Batch zurückgesetzt.")
                raise LibraryError(
                    "Verschieben fehlgeschlagen. Schreibrechte und freien Speicher prüfen; die Aktion wurde zurückgesetzt.",
                    409,
                ) from exc
            self._refresh_after_action()
            logger.info("Transaktion %s: %s, %s Bilder", identifier, action, len(plan))
            return self.journal.get(identifier)

    def _rollback(self, finished: list[dict[str, Any]], *, undo: bool) -> bool:
        failed = False
        for item in reversed(finished):
            try:
                source_key, destination_key = ("source", "destination") if undo else ("destination", "source")
                source = self.paths.image(item[source_key])
                target = self.paths.resolve(item[destination_key], exists=False)
                target.parent.mkdir(parents=True, exist_ok=True)
                transfer_no_replace(source, target, item["sha1"])
            except Exception:
                failed = True
                logger.exception("Rollback-Konflikt: %s", item)
        return failed

    def undo(self) -> dict[str, Any]:
        with self.lock:
            transaction = self.journal.latest()
            if not transaction:
                raise LibraryError("Es gibt keine Aktion zum Rückgängigmachen.", 409)
            # Preflight the entire batch before changing any file.
            for item in transaction["files"]:
                original = self.paths.resolve(item["source"], roots=("zur_sortieren",), exists=False)
                destination = self.paths.image(item["destination"])
                if original.exists() or original.is_symlink():
                    raise LibraryError(
                        f"Am ursprünglichen Ort existiert bereits {original.name}. Es wird nichts überschrieben.",
                        409,
                    )
                if sha1_file(destination) != item["sha1"]:
                    raise LibraryError(
                        f"{destination.name} wurde inzwischen verändert. Rückgängig wurde sicher abgebrochen.",
                        409,
                    )
            self.journal.update(transaction["id"], "undoing")
            finished: list[dict[str, Any]] = []
            try:
                for item in reversed(transaction["files"]):
                    source = self.paths.image(item["destination"])
                    target = self.paths.resolve(item["source"], roots=("zur_sortieren",), exists=False)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    transfer_no_replace(source, target, item["sha1"])
                    finished.append(item)
                self.journal.update(transaction["id"], "undone")
            except Exception as exc:
                failed = self._rollback(finished, undo=True)
                failed = failed or isinstance(exc, IncompleteTransferError)
                self.journal.update(transaction["id"], "interrupted" if failed else "completed", str(exc))
                self._refresh_after_action()
                raise LibraryError(
                    "Rückgängig nicht möglich. Dateien bleiben erhalten; bitte das Protokoll prüfen.", 409
                ) from exc
            self._refresh_after_action()
            logger.info("Transaktion rückgängig: %s", transaction["id"])
            return self.journal.get(transaction["id"])

    def _refresh_after_action(self) -> None:
        try:
            self.rebuild()
        except Exception:
            # The journal has already committed. Never misreport a successful move as failed.
            # Report the independent cache problem through /api/status instead.
            logger.exception(
                "Aktion abgeschlossen, aber Index konnte nicht gespeichert werden. Bitte neu einlesen."
            )

    def recover(self) -> None:
        """Roll back unfinished moves; complete unfinished undo, without overwriting."""
        for transaction in self.journal.unfinished():
            try:
                restore = []
                for item in transaction["files"]:
                    original = self.paths.resolve(item["source"], roots=("zur_sortieren",), exists=False)
                    moved = self.paths.resolve(item["destination"], exists=False)
                    if original.exists() and not moved.exists() and sha1_file(original) == item["sha1"]:
                        continue
                    if moved.exists() and not original.exists() and sha1_file(moved) == item["sha1"]:
                        restore.append((moved, original, item["sha1"]))
                    else:
                        raise LibraryError(
                            "Unvollständige Transaktion mit Dateikonflikt; keine Datei wird automatisch gelöscht.",
                            409,
                        )
                for source, destination, digest in reversed(restore):
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    transfer_no_replace(source, destination, digest)
                self.journal.update(
                    transaction["id"], "undone" if transaction["status"] == "undoing" else "rolled_back"
                )
                logger.warning("Unterbrochene Transaktion wiederhergestellt: %s", transaction["id"])
            except Exception as exc:
                self.journal.update(transaction["id"], "interrupted", str(exc))
                logger.exception("Manuelle Prüfung nötig: Transaktion %s", transaction["id"])
