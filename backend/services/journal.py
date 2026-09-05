"""SQLite write-ahead journal for batch operations and persistent undo history."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from backend.services.indexer import utc_now


class Journal:
    def __init__(self, path: Path) -> None:
        self.path = path
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT NOT NULL UNIQUE,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    undone_at TEXT,
                    error TEXT,
                    files TEXT NOT NULL
                )
            """)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def decode(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data.pop("sequence", None)
        data["files"] = json.loads(data["files"])
        return data

    def begin(self, action: str, files: list[dict[str, Any]]) -> str:
        identifier = uuid.uuid4().hex
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO transactions (id, action, status, created_at, files) VALUES (?, ?, 'pending', ?, ?)",
                (identifier, action, utc_now(), json.dumps(files, ensure_ascii=False)),
            )
        return identifier

    def update(self, identifier: str, status: str, error: str | None = None) -> None:
        with self.connection() as connection:
            connection.execute(
                "UPDATE transactions SET status=?, error=?, undone_at=? WHERE id=?",
                (status, error, utc_now() if status == "undone" else None, identifier),
            )

    def get(self, identifier: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM transactions WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise KeyError(identifier)
        return self.decode(row)

    def latest(self) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM transactions WHERE status='completed' ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
        return self.decode(row) if row else None

    def list(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM transactions ORDER BY sequence DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
        return [self.decode(row) for row in rows]

    def unfinished(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM transactions WHERE status IN ('pending', 'undoing') ORDER BY sequence DESC"
            ).fetchall()
        return [self.decode(row) for row in rows]
