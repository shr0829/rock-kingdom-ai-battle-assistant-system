import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ailock.advisor import AdvisorService
from ailock.models import AdviceResult, AppSettings, BattleState, KnowledgeEntry


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


if __name__ == "__main__":
    unittest.main()
