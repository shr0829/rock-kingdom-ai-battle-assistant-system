from __future__ import annotations

from pathlib import Path

from .capture import ScreenCaptureService
from .knowledge import KnowledgeStore
from .llm_client import MultimodalClient
from .models import AnalysisResult, AppSettings, BattleState
from .pet_vision import PetVisionService
from .pet_vision.types import DualPetRecognitionResult
from .timing_log import AnalysisTimingLog


class AdvisorService:
    def __init__(
        self,
        settings: AppSettings,
        capture_service: ScreenCaptureService,
        knowledge_store: KnowledgeStore,
        log_dir: Path | None = None,
        pet_vision_service: PetVisionService | None = None,
    ) -> None:
        self.settings = settings
        self.capture_service = capture_service
        self.knowledge_store = knowledge_store
        self.log_dir = log_dir
        self.pet_vision_service = pet_vision_service
        self.client = MultimodalClient(settings)

    def refresh_settings(self, settings: AppSettings) -> None:
        self.settings = settings
        self.capture_service.refresh_settings(settings)
        self.client = MultimodalClient(settings)

    def capture_and_advise(self) -> AnalysisResult:
        timing_log = self._new_timing_log()
        try:
            with timing_log.step("capture_screenshot"):
                image_bytes, screenshot_path = self.capture_service.capture_primary_screen()
            timing_log.write_event(
                "artifact",
                artifact="screenshot",
                path=str(screenshot_path),
                bytes=len(image_bytes),
            )

            pet_recognition: DualPetRecognitionResult | None = None
            if self.pet_vision_service is not None:
                with timing_log.step("pet_vision_recognition"):
                    pet_recognition = self.pet_vision_service.recognize_screenshot(screenshot_path)
                timing_log.write_event(
                    "artifact",
                    artifact="pet_recognition",
                    result=pet_recognition.to_dict(),
                )

            with timing_log.step("recognize_battle_state", image_bytes=len(image_bytes)):
                battle_state = self.client.describe_battle_state(image_bytes)
            if pet_recognition is not None:
                battle_state = self._apply_pet_recognition(battle_state, pet_recognition)
            timing_log.write_event(
                "artifact",
                artifact="battle_state",
                query=battle_state.to_query(),
                unknown_count=len(battle_state.unknowns),
                confidence_map=battle_state.confidence_map,
            )

            query_text = battle_state.to_query()
            with timing_log.step(
                "search_knowledge",
                query=query_text,
                limit=self.settings.max_knowledge_hits,
            ):
                knowledge_hits = self.knowledge_store.search(
                    query_text,
                    limit=self.settings.max_knowledge_hits,
                )
            timing_log.write_event(
                "artifact",
                artifact="knowledge_hits",
                count=len(knowledge_hits),
                titles=[entry.title for entry in knowledge_hits],
            )

            with timing_log.step("generate_advice", knowledge_hit_count=len(knowledge_hits)):
                advice = self.client.generate_advice(battle_state, knowledge_hits)

            with timing_log.step("finalize_result"):
                timing_log.write_event(
                    "artifact",
                    artifact="final_result",
                    recommended_action=advice.recommended_action,
                    confidence=advice.confidence,
                )
            timing_log.finish("ok", screenshot_path=str(screenshot_path))
            return AnalysisResult(
                battle_state=battle_state,
                advice=advice,
                knowledge_hits=knowledge_hits,
                pet_recognition=pet_recognition,
                screenshot_path=str(screenshot_path),
                timing_log_path=str(timing_log.path),
                timing_events=timing_log.events,
            )
        except Exception as exc:
            timing_log.finish("error", error_type=type(exc).__name__, error=str(exc))
            raise

    def save_pet_confirmation(
        self,
        result: AnalysisResult,
        *,
        player_name: str,
        opponent_name: str,
    ) -> tuple[int, list[int]]:
        if self.pet_vision_service is None or result.pet_recognition is None:
            raise RuntimeError("当前分析结果没有可保存的本地宠物识别样本。")
        return self.pet_vision_service.save_confirmation(
            result.pet_recognition,
            player_name=player_name,
            opponent_name=opponent_name,
        )

    def list_pet_catalog_names(self, limit: int = 2000) -> list[str]:
        if self.pet_vision_service is None:
            return []
        return self.pet_vision_service.list_catalog_names(limit=limit)

    @staticmethod
    def _apply_pet_recognition(
        battle_state: BattleState,
        pet_recognition: DualPetRecognitionResult,
    ) -> BattleState:
        confidence_map = dict(battle_state.confidence_map)
        unknowns = list(battle_state.unknowns)
        player_name = pet_recognition.player.name
        opponent_name = pet_recognition.opponent.name
        confidence_map["player_pet"] = pet_recognition.player.confidence
        confidence_map["opponent_pet"] = pet_recognition.opponent.confidence
        if not player_name or pet_recognition.player.confidence < PetVisionService.LOW_CONFIDENCE_THRESHOLD:
            player_unknown = "我方宠物需确认"
            if player_unknown not in unknowns:
                unknowns.append(player_unknown)
        if not opponent_name or pet_recognition.opponent.confidence < PetVisionService.LOW_CONFIDENCE_THRESHOLD:
            opponent_unknown = "对方宠物需确认"
            if opponent_unknown not in unknowns:
                unknowns.append(opponent_unknown)
        return BattleState(
            player_pet=player_name,
            opponent_pet=opponent_name,
            player_hp_state=battle_state.player_hp_state,
            visible_moves=battle_state.visible_moves,
            status_effects=battle_state.status_effects,
            field_notes=battle_state.field_notes,
            tactical_summary=battle_state.tactical_summary,
            suggested_query_terms=battle_state.suggested_query_terms,
            unknowns=unknowns,
            confidence_map=confidence_map,
        )

    def import_knowledge_folder(self, folder_path: Path) -> int:
        return self.knowledge_store.ingest_folder(folder_path, self.client)

    def _new_timing_log(self) -> AnalysisTimingLog:
        log_dir = self.log_dir or Path("data") / "logs"
        return AnalysisTimingLog(log_dir)
