from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .features import ImageFeatureExtractor
from .samples import PetRecognitionSampleStore


@dataclass(frozen=True, slots=True)
class IndexedPetFeature:
    pet_id: int | None
    name: str
    feature: list[float]
    source: str
    path: str
    source_kind: str = "unknown"


class PetVisionIndexStore:
    INDEX_SCHEMA_VERSION = 3

    def __init__(self, data_dir: Path, sample_store: PetRecognitionSampleStore, crop_kind: str = "body") -> None:
        if crop_kind not in {"avatar", "body"}:
            raise ValueError(f"unsupported pet vision index kind: {crop_kind}")
        self.data_dir = data_dir
        self.sample_store = sample_store
        self.crop_kind = crop_kind
        self.index_dir = data_dir / "pet_vision" / "index"
        self.index_path = self.index_dir / ("pet_avatar_features.npz" if crop_kind == "avatar" else "pet_features.npz")
        self.artworks_dir = data_dir / "pet_vision" / "artworks"
        self.extractor = ImageFeatureExtractor()

    def ensure_index(self) -> list[IndexedPetFeature]:
        features = self.load_index()
        if features:
            return features
        return self.rebuild_index()

    def rebuild_index(self) -> list[IndexedPetFeature]:
        self.index_dir.mkdir(parents=True, exist_ok=True)
        features: list[IndexedPetFeature] = []
        for source in self._iter_sources():
            local_path = Path(str(source.get("local_path") or ""))
            try:
                if local_path.exists():
                    feature = self.extractor.extract_from_path(local_path)
                else:
                    image_bytes = source.get("image_bytes")
                    if not isinstance(image_bytes, bytes):
                        continue
                    feature = self.extractor.extract_from_bytes(image_bytes)
            except ValueError:
                continue
            name = self._display_name(source, local_path)
            pet_id_value = source.get("pet_id")
            catalog_name = str(source.get("catalog_name") or "")
            if source.get("source_kind") == "artwork_reference" and catalog_name and name != catalog_name:
                pet_id_value = None
            features.append(
                IndexedPetFeature(
                    pet_id=int(pet_id_value) if pet_id_value not in (None, "") else None,
                    name=name,
                    feature=feature,
                    source=str(source.get("source_url") or local_path),
                    path=str(local_path),
                    source_kind=str(source.get("source_kind") or "unknown"),
                )
            )
        self._write_index(features)
        return features

    def load_index(self) -> list[IndexedPetFeature]:
        if not self.index_path.exists():
            return []
        try:
            with zipfile.ZipFile(self.index_path, "r") as archive:
                payload = json.loads(archive.read("features.json").decode("utf-8"))
        except (OSError, KeyError, json.JSONDecodeError, zipfile.BadZipFile):
            return []
        if payload.get("version") != self._index_version:
            return []
        return [self._feature_from_payload(item) for item in payload.get("features", [])]

    def _iter_sources(self) -> list[dict[str, object]]:
        if self.crop_kind == "avatar":
            confirmed_sources = [
                {**source, "source_kind": "confirmed_avatar"}
                for source in self.sample_store.load_confirmed_sample_sources("avatar")
            ]
            if confirmed_sources:
                return confirmed_sources
            return self._artwork_reference_sources()

        sources = [
            *self._artwork_reference_sources(),
            *({**source, "source_kind": "confirmed_body"} for source in self.sample_store.load_confirmed_sample_sources("body")),
        ]
        return sources

    def _artwork_reference_sources(self) -> list[dict[str, object]]:
        sources = [
            {**source, "source_kind": "artwork_reference"}
            for source in self.sample_store.load_artwork_sources()
        ]
        if self.artworks_dir.exists():
            known_paths = {self._path_key(Path(str(item.get("local_path") or ""))) for item in sources}
            for path in sorted(self.artworks_dir.rglob("*")):
                if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
                    key = self._path_key(path)
                    if key not in known_paths:
                        known_paths.add(key)
                        sources.append(
                            {
                                "name": path.stem,
                                "local_path": str(path),
                                "source_url": str(path),
                                "source_kind": "artwork_reference",
                            }
                        )
        return sources

    def _write_index(self, features: list[IndexedPetFeature]) -> None:
        payload: dict[str, Any] = {
            "version": self._index_version,
            "feature_version": self.extractor.feature_version,
            "feature_backend": self.extractor.backend_name,
            "crop_kind": self.crop_kind,
            "features": [
                {
                    "pet_id": item.pet_id,
                    "name": item.name,
                    "feature": item.feature,
                    "source": item.source,
                    "path": item.path,
                    "source_kind": item.source_kind,
                }
                for item in features
            ],
        }
        with zipfile.ZipFile(self.index_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("features.json", json.dumps(payload, ensure_ascii=False))

    @property
    def _index_version(self) -> str:
        return f"{self.extractor.feature_version}:{self.INDEX_SCHEMA_VERSION}:{self.crop_kind}"

    @staticmethod
    def _display_name(source: dict[str, object], local_path: Path) -> str:
        source_kind = str(source.get("source_kind") or "")
        raw = str(source.get("name") or local_path.stem)
        if source_kind == "artwork_reference":
            cleaned = PetVisionIndexStore._clean_reference_name(raw)
            if cleaned:
                return cleaned
        return str(source.get("catalog_name") or raw or local_path.stem)

    @staticmethod
    def _clean_reference_name(value: str) -> str:
        cleaned = Path(value).stem.strip()
        while True:
            old = cleaned
            for suffix in ("精灵立绘", "进化链"):
                cleaned = cleaned.removesuffix(suffix).strip()
            cleaned = cleaned.rsplit("-", 1)[0].strip() if cleaned.rsplit("-", 1)[-1].isdigit() else cleaned
            if cleaned == old:
                return cleaned

    @staticmethod
    def _path_key(path: Path) -> str:
        try:
            return str(path.resolve()).lower()
        except OSError:
            return str(path).lower()

    @staticmethod
    def _feature_from_payload(item: dict[str, object]) -> IndexedPetFeature:
        pet_id_value = item.get("pet_id")
        return IndexedPetFeature(
            pet_id=int(pet_id_value) if pet_id_value not in (None, "") else None,
            name=str(item.get("name") or ""),
            feature=[float(value) for value in item.get("feature", [])],
            source=str(item.get("source") or ""),
            path=str(item.get("path") or ""),
            source_kind=str(item.get("source_kind") or "unknown"),
        )
