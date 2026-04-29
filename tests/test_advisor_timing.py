import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ailock.advisor import AdvisorService
from ailock.models import AdviceResult, AppSettings, BattleState, KnowledgeEntry
from ailock.pet_vision.types import DualPetRecognitionResult, PetCandidate, PetRecognitionResult


class FakeCaptureService:
    def __init__(self, screenshot_path: Path) -> None:
        self.screenshot_path = screenshot_path

    def capture_primary_screen(self) -> tuple[bytes, Path]:
        return b"fake-image", self.screenshot_path


class FakeClient:
    def describe_battle_state(self, image_bytes: bytes) -> BattleState:
        return BattleState(
            player_pet="player",
            opponent_pet="opponent",
            tactical_summary="summary",
            suggested_query_terms=["player", "opponent"],
            confidence_map={"player_pet": 0.9},
        )

    def generate_advice(
        self,
        battle_state: BattleState,
        knowledge_hits: list[KnowledgeEntry],
    ) -> AdviceResult:
        return AdviceResult(
            recommended_action="attack",
            reason="matched knowledge",
            confidence="high",
        )


class FailingClient(FakeClient):
    def generate_advice(
        self,
        battle_state: BattleState,
        knowledge_hits: list[KnowledgeEntry],
    ) -> AdviceResult:
        raise RuntimeError("advice failed")


class ExplodingClient(FakeClient):
    def describe_battle_state(self, image_bytes: bytes) -> BattleState:
        raise AssertionError("pet recognition flow should not call LLM battle-state recognition")

    def generate_advice(
        self,
        battle_state: BattleState,
        knowledge_hits: list[KnowledgeEntry],
    ) -> AdviceResult:
        raise AssertionError("pet recognition flow should not generate advice yet")


class FakePetVisionService:
    def recognize_screenshot(self, screenshot_path: Path) -> DualPetRecognitionResult:
        return DualPetRecognitionResult(
            player=PetRecognitionResult(
                side="player",
                pet_id=1,
                name="迪莫",
                confidence=0.9,
                top_candidates=[PetCandidate(1, "迪莫", 0.9)],
            ),
            opponent=PetRecognitionResult(
                side="opponent",
                pet_id=2,
                name="喵喵",
                confidence=0.8,
                top_candidates=[PetCandidate(2, "喵喵", 0.8)],
            ),
            screenshot_path=str(screenshot_path),
        )


class FakeKnowledgeStore:
    def search(self, query_text: str, limit: int = 5) -> list[KnowledgeEntry]:
        return [
            KnowledgeEntry(
                source_path="source.md",
                source_type="text",
                title="Counter note",
                content="Use attack.",
                keywords=["player"],
            )
        ]


class AdvisorTimingTests(unittest.TestCase):
    def test_capture_analysis_writes_step_timing_log(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            advisor = AdvisorService(
                settings=AppSettings(api_key="secret", max_knowledge_hits=3),
                capture_service=FakeCaptureService(root / "capture.png"),
                knowledge_store=FakeKnowledgeStore(),
                log_dir=root / "logs",
            )
            advisor.client = FakeClient()

            result = advisor.capture_and_advise()

            log_path = Path(result.timing_log_path)
            self.assertTrue(log_path.exists())
            records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            step_records = [record for record in records if record["event"] == "step"]
            self.assertEqual(
                [record["step"] for record in step_records],
                [
                    "capture_screenshot",
                    "recognize_battle_state",
                    "search_knowledge",
                    "generate_advice",
                    "finalize_result",
                ],
            )
            self.assertTrue(all(record["status"] == "ok" for record in step_records))
            self.assertTrue(all(isinstance(record["duration_ms"], float | int) for record in step_records))
            self.assertEqual(records[-1]["event"], "run_finish")
            self.assertEqual(records[-1]["status"], "ok")
            self.assertEqual(result.timing_events, records)

    def test_capture_analysis_logs_failed_step_before_reraising(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            advisor = AdvisorService(
                settings=AppSettings(api_key="secret"),
                capture_service=FakeCaptureService(root / "capture.png"),
                knowledge_store=FakeKnowledgeStore(),
                log_dir=root / "logs",
            )
            advisor.client = FailingClient()

            with self.assertRaisesRegex(RuntimeError, "advice failed"):
                advisor.capture_and_advise()

            [log_path] = (root / "logs").glob("analysis-*.jsonl")
            records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            failed_steps = [
                record
                for record in records
                if record["event"] == "step" and record["status"] == "error"
            ]
            self.assertEqual(failed_steps[0]["step"], "generate_advice")
            self.assertEqual(records[-1]["event"], "run_finish")
            self.assertEqual(records[-1]["status"], "error")

    def test_pet_recognition_flow_skips_llm_advice_generation(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            advisor = AdvisorService(
                settings=AppSettings(api_key="secret"),
                capture_service=FakeCaptureService(root / "capture.png"),
                knowledge_store=FakeKnowledgeStore(),
                log_dir=root / "logs",
                pet_vision_service=FakePetVisionService(),
            )
            advisor.client = ExplodingClient()

            result = advisor.capture_and_advise()

            self.assertEqual(result.battle_state.player_pet, "迪莫")
            self.assertEqual(result.battle_state.opponent_pet, "喵喵")
            self.assertEqual(result.knowledge_hits, [])
            self.assertEqual(result.advice.recommended_action, "暂不生成对战建议")
            step_names = [
                record["step"]
                for record in result.timing_events
                if record["event"] == "step"
            ]
            self.assertEqual(
                step_names,
                [
                    "capture_screenshot",
                    "pet_vision_recognition",
                    "build_battle_state_from_pet_recognition",
                    "skip_advice_until_pet_recognition_is_accurate",
                ],
            )


if __name__ == "__main__":
    unittest.main()
