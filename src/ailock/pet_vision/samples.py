from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .types import DualPetRecognitionResult, PetCandidate, PetRecognitionResult


class PetRecognitionSampleStore:
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
                CREATE TABLE IF NOT EXISTS pet_recognition_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    screenshot_path TEXT,
                    player_pet_id INTEGER,
                    opponent_pet_id INTEGER,
                    player_confidence REAL,
                    opponent_confidence REAL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pet_recognition_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER NOT NULL,
                    side TEXT NOT NULL,
                    pet_id INTEGER NOT NULL,
                    confirmed_name TEXT NOT NULL,
                    predicted_name TEXT,
                    confidence REAL,
                    top_candidates TEXT NOT NULL,
                    crop_png BLOB NOT NULL,
                    crop_path TEXT,
                    roi_json TEXT NOT NULL,
                    avatar_crop_png BLOB,
                    avatar_crop_path TEXT,
                    avatar_roi_json TEXT,
                    body_crop_png BLOB,
                    body_crop_path TEXT,
                    body_roi_json TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pet_artworks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pet_id INTEGER,
                    name TEXT NOT NULL,
                    source_url TEXT NOT NULL UNIQUE,
                    local_path TEXT,
                    image_bytes BLOB NOT NULL,
                    content_type TEXT,
                    source TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pet_artworks_pet_id ON pet_artworks(pet_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pet_samples_event ON pet_recognition_samples(event_id)")
            self._ensure_sample_columns(conn)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _ensure_sample_columns(conn: sqlite3.Connection) -> None:
        existing_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(pet_recognition_samples)").fetchall()
        }
        migrations = {
            "avatar_crop_png": "ALTER TABLE pet_recognition_samples ADD COLUMN avatar_crop_png BLOB",
            "avatar_crop_path": "ALTER TABLE pet_recognition_samples ADD COLUMN avatar_crop_path TEXT",
            "avatar_roi_json": "ALTER TABLE pet_recognition_samples ADD COLUMN avatar_roi_json TEXT",
            "body_crop_png": "ALTER TABLE pet_recognition_samples ADD COLUMN body_crop_png BLOB",
            "body_crop_path": "ALTER TABLE pet_recognition_samples ADD COLUMN body_crop_path TEXT",
            "body_roi_json": "ALTER TABLE pet_recognition_samples ADD COLUMN body_roi_json TEXT",
        }
        for column, statement in migrations.items():
            if column not in existing_columns:
                conn.execute(statement)

    def create_event(self, result: DualPetRecognitionResult) -> int:
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                INSERT INTO pet_recognition_events (
                    screenshot_path, player_pet_id, opponent_pet_id,
                    player_confidence, opponent_confidence, created_at
                ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    result.screenshot_path,
                    result.player.pet_id,
                    result.opponent.pet_id,
                    result.player.confidence,
                    result.opponent.confidence,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def save_confirmed_sample(
        self,
        *,
        event_id: int,
        result: PetRecognitionResult,
        pet_id: int,
        confirmed_name: str,
    ) -> int:
        body_crop = result.crop_set.body if result.crop_set is not None else result.crop
        avatar_crop = result.crop_set.avatar if result.crop_set is not None else None
        if body_crop is None:
            raise ValueError("pet body crop is required before saving a confirmed sample")
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                INSERT INTO pet_recognition_samples (
                    event_id, side, pet_id, confirmed_name, predicted_name, confidence,
                    top_candidates, crop_png, crop_path, roi_json,
                    avatar_crop_png, avatar_crop_path, avatar_roi_json,
                    body_crop_png, body_crop_path, body_roi_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    event_id,
                    result.side,
                    pet_id,
                    confirmed_name,
                    result.name,
                    result.confidence,
                    json.dumps([candidate.to_dict() for candidate in result.top_candidates], ensure_ascii=False),
                    body_crop.image_bytes,
                    body_crop.path,
                    json.dumps(body_crop.roi, ensure_ascii=False),
                    avatar_crop.image_bytes if avatar_crop is not None else None,
                    avatar_crop.path if avatar_crop is not None else None,
                    json.dumps(avatar_crop.roi, ensure_ascii=False) if avatar_crop is not None else None,
                    body_crop.image_bytes,
                    body_crop.path,
                    json.dumps(body_crop.roi, ensure_ascii=False),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def upsert_artwork(
        self,
        *,
        name: str,
        source_url: str,
        image_bytes: bytes,
        pet_id: int | None = None,
        local_path: str = "",
        content_type: str = "",
        source: str = "",
    ) -> int:
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                INSERT INTO pet_artworks (
                    pet_id, name, source_url, local_path, image_bytes, content_type, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(source_url) DO UPDATE SET
                    pet_id=excluded.pet_id,
                    name=excluded.name,
                    local_path=excluded.local_path,
                    image_bytes=excluded.image_bytes,
                    content_type=excluded.content_type,
                    source=excluded.source,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (pet_id, name, source_url, local_path, image_bytes, content_type, source),
            )
            conn.commit()
            if cursor.lastrowid:
                return int(cursor.lastrowid)
            row = conn.execute("SELECT id FROM pet_artworks WHERE source_url = ?", (source_url,)).fetchone()
            return int(row["id"])
        finally:
            conn.close()

    def load_artwork_sources(self) -> list[dict[str, object]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT a.pet_id, a.name, a.source_url, a.local_path, a.image_bytes, c.name AS catalog_name
                FROM pet_artworks a
                LEFT JOIN pet_catalog c ON c.id = a.pet_id
                ORDER BY a.name
                """
            ).fetchall()
        finally:
            conn.close()
        return [dict(row) for row in rows]

    def load_confirmed_sample_sources(self, crop_kind: str = "body") -> list[dict[str, object]]:
        if crop_kind not in {"avatar", "body"}:
            raise ValueError(f"unsupported pet sample crop kind: {crop_kind}")
        conn = self._connect()
        try:
            if crop_kind == "avatar":
                rows = conn.execute(
                    """
                    SELECT
                        pet_id,
                        confirmed_name AS name,
                        avatar_crop_path AS local_path,
                        avatar_crop_png AS image_bytes,
                        '' AS source_url
                    FROM pet_recognition_samples
                    WHERE avatar_crop_png IS NOT NULL
                    ORDER BY created_at DESC
                    """
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT
                        pet_id,
                        confirmed_name AS name,
                        COALESCE(NULLIF(body_crop_path, ''), crop_path) AS local_path,
                        COALESCE(body_crop_png, crop_png) AS image_bytes,
                        '' AS source_url
                    FROM pet_recognition_samples
                    WHERE COALESCE(body_crop_png, crop_png) IS NOT NULL
                    ORDER BY created_at DESC
                    """
                ).fetchall()
        finally:
            conn.close()
        return [dict(row) for row in rows]

    @staticmethod
    def candidates_json(candidates: list[PetCandidate]) -> str:
        return json.dumps([candidate.to_dict() for candidate in candidates], ensure_ascii=False)
