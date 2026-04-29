from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .types import PetCatalogEntry


class PetCatalogStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pet_catalog (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    no TEXT,
                    aliases TEXT NOT NULL DEFAULT '[]',
                    primary_attribute TEXT,
                    secondary_attribute TEXT,
                    source TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pet_catalog_name ON pet_catalog(name)")
            conn.commit()
        finally:
            conn.close()

    def count(self) -> int:
        conn = self._connect()
        try:
            row = conn.execute("SELECT COUNT(*) AS total FROM pet_catalog").fetchone()
        finally:
            conn.close()
        return int(row["total"])

    def import_from_wiki_json(self, path: Path) -> int:
        if not path.exists():
            return 0
        payload = json.loads(path.read_text(encoding="utf-8"))
        imported = 0
        for item in payload:
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            aliases = self._derive_aliases(item)
            self.upsert(
                name=name,
                no=str(item.get("no", "")).strip(),
                aliases=aliases,
                primary_attribute=str(item.get("primary_attribute", "")).strip(),
                secondary_attribute=str(item.get("secondary_attribute", "")).strip(),
                source="rocom_wiki",
            )
            imported += 1
        return imported

    def upsert(
        self,
        *,
        name: str,
        no: str = "",
        aliases: list[str] | None = None,
        primary_attribute: str = "",
        secondary_attribute: str = "",
        source: str = "",
    ) -> int:
        name = name.strip()
        if not name:
            raise ValueError("pet catalog name cannot be empty")
        aliases = self._clean_aliases([*(aliases or []), name])
        conn = self._connect()
        try:
            existing = conn.execute("SELECT * FROM pet_catalog WHERE name = ?", (name,)).fetchone()
            if existing:
                merged_aliases = self._clean_aliases([*self._loads_aliases(existing["aliases"]), *aliases])
                conn.execute(
                    """
                    UPDATE pet_catalog
                    SET no = COALESCE(NULLIF(?, ''), no),
                        aliases = ?,
                        primary_attribute = COALESCE(NULLIF(?, ''), primary_attribute),
                        secondary_attribute = COALESCE(NULLIF(?, ''), secondary_attribute),
                        source = COALESCE(NULLIF(?, ''), source),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        no,
                        json.dumps(merged_aliases, ensure_ascii=False),
                        primary_attribute,
                        secondary_attribute,
                        source,
                        existing["id"],
                    ),
                )
                conn.commit()
                return int(existing["id"])
            cursor = conn.execute(
                """
                INSERT INTO pet_catalog (
                    name, no, aliases, primary_attribute, secondary_attribute, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    name,
                    no,
                    json.dumps(aliases, ensure_ascii=False),
                    primary_attribute,
                    secondary_attribute,
                    source,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def find_by_name(self, name: str) -> PetCatalogEntry | None:
        normalized = self._normalize_text(name)
        if not normalized:
            return None
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM pet_catalog").fetchall()
        finally:
            conn.close()
        for row in rows:
            if self._normalize_text(row["name"]) == normalized:
                return self._entry_from_row(row)
        for row in rows:
            aliases = [self._normalize_text(alias) for alias in self._loads_aliases(row["aliases"])]
            if normalized in aliases:
                return self._entry_from_row(row)
        return None

    def normalize_candidate(self, raw_name: str) -> PetCatalogEntry | None:
        cleaned = raw_name.strip()
        for suffix in ("进化链", "精灵立绘", ".png", ".jpg", ".jpeg", ".webp"):
            cleaned = cleaned.removesuffix(suffix)
        exact = self.find_by_name(cleaned)
        if exact is not None:
            return exact
        hits = self.search(cleaned, limit=1)
        return hits[0] if hits else None

    def search(self, query: str, limit: int = 20) -> list[PetCatalogEntry]:
        normalized = self._normalize_text(query)
        if not normalized:
            return []
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM pet_catalog ORDER BY name LIMIT 5000").fetchall()
        finally:
            conn.close()
        matches: list[tuple[int, PetCatalogEntry]] = []
        for row in rows:
            name_norm = self._normalize_text(row["name"])
            aliases = [self._normalize_text(alias) for alias in self._loads_aliases(row["aliases"])]
            score = 0
            if name_norm == normalized:
                score = 100
            elif normalized in name_norm:
                score = 80
            elif any(alias == normalized for alias in aliases):
                score = 70
            elif any(normalized in alias for alias in aliases):
                score = 50
            if score:
                matches.append((score, self._entry_from_row(row)))
        matches.sort(key=lambda item: (-item[0], item[1].name))
        return [entry for _, entry in matches[:limit]]

    def list_names(self, limit: int = 2000) -> list[str]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT name FROM pet_catalog ORDER BY name LIMIT ?", (limit,)).fetchall()
        finally:
            conn.close()
        return [str(row["name"]) for row in rows]

    def ensure_from_defaults(self, data_dir: Path) -> int:
        if self.count() > 0:
            return 0
        return self.import_from_wiki_json(data_dir / "rocom_wiki" / "pets.json")

    @classmethod
    def _entry_from_row(cls, row: sqlite3.Row) -> PetCatalogEntry:
        return PetCatalogEntry(
            id=int(row["id"]),
            name=str(row["name"]),
            no=str(row["no"] or ""),
            aliases=cls._loads_aliases(row["aliases"]),
            primary_attribute=str(row["primary_attribute"] or ""),
            secondary_attribute=str(row["secondary_attribute"] or ""),
            source=str(row["source"] or ""),
        )

    @staticmethod
    def _derive_aliases(item: dict[str, object]) -> list[str]:
        aliases = []
        for key in ("name", "origin_form", "display_form"):
            value = str(item.get(key, "")).strip()
            if value and value not in {"原始形态", "最终形态"}:
                aliases.append(value)
        return PetCatalogStore._clean_aliases(aliases)

    @staticmethod
    def _loads_aliases(value: str | None) -> list[str]:
        if not value:
            return []
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        return [str(item) for item in payload if str(item).strip()]

    @staticmethod
    def _clean_aliases(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            cleaned = value.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            result.append(cleaned)
        return result

    @staticmethod
    def _normalize_text(value: str) -> str:
        return "".join(value.lower().strip().split())
