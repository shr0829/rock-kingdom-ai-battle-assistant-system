import sqlite3
import tempfile
import unittest
from pathlib import Path

from ailock.advisor import AdvisorService
from ailock.models import BattleState
from PySide6.QtGui import QColor, QImage

from ailock.pet_vision import (
    BattlePetCropper,
    PetCatalogStore,
    PetRecognitionSampleStore,
    PetVisionIndexStore,
    PetVisionRecognizer,
    PetVisionService,
)
from ailock.pet_vision.types import DualPetRecognitionResult, PetCandidate, PetRecognitionResult


def write_image(path: Path, color: QColor, width: int = 120, height: int = 80) -> None:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(color)
    assert image.save(str(path), "PNG")


class PetVisionTests(unittest.TestCase):
    def test_advisor_applies_local_pet_recognition_to_battle_state(self) -> None:
        result = DualPetRecognitionResult(
            player=PetRecognitionResult(
                side="player",
                pet_id=1,
                name="迪莫",
                confidence=0.91,
                top_candidates=[PetCandidate(1, "迪莫", 0.91)],
            ),
            opponent=PetRecognitionResult(
                side="opponent",
                pet_id=2,
                name="喵喵",
                confidence=0.44,
                top_candidates=[PetCandidate(2, "喵喵", 0.44)],
            ),
        )

        battle_state = AdvisorService._apply_pet_recognition(
            BattleState(player_pet="LLM我方", opponent_pet="LLM对方"),
            result,
        )

        self.assertEqual(battle_state.player_pet, "迪莫")
        self.assertEqual(battle_state.opponent_pet, "喵喵")
        self.assertEqual(battle_state.confidence_map["player_pet"], 0.91)
        self.assertIn("对方宠物需确认", battle_state.unknowns)

    def test_catalog_matches_standard_name_and_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PetCatalogStore(Path(temp_dir) / "knowledge.db")
            pet_id = store.upsert(name="迪莫", aliases=["圣光迪莫"], primary_attribute="光")

            self.assertEqual(store.find_by_name("迪莫").id, pet_id)  # type: ignore[union-attr]
            self.assertEqual(store.find_by_name("圣光迪莫").name, "迪莫")  # type: ignore[union-attr]
            self.assertEqual(store.search("圣光")[0].name, "迪莫")

    def test_cropper_writes_player_and_opponent_crops(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            screenshot = root / "capture.png"
            write_image(screenshot, QColor("red"), width=200, height=100)
            cropper = BattlePetCropper(root)

            crops = cropper.crop_both(screenshot)

            self.assertEqual(set(crops), {"player", "opponent"})
            self.assertTrue(Path(crops["player"].path).exists())
            self.assertGreater(len(crops["opponent"].image_bytes), 0)
            self.assertEqual(crops["player"].roi["width"], 70)
            self.assertEqual(crops["opponent"].roi["height"], 45)

    def test_index_recognizer_returns_ranked_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database_path = root / "knowledge.db"
            catalog = PetCatalogStore(database_path)
            pet_id = catalog.upsert(name="火花")
            samples = PetRecognitionSampleStore(database_path)
            artwork_path = root / "data" / "pet_vision" / "artworks" / "火花.png"
            artwork_path.parent.mkdir(parents=True)
            write_image(artwork_path, QColor("red"))
            samples.upsert_artwork(
                pet_id=pet_id,
                name="火花",
                source_url="https://example.invalid/fire.png",
                local_path=str(artwork_path),
                image_bytes=artwork_path.read_bytes(),
            )
            index = PetVisionIndexStore(root / "data", samples)
            index.rebuild_index()
            cropper = BattlePetCropper(root / "data")
            screenshot = root / "capture.png"
            write_image(screenshot, QColor("red"), width=200, height=100)
            crop = cropper.crop_both(screenshot)["player"]

            result = PetVisionRecognizer(index).recognize(crop)

            self.assertEqual(result.name, "火花")
            self.assertEqual(result.pet_id, pet_id)
            self.assertGreaterEqual(result.confidence, 0.99)

    def test_confirmation_saves_two_blob_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service = PetVisionService(data_dir=root / "data", database_path=root / "data" / "knowledge.db")
            pet_a = service.catalog.upsert(name="迪莫")
            pet_b = service.catalog.upsert(name="喵喵")
            artwork = root / "data" / "pet_vision" / "artworks" / "迪莫.png"
            artwork.parent.mkdir(parents=True, exist_ok=True)
            write_image(artwork, QColor("blue"))
            service.samples.upsert_artwork(
                pet_id=pet_a,
                name="迪莫",
                source_url="https://example.invalid/dimo.png",
                local_path=str(artwork),
                image_bytes=artwork.read_bytes(),
            )
            service.index_store.rebuild_index()
            screenshot = root / "capture.png"
            write_image(screenshot, QColor("blue"), width=200, height=100)
            result = service.recognize_screenshot(screenshot)

            event_id, sample_ids = service.save_confirmation(
                result,
                player_name="迪莫",
                opponent_name="喵喵",
            )

            conn = sqlite3.connect(root / "data" / "knowledge.db")
            rows = conn.execute("SELECT side, length(crop_png), roi_json FROM pet_recognition_samples ORDER BY id").fetchall()
            conn.close()
            self.assertEqual(event_id, 1)
            self.assertEqual(len(sample_ids), 2)
            self.assertEqual([row[0] for row in rows], ["player", "opponent"])
            self.assertTrue(all(row[1] > 0 for row in rows))
            self.assertTrue(all("width" in row[2] for row in rows))


if __name__ == "__main__":
    unittest.main()
