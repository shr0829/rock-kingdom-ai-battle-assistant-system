from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from .llm_client import MultimodalClient
from .models import KnowledgeEntry

TEXT_EXTENSIONS = {".txt", ".md"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


class KnowledgeStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_path TEXT NOT NULL UNIQUE,
                    source_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    keywords TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def upsert(self, entry: KnowledgeEntry) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO documents (source_path, source_type, title, content, keywords, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(source_path) DO UPDATE SET
                    source_type=excluded.source_type,
                    title=excluded.title,
                    content=excluded.content,
                    keywords=excluded.keywords,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    entry.source_path,
                    entry.source_type,
                    entry.title,
                    entry.content,
                    json.dumps(entry.keywords, ensure_ascii=False),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def ingest_folder(self, folder: Path, client: MultimodalClient | None = None) -> int:
        imported = 0
        for path in sorted(folder.rglob("*")):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix in TEXT_EXTENSIONS:
                self.upsert(self._entry_from_text(path))
                imported += 1
            elif suffix in IMAGE_EXTENSIONS:
                if client is None:
                    raise RuntimeError("导入图片资料需要先配置大模型 API。")
                self.upsert(self._entry_from_image(path, client))
                imported += 1
        return imported

    def count(self) -> int:
        conn = self._connect()
        try:
            row = conn.execute("SELECT COUNT(*) AS total FROM documents").fetchone()
        finally:
            conn.close()
        return int(row["total"])

    def search(self, query_text: str, limit: int = 5) -> list[KnowledgeEntry]:
        tokens = self._tokenize(query_text)
        if not tokens:
            return []
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM documents ORDER BY updated_at DESC").fetchall()
        finally:
            conn.close()
        hits: list[KnowledgeEntry] = []
        for row in rows:
            keywords = json.loads(row["keywords"])
            haystack = " ".join([row["title"], row["content"], " ".join(keywords)]).lower()
            score = float(sum(2 if token in keywords else 1 for token in tokens if token in haystack))
            if score <= 0:
                continue
            hits.append(
                KnowledgeEntry(
                    source_path=row["source_path"],
                    source_type=row["source_type"],
                    title=row["title"],
                    content=row["content"],
                    keywords=keywords,
                    score=score,
                )
            )
        hits.sort(key=lambda item: item.score, reverse=True)
        return hits[:limit]

    def _entry_from_text(self, path: Path) -> KnowledgeEntry:
        content = path.read_text(encoding="utf-8", errors="ignore").strip()
        summary = content[:1200]
        keywords = self._tokenize(f"{path.stem} {summary}")[:12]
        return KnowledgeEntry(
            source_path=str(path),
            source_type="text",
            title=path.stem,
            content=summary,
            keywords=keywords,
        )

    def _entry_from_image(self, path: Path, client: MultimodalClient) -> KnowledgeEntry:
        payload = client.describe_knowledge_image(path)
        facts = payload.get("facts", [])
        summary = payload.get("summary", "")
        content = "\n".join([summary, *facts]).strip()
        return KnowledgeEntry(
            source_path=str(path),
            source_type="image",
            title=payload.get("title") or path.stem,
            content=content,
            keywords=payload.get("keywords", []),
        )

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [
            token
            for token in re.split(r"[^0-9A-Za-z\u4e00-\u9fff]+", text.lower())
            if token and len(token) > 1
        ]
