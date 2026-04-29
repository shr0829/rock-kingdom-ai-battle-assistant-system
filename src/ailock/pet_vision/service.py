from __future__ import annotations

from pathlib import Path

from .catalog import PetCatalogStore
from .index import PetVisionIndexStore
from .recognizer import PetVisionRecognizer
from .roi import BattlePetCropper
from .samples import PetRecognitionSampleStore
from .types import DualPetRecognitionResult, PetCandidate, PetCropSet, PetRecognitionResult


class PetVisionService:
    LOW_CONFIDENCE_THRESHOLD = 0.55
    BODY_WEIGHT = 0.35
    AVATAR_WEIGHT = 0.65
    AGREEMENT_BONUS = 0.05

    def __init__(self, *, data_dir: Path, database_path: Path) -> None:
        self.data_dir = data_dir
        self.database_path = database_path
        self.catalog = PetCatalogStore(database_path)
        self.samples = PetRecognitionSampleStore(database_path)
        self.cropper = BattlePetCropper(data_dir)
        self.body_index_store = PetVisionIndexStore(data_dir, self.samples, crop_kind="body")
        self.avatar_index_store = PetVisionIndexStore(data_dir, self.samples, crop_kind="avatar")
        self.index_store = self.body_index_store
        self.body_recognizer = PetVisionRecognizer(self.body_index_store)
        self.avatar_recognizer = PetVisionRecognizer(self.avatar_index_store)
        self.recognizer = self.body_recognizer
        self.catalog.ensure_from_defaults(data_dir)

    def recognize_screenshot(self, screenshot_path: Path) -> DualPetRecognitionResult:
        crop_sets = self.cropper.crop_both_sets(screenshot_path)
        player = self._recognize_crop_set(crop_sets["player"])
        opponent = self._recognize_crop_set(crop_sets["opponent"])
        return DualPetRecognitionResult(
            player=self._normalize_result(player),
            opponent=self._normalize_result(opponent),
            screenshot_path=str(screenshot_path),
        )

    def save_confirmation(
        self,
        result: DualPetRecognitionResult,
        *,
        player_name: str,
        opponent_name: str,
    ) -> tuple[int, list[int]]:
        player = self._get_or_create_confirmed_entry(player_name)
        opponent = self._get_or_create_confirmed_entry(opponent_name)
        event_id = self.samples.create_event(result)
        sample_ids = [
            self.samples.save_confirmed_sample(
                event_id=event_id,
                result=result.player,
                pet_id=player.id,
                confirmed_name=player.name,
            ),
            self.samples.save_confirmed_sample(
                event_id=event_id,
                result=result.opponent,
                pet_id=opponent.id,
                confirmed_name=opponent.name,
            ),
        ]
        self.body_index_store.rebuild_index()
        self.avatar_index_store.rebuild_index()
        return event_id, sample_ids

    def list_catalog_names(self, limit: int = 2000) -> list[str]:
        return self.catalog.list_names(limit=limit)

    def _get_or_create_confirmed_entry(self, name: str):
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("确认入库前必须填写宠物名。")
        existing = self.catalog.find_by_name(cleaned)
        if existing is not None:
            return existing
        pet_id = self.catalog.upsert(name=cleaned, aliases=[cleaned], source="user_confirmation")
        created = self.catalog.find_by_name(cleaned)
        if created is None:
            raise RuntimeError(f"保存玩家输入宠物名失败：{cleaned}")
        return created

    def _recognize_crop_set(self, crop_set: PetCropSet) -> PetRecognitionResult:
        body_result = self.body_recognizer.recognize(crop_set.body)
        avatar_result = self.avatar_recognizer.recognize(crop_set.avatar)
        fused_candidates, score_breakdown = self._fuse_candidates(
            body_result.top_candidates,
            avatar_result.top_candidates,
        )
        score_breakdown.update(
            {
                "body_index": body_result.score_breakdown,
                "avatar_index": avatar_result.score_breakdown,
            }
        )
        best = fused_candidates[0] if fused_candidates else None
        if fused_candidates:
            source = "dual_channel_fusion" if avatar_result.top_candidates else "body_feature_index"
        else:
            source = "no_index"
        return PetRecognitionResult(
            side=crop_set.side,
            pet_id=best.pet_id if best else None,
            name=best.name if best else "",
            confidence=best.confidence if best else 0.0,
            top_candidates=fused_candidates,
            body_candidates=body_result.top_candidates,
            avatar_candidates=avatar_result.top_candidates,
            score_breakdown=score_breakdown,
            source=source,
            crop_path=crop_set.body.path,
            crop=crop_set.body,
            crop_set=crop_set,
        )

    def _fuse_candidates(
        self,
        body_candidates: list[PetCandidate],
        avatar_candidates: list[PetCandidate],
    ) -> tuple[list[PetCandidate], dict[str, object]]:
        body_weight, avatar_weight = self._channel_weights(body_candidates, avatar_candidates)
        by_key: dict[tuple[str, str], dict[str, object]] = {}

        self._add_weighted_candidates(by_key, body_candidates, channel="body", weight=body_weight)
        self._add_weighted_candidates(by_key, avatar_candidates, channel="avatar", weight=avatar_weight)

        fused: list[PetCandidate] = []
        for item in by_key.values():
            channels = set(item["channels"])
            channel_scores = item["channel_scores"]
            score = sum(float(value) for value in channel_scores.values())  # type: ignore[union-attr]
            if {"avatar", "body"}.issubset(channels):
                score += self.AGREEMENT_BONUS
            fused.append(
                PetCandidate(
                    pet_id=item["pet_id"],  # type: ignore[arg-type]
                    name=str(item["name"]),
                    confidence=round(max(0.0, min(1.0, score)), 4),
                    source="fusion",
                    channel="+".join(sorted(channels)),
                )
            )
        fused.sort(key=lambda candidate: candidate.confidence, reverse=True)
        return fused[: self.body_recognizer.top_k], {
            "body_weight": body_weight,
            "avatar_weight": avatar_weight,
            "agreement_bonus": self.AGREEMENT_BONUS,
            "body_top": body_candidates[0].to_dict() if body_candidates else None,
            "avatar_top": avatar_candidates[0].to_dict() if avatar_candidates else None,
        }

    @classmethod
    def _channel_weights(
        cls,
        body_candidates: list[PetCandidate],
        avatar_candidates: list[PetCandidate],
    ) -> tuple[float, float]:
        if body_candidates and avatar_candidates:
            if not any(candidate.channel.startswith("avatar:confirmed_avatar") for candidate in avatar_candidates):
                return 1.0, 0.15
            return cls.BODY_WEIGHT, cls.AVATAR_WEIGHT
        if body_candidates:
            return 1.0, 0.0
        if avatar_candidates:
            return 0.0, 1.0
        return 0.0, 0.0

    @staticmethod
    def _add_weighted_candidates(
        by_key: dict[tuple[str, str], dict[str, object]],
        candidates: list[PetCandidate],
        *,
        channel: str,
        weight: float,
    ) -> None:
        for candidate in candidates:
            key = ("id", str(candidate.pet_id)) if candidate.pet_id is not None else ("name", candidate.name)
            item = by_key.setdefault(
                key,
                {
                    "pet_id": candidate.pet_id,
                    "name": candidate.name,
                    "channel_scores": {},
                    "channels": set(),
                },
            )
            channel_scores = item["channel_scores"]
            previous_score = float(channel_scores.get(channel, 0.0))  # type: ignore[union-attr]
            channel_scores[channel] = max(previous_score, candidate.confidence * weight)  # type: ignore[index]
            item["channels"].add(channel)  # type: ignore[union-attr]

    def _normalize_result(self, result: PetRecognitionResult) -> PetRecognitionResult:
        if not result.name:
            return result
        entry = self.catalog.normalize_candidate(result.name)
        if entry is None:
            return result
        top_candidates = [self._normalize_candidate(candidate) for candidate in result.top_candidates]
        body_candidates = [self._normalize_candidate(candidate) for candidate in result.body_candidates]
        avatar_candidates = [self._normalize_candidate(candidate) for candidate in result.avatar_candidates]
        return PetRecognitionResult(
            side=result.side,
            pet_id=entry.id,
            name=entry.name,
            confidence=result.confidence,
            top_candidates=top_candidates,
            body_candidates=body_candidates,
            avatar_candidates=avatar_candidates,
            score_breakdown=result.score_breakdown,
            source=result.source,
            crop_path=result.crop_path,
            crop=result.crop,
            crop_set=result.crop_set,
        )

    def _normalize_candidate(self, candidate: PetCandidate) -> PetCandidate:
        entry = self.catalog.normalize_candidate(candidate.name)
        if entry is None:
            return candidate
        return PetCandidate(
            pet_id=entry.id,
            name=entry.name,
            confidence=candidate.confidence,
            source=candidate.source,
            channel=candidate.channel,
        )
