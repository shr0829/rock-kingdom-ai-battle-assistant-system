from __future__ import annotations

from .features import ImageFeatureExtractor, cosine_similarity
from .index import IndexedPetFeature, PetVisionIndexStore
from .types import PetCandidate, PetCrop, PetRecognitionResult


class PetVisionRecognizer:
    def __init__(self, index_store: PetVisionIndexStore, top_k: int = 5) -> None:
        self.index_store = index_store
        self.top_k = top_k
        self.extractor = ImageFeatureExtractor()

    def recognize(self, crop: PetCrop) -> PetRecognitionResult:
        indexed_features = self.index_store.ensure_index()
        breakdown = {
            "crop_kind": self.index_store.crop_kind,
            "feature_backend": self.extractor.backend_name,
            "reference_count": len(indexed_features),
            "source_counts": self._source_counts(indexed_features),
        }
        if not indexed_features:
            return PetRecognitionResult(
                side=crop.side,
                pet_id=None,
                name="",
                confidence=0.0,
                top_candidates=[],
                score_breakdown=breakdown,
                source="no_index",
                crop_path=crop.path,
                crop=crop,
            )
        query_feature = self.extractor.extract_from_bytes(crop.image_bytes)
        ranked = self._rank(query_feature, indexed_features)
        top_candidates = [
            PetCandidate(
                pet_id=item.pet_id,
                name=item.name,
                confidence=round(score, 4),
                source=item.source,
                channel=f"{self.index_store.crop_kind}:{item.source_kind}",
            )
            for item, score in ranked[: self.top_k]
        ]
        best = top_candidates[0] if top_candidates else None
        return PetRecognitionResult(
            side=crop.side,
            pet_id=best.pet_id if best else None,
            name=best.name if best else "",
            confidence=best.confidence if best else 0.0,
            top_candidates=top_candidates,
            score_breakdown=breakdown,
            source="local_feature_index",
            crop_path=crop.path,
            crop=crop,
        )

    @staticmethod
    def _rank(
        query_feature: list[float],
        indexed_features: list[IndexedPetFeature],
    ) -> list[tuple[IndexedPetFeature, float]]:
        scored = [(item, cosine_similarity(query_feature, item.feature)) for item in indexed_features]
        scored.sort(key=lambda item: item[1], reverse=True)
        unique: list[tuple[IndexedPetFeature, float]] = []
        seen: set[tuple[str, str]] = set()
        for item, score in scored:
            key = ("id", str(item.pet_id)) if item.pet_id is not None else ("name", item.name)
            if key in seen:
                continue
            seen.add(key)
            unique.append((item, score))
        return unique

    @staticmethod
    def _source_counts(indexed_features: list[IndexedPetFeature]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in indexed_features:
            counts[item.source_kind] = counts.get(item.source_kind, 0) + 1
        return counts
