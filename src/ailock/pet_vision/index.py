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


class PetVisionIndexStore:
    def __init__(self, data_dir: Path, sample_store: PetRecognitionSampleStore) -> None:
        self.data_dir = data_dir
        self.sample_store = sample_store
        self.index_dir = data_dir / "pet_vision" / "index"
        self.index_path = self.index_dir / "pet_features.npz"
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
            name = str(source.get("catalog_name") or source.get("name") or local_path.stem)
            pet_id_value = source.get("pet_id")
            features.append(
                IndexedPetFeature(
                    pet_id=int(pet_id_value) if pet_id_value not in (None, "") else None,
                    name=name,
                    feature=feature,
                    source=str(source.get("source_url") or local_path),
                    path=str(local_path),
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
        return [self._feature_from_payload(item) for item in payload.get("features", [])]

    def _iter_sources(self) -> list[dict[str, object]]:
        sources = [*self.sample_store.load_artwork_sources(), *self.sample_store.load_confirmed_sample_sources()]
        if self.artworks_dir.exists():
            known_paths = {str(item.get("local_path") or "") for item in sources}
            for path in sorted(self.artworks_dir.rglob("*")):
                if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
                    if str(path) not in known_paths:
                        sources.append({"name": path.stem, "local_path": str(path), "source_url": str(path)})
        return sources

    def _write_index(self, features: list[IndexedPetFeature]) -> None:
        payload: dict[str, Any] = {
            "version": 1,
            "features": [
                {
                    "pet_id": item.pet_id,
                    "name": item.name,
                    "feature": item.feature,
                    "source": item.source,
                    "path": item.path,
                }
                for item in features
            ],
        }
        with zipfile.ZipFile(self.index_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("features.json", json.dumps(payload, ensure_ascii=False))

    @staticmethod
    def _feature_from_payload(item: dict[str, object]) -> IndexedPetFeature:
        pet_id_value = item.get("pet_id")
        return IndexedPetFeature(
            pet_id=int(pet_id_value) if pet_id_value not in (None, "") else None,
            name=str(item.get("name") or ""),
            feature=[float(value) for value in item.get("feature", [])],
            source=str(item.get("source") or ""),
            path=str(item.get("path") or ""),
        )
