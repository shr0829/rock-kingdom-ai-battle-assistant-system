from __future__ import annotations

from pathlib import Path

from .capture import ScreenCaptureService
from .knowledge import KnowledgeStore
from .llm_client import MultimodalClient
from .models import AnalysisResult, AppSettings


class AdvisorService:
    def __init__(
        self,
        settings: AppSettings,
        capture_service: ScreenCaptureService,
        knowledge_store: KnowledgeStore,
    ) -> None:
        self.settings = settings
        self.capture_service = capture_service
        self.knowledge_store = knowledge_store
        self.client = MultimodalClient(settings)

    def refresh_settings(self, settings: AppSettings) -> None:
        self.settings = settings
        self.client = MultimodalClient(settings)

    def capture_and_advise(self) -> AnalysisResult:
        image_bytes, screenshot_path = self.capture_service.capture_primary_screen()
        battle_state = self.client.describe_battle_state(image_bytes)
        knowledge_hits = self.knowledge_store.search(
            battle_state.to_query(),
            limit=self.settings.max_knowledge_hits,
        )
        advice = self.client.generate_advice(battle_state, knowledge_hits)
        return AnalysisResult(
            battle_state=battle_state,
            advice=advice,
            knowledge_hits=knowledge_hits,
            screenshot_path=str(screenshot_path),
        )

    def import_knowledge_folder(self, folder_path: Path) -> int:
        return self.knowledge_store.ingest_folder(folder_path, self.client)
