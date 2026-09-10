"""SQLite persistence for knowledge bases, documents, messages, and notes."""

import sqlite3
from contextlib import contextmanager
import uuid
from pathlib import Path
from typing import Any


class SQLiteStore:
    """Small transactional business store for the first project version."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_bases (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT NOT NULL,
                    knowledge_base_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    page_count INTEGER NOT NULL,
                    chunk_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id, knowledge_base_id),
                    FOREIGN KEY (knowledge_base_id)
                        REFERENCES knowledge_bases(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS notes (
                    id TEXT PRIMARY KEY,
                    knowledge_base_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (knowledge_base_id)
                        REFERENCES knowledge_bases(id) ON DELETE CASCADE
                );
                """
            )

    def create_knowledge_base(self, name: str) -> dict[str, Any]:
        knowledge_base_id = uuid.uuid4().hex
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO knowledge_bases (id, name) VALUES (?, ?)",
                (knowledge_base_id, name.strip()),
            )
        return {"id": knowledge_base_id, "name": name.strip()}

    def list_knowledge_bases(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, name, created_at FROM knowledge_bases ORDER BY created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def knowledge_base_exists(self, knowledge_base_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM knowledge_bases WHERE id = ?",
                (knowledge_base_id,),
            ).fetchone()
        return row is not None

    def add_document(
        self,
        *,
        document_id: str,
        knowledge_base_id: str,
        filename: str,
        file_path: str,
        page_count: int,
        chunk_count: int,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO documents
                    (id, knowledge_base_id, filename, file_path, page_count, chunk_count)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    knowledge_base_id,
                    filename,
                    file_path,
                    page_count,
                    chunk_count,
                ),
            )

    def list_documents(self, knowledge_base_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, filename, page_count, chunk_count, created_at
                FROM documents
                WHERE knowledge_base_id = ?
                ORDER BY created_at DESC
                """,
                (knowledge_base_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_document(
        self,
        knowledge_base_id: str,
        document_id: str,
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, knowledge_base_id, filename, file_path,
                       page_count, chunk_count, created_at
                FROM documents
                WHERE knowledge_base_id = ? AND id = ?
                """,
                (knowledge_base_id, document_id),
            ).fetchone()
        return dict(row) if row else None

    def delete_document(
        self,
        knowledge_base_id: str,
        document_id: str,
    ) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM documents WHERE knowledge_base_id = ? AND id = ?",
                (knowledge_base_id, document_id),
            )
        return cursor.rowcount > 0

    def delete_knowledge_base(self, knowledge_base_id: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM knowledge_bases WHERE id = ?",
                (knowledge_base_id,),
            )
        return cursor.rowcount > 0

    def add_message(self, thread_id: str, role: str, content: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO messages (thread_id, role, content) VALUES (?, ?, ?)",
                (thread_id, role, content),
            )

    def get_messages(self, thread_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content, created_at
                FROM messages
                WHERE thread_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (thread_id, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def save_note(self, knowledge_base_id: str, title: str, content: str) -> dict[str, Any]:
        note_id = uuid.uuid4().hex
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO notes (id, knowledge_base_id, title, content) VALUES (?, ?, ?, ?)",
                (note_id, knowledge_base_id, title.strip(), content.strip()),
            )
        return {"id": note_id, "title": title.strip(), "content": content.strip()}

    def search_notes(self, knowledge_base_id: str, query: str) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, title, content, created_at
                FROM notes
                WHERE knowledge_base_id = ?
                  AND (title LIKE ? OR content LIKE ?)
                ORDER BY created_at DESC
                """,
                (knowledge_base_id, pattern, pattern),
            ).fetchall()
        return [dict(row) for row in rows]
