"""An OS-held lock prevents two application processes using the same library."""

from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO


class LibraryProcessLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: BinaryIO | None = None

    def acquire(self) -> None:
        if self.path.is_symlink():
            raise ValueError("Die Bibliothek-Sperrdatei darf kein symbolischer Link sein.")
        self.handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                if self.path.stat().st_size == 0:
                    self.handle.write(b"0")
                    self.handle.flush()
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            self.handle = None
            raise RuntimeError(
                "Diese Bibliothek wird bereits von einem anderen Folio-Prozess verwendet. Bitte nur eine Instanz pro Basis-Pfad starten."
            ) from exc

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None
