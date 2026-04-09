from __future__ import annotations

"""Persistent document storage backed by SQLite."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from .constants import DATABASE_PATH, EXPORT_DIR, FILE_RETENTION_HOURS, UPLOAD_DIR


class SQLiteDocumentStore:
    """Store document payloads as JSON blobs for local durability."""

    def __init__(self, database_path: Path = DATABASE_PATH) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._initialize()

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.database_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._get_connection()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def save_document(self, document_id: str, payload: Dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        filename = str(payload.get("filename") or "")
        payload_json = json.dumps(payload, ensure_ascii=False)
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO documents (document_id, filename, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    filename = excluded.filename,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (document_id, filename, payload_json, now, now),
            )

    def get_document(self, document_id: str) -> Optional[Dict[str, Any]]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
        if not row:
            return None
        return json.loads(row["payload_json"])

    def cleanup_expired_artifacts(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=FILE_RETENTION_HOURS)
        for folder in (UPLOAD_DIR, EXPORT_DIR):
            if not folder.exists():
                continue
            for path in folder.iterdir():
                if not path.is_file():
                    continue
                modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                if modified < cutoff:
                    path.unlink(missing_ok=True)
