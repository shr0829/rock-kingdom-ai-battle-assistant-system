from __future__ import annotations

from pathlib import Path

from .capture import ScreenCaptureService
from .knowledge import KnowledgeStore
from .llm_client import MultimodalClient
from .models import AnalysisResult, AppSettings
from .timing_log import AnalysisTimingLog


class AdvisorService:
    def __init__(
        self,
        settings: AppSettings,
        capture_service: ScreenCaptureService,
        knowledge_store: KnowledgeStore,
        log_dir: Path | None = None,
    ) -> None:
        self.settings = settings
        self.capture_service = capture_service
        self.knowledge_store = knowledge_store
        self.log_dir = log_dir
        self.client = MultimodalClient(settings)

    def refresh_settings(self, settings: AppSettings) -> None:
        self.settings = settings
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

            with timing_log.step("recognize_battle_state", image_bytes=len(image_bytes)):
                battle_state = self.client.describe_battle_state(image_bytes)
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
                screenshot_path=str(screenshot_path),
                timing_log_path=str(timing_log.path),
                timing_events=timing_log.events,
            )
        except Exception as exc:
            timing_log.finish("error", error_type=type(exc).__name__, error=str(exc))
            raise

    def import_knowledge_folder(self, folder_path: Path) -> int:
        return self.knowledge_store.ingest_folder(folder_path, self.client)

    def _new_timing_log(self) -> AnalysisTimingLog:
        log_dir = self.log_dir or Path("data") / "logs"
        return AnalysisTimingLog(log_dir)
