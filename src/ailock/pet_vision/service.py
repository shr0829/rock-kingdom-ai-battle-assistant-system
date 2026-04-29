from __future__ import annotations

from pathlib import Path

from .catalog import PetCatalogStore
from .index import PetVisionIndexStore
from .recognizer import PetVisionRecognizer
from .roi import BattlePetCropper
from .samples import PetRecognitionSampleStore
from .types import DualPetRecognitionResult, PetRecognitionResult


class PetVisionService:
    LOW_CONFIDENCE_THRESHOLD = 0.55

    def __init__(self, *, data_dir: Path, database_path: Path) -> None:
        self.data_dir = data_dir
        self.database_path = database_path
        self.catalog = PetCatalogStore(database_path)
        self.samples = PetRecognitionSampleStore(database_path)
        self.cropper = BattlePetCropper(data_dir)
        self.index_store = PetVisionIndexStore(data_dir, self.samples)
        self.recognizer = PetVisionRecognizer(self.index_store)
        self.catalog.ensure_from_defaults(data_dir)

    def recognize_screenshot(self, screenshot_path: Path) -> DualPetRecognitionResult:
        crops = self.cropper.crop_both(screenshot_path)
        player = self.recognizer.recognize(crops["player"])
        opponent = self.recognizer.recognize(crops["opponent"])
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
        player = self.catalog.find_by_name(player_name)
        opponent = self.catalog.find_by_name(opponent_name)
        missing = [name for name, entry in ((player_name, player), (opponent_name, opponent)) if entry is None]
        if missing:
            raise ValueError(f"确认入库前必须选择数据库内的标准宠物名：{', '.join(missing)}")
        assert player is not None
        assert opponent is not None
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
        self.index_store.rebuild_index()
        return event_id, sample_ids

    def list_catalog_names(self, limit: int = 2000) -> list[str]:
        return self.catalog.list_names(limit=limit)

    def _normalize_result(self, result: PetRecognitionResult) -> PetRecognitionResult:
        if not result.name:
            return result
        entry = self.catalog.normalize_candidate(result.name)
        if entry is None:
            return result
        return PetRecognitionResult(
            side=result.side,
            pet_id=entry.id,
            name=entry.name,
            confidence=result.confidence,
            top_candidates=result.top_candidates,
            source=result.source,
            crop_path=result.crop_path,
            crop=result.crop,
        )
