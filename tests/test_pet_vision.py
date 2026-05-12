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
from ailock.pet_vision.features import ImageFeatureExtractor, cosine_similarity
from ailock.pet_vision.types import DualPetRecognitionResult, PetCandidate, PetRecognitionResult


def write_image(path: Path, color: QColor, width: int = 120, height: int = 80) -> None:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(color)
    assert image.save(str(path), "PNG")


def transparent_subject_image(width: int, height: int, color: QColor) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGBA8888)
    image.fill(QColor(0, 0, 0, 0))
    margin_x = width // 4
    margin_y = height // 4
    for y in range(margin_y, height - margin_y):
        for x in range(margin_x, width - margin_x):
            image.setPixelColor(x, y, color)
    return image


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

    def test_catalog_prefers_exact_name_over_earlier_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PetCatalogStore(Path(temp_dir) / "knowledge.db")
            store.upsert(name="海豹战士", aliases=["海豹船长"])
            exact_id = store.upsert(name="海豹船长")

            self.assertEqual(store.find_by_name("海豹船长").id, exact_id)  # type: ignore[union-attr]

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
            self.assertEqual(crops["player"].roi["width"], 72)
            self.assertEqual(crops["opponent"].roi["height"], 48)

    def test_cropper_writes_avatar_and_body_crops_for_each_side(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            screenshot = root / "capture.png"
            write_image(screenshot, QColor("red"), width=200, height=100)
            cropper = BattlePetCropper(root)

            crop_sets = cropper.crop_both_sets(screenshot)

            self.assertEqual(set(crop_sets), {"player", "opponent"})
            self.assertEqual(crop_sets["player"].avatar.crop_kind, "avatar")
            self.assertEqual(crop_sets["player"].body.crop_kind, "body")
            self.assertTrue(Path(crop_sets["opponent"].avatar.path).exists())
            self.assertTrue(Path(crop_sets["opponent"].body.path).exists())
            self.assertLess(crop_sets["player"].avatar.roi["width"], crop_sets["player"].body.roi["width"])

    def test_default_avatar_rois_match_reference_capture_proportions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            screenshot = root / "capture.png"
            write_image(screenshot, QColor("black"), width=1680, height=1050)
            cropper = BattlePetCropper(root)

            crop_sets = cropper.crop_both_sets(screenshot)

            self.assertEqual(
                crop_sets["player"].avatar.roi,
                {"x": 35, "y": 36, "width": 62, "height": 62},
            )
            self.assertEqual(
                crop_sets["opponent"].avatar.roi,
                {"x": 1405, "y": 39, "width": 62, "height": 62},
            )

    def test_default_rois_match_windowed_battle_layout_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            screenshot = root / "capture.png"
            write_image(screenshot, QColor("black"), width=2048, height=950)
            cropper = BattlePetCropper(root)

            crop_sets = cropper.crop_both_sets(screenshot)

            self.assertEqual(
                crop_sets["player"].avatar.roi,
                {"x": 43, "y": 33, "width": 76, "height": 56},
            )
            self.assertEqual(
                crop_sets["opponent"].avatar.roi,
                {"x": 1713, "y": 35, "width": 76, "height": 56},
            )
            self.assertEqual(
                crop_sets["player"].body.roi,
                {"x": 348, "y": 428, "width": 737, "height": 504},
            )
            self.assertEqual(
                crop_sets["opponent"].body.roi,
                {"x": 1126, "y": 238, "width": 655, "height": 456},
            )

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

    def test_feature_extractor_ignores_transparent_padding(self) -> None:
        extractor = ImageFeatureExtractor()
        padded = transparent_subject_image(100, 100, QColor("red"))
        cropped = transparent_subject_image(50, 50, QColor("red"))

        score = cosine_similarity(
            extractor.extract_from_image(padded),
            extractor.extract_from_image(cropped),
        )

        self.assertGreater(score, 0.98)

    def test_feature_extractor_falls_back_when_onnx_model_is_missing(self) -> None:
        extractor = ImageFeatureExtractor(model_path=Path("missing-model.onnx"))

        self.assertEqual(extractor.feature_version, 2)
        self.assertEqual(extractor.backend_name, "handcrafted-reference-v2")

    def test_feature_extractor_does_not_use_classifier_logits_as_default_embedding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            model = Path(temp_dir) / "mobilenetv2-12.onnx"
            model.write_bytes(b"0" * 2048)

            extractor = ImageFeatureExtractor(model_path=model)

            self.assertEqual(extractor.feature_version, 2)
            self.assertEqual(extractor.backend_name, "handcrafted-reference-v2")

    def test_artwork_reference_name_uses_visible_artwork_name_before_catalog_chain_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database_path = root / "knowledge.db"
            catalog = PetCatalogStore(database_path)
            catalog.upsert(name="果冻")
            final_id = catalog.upsert(name="抹茶布丁", aliases=["果冻进化链"])
            samples = PetRecognitionSampleStore(database_path)
            artwork_path = root / "data" / "pet_vision" / "artworks" / "果冻进化链-54.png"
            artwork_path.parent.mkdir(parents=True)
            write_image(artwork_path, QColor("green"))
            samples.upsert_artwork(
                pet_id=final_id,
                name="果冻进化链",
                source_url="https://example.invalid/jelly.png",
                local_path=str(artwork_path),
                image_bytes=artwork_path.read_bytes(),
            )

            features = PetVisionIndexStore(root / "data", samples).rebuild_index()

            self.assertEqual(len(features), 1)
            self.assertEqual(features[0].name, "果冻")
            self.assertIsNone(features[0].pet_id)
            self.assertEqual(features[0].source_kind, "artwork_reference")

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
            rows = conn.execute(
                """
                SELECT
                    side,
                    length(crop_png),
                    roi_json,
                    length(avatar_crop_png),
                    length(body_crop_png),
                    avatar_roi_json,
                    body_roi_json
                FROM pet_recognition_samples
                ORDER BY id
                """
            ).fetchall()
            event_row = conn.execute(
                """
                SELECT
                    player_confirmed_pet_id,
                    opponent_confirmed_pet_id,
                    player_confirmed_name,
                    opponent_confirmed_name
                FROM pet_recognition_events
                WHERE id = ?
                """,
                (event_id,),
            ).fetchone()
            conn.close()
            self.assertEqual(event_id, 1)
            self.assertEqual(len(sample_ids), 2)
            self.assertEqual(event_row[0], pet_a)
            self.assertEqual(event_row[1], pet_b)
            self.assertEqual(event_row[2], "迪莫")
            self.assertEqual(event_row[3], "喵喵")
            self.assertEqual([row[0] for row in rows], ["player", "opponent"])
            self.assertTrue(all(row[1] > 0 for row in rows))
            self.assertTrue(all("width" in row[2] for row in rows))
            self.assertTrue(all(row[3] > 0 for row in rows))
            self.assertTrue(all(row[4] > 0 for row in rows))
            self.assertTrue(all("width" in row[5] for row in rows))
            self.assertTrue(all("width" in row[6] for row in rows))
            self.assertEqual(len(service.avatar_index_store.ensure_index()), 2)
            self.assertGreaterEqual(len(service.body_index_store.ensure_index()), 3)

    def test_avatar_channel_uses_artwork_reference_until_confirmed_avatar_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service = PetVisionService(data_dir=root / "data", database_path=root / "data" / "knowledge.db")
            pet_id = service.catalog.upsert(name="迪莫")
            artwork = root / "data" / "pet_vision" / "artworks" / "迪莫.png"
            artwork.parent.mkdir(parents=True, exist_ok=True)
            write_image(artwork, QColor("green"))
            service.samples.upsert_artwork(
                pet_id=pet_id,
                name="迪莫",
                source_url="https://example.invalid/dimo-green.png",
                local_path=str(artwork),
                image_bytes=artwork.read_bytes(),
            )
            service.body_index_store.rebuild_index()
            screenshot = root / "capture.png"
            write_image(screenshot, QColor("green"), width=200, height=100)

            result = service.recognize_screenshot(screenshot)

            self.assertEqual(result.player.name, "迪莫")
            self.assertEqual(result.player.score_breakdown["body_weight"], 1.0)
            self.assertEqual(result.player.score_breakdown["avatar_weight"], 0.15)
            self.assertEqual(result.player.score_breakdown["body_index"]["source_counts"]["artwork_reference"], 1)
            self.assertEqual(result.player.score_breakdown["avatar_index"]["source_counts"]["artwork_reference"], 1)
            self.assertEqual(result.player.avatar_candidates[0].name, "迪莫")

    def test_avatar_index_switches_to_confirmed_avatar_samples_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service = PetVisionService(data_dir=root / "data", database_path=root / "data" / "knowledge.db")
            pet_id = service.catalog.upsert(name="迪莫")
            artwork = root / "data" / "pet_vision" / "artworks" / "迪莫.png"
            artwork.parent.mkdir(parents=True, exist_ok=True)
            write_image(artwork, QColor("green"))
            service.samples.upsert_artwork(
                pet_id=pet_id,
                name="迪莫",
                source_url="https://example.invalid/dimo-green.png",
                local_path=str(artwork),
                image_bytes=artwork.read_bytes(),
            )
            screenshot = root / "capture.png"
            write_image(screenshot, QColor("green"), width=200, height=100)
            result = service.recognize_screenshot(screenshot)

            service.save_confirmation(result, player_name="迪莫", opponent_name="迪莫")

            avatar_features = service.avatar_index_store.ensure_index()
            self.assertEqual(len(avatar_features), 2)
            self.assertEqual({item.source_kind for item in avatar_features}, {"confirmed_avatar"})

    def test_fusion_adds_agreement_bonus_and_preserves_conflicting_channels(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service = PetVisionService(data_dir=root / "data", database_path=root / "data" / "knowledge.db")

            agreed, _ = service._fuse_candidates(
                [PetCandidate(1, "迪莫", 0.9, channel="body")],
                [PetCandidate(1, "迪莫", 0.8, channel="avatar:confirmed_avatar")],
            )
            conflicted, _ = service._fuse_candidates(
                [PetCandidate(1, "迪莫", 0.9, channel="body")],
                [PetCandidate(2, "喵喵", 0.8, channel="avatar:confirmed_avatar")],
            )

            self.assertEqual(agreed[0].name, "迪莫")
            self.assertAlmostEqual(agreed[0].confidence, 0.885)
            self.assertEqual(conflicted[0].name, "喵喵")
            self.assertEqual({candidate.channel for candidate in conflicted}, {"body", "avatar"})

    def test_confirmation_accepts_user_typed_pet_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service = PetVisionService(data_dir=root / "data", database_path=root / "data" / "knowledge.db")
            pet_a = service.catalog.upsert(name="迪莫")
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

            service.save_confirmation(
                result,
                player_name="玩家手输新宠",
                opponent_name="喵喵",
            )

            self.assertEqual(service.catalog.find_by_name("玩家手输新宠").source, "user_confirmation")  # type: ignore[union-attr]
            self.assertIsNotNone(service.catalog.find_by_name("喵喵"))

    def test_sample_store_migrates_event_confirmation_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "knowledge.db"
            conn = sqlite3.connect(database_path)
            conn.execute(
                """
                CREATE TABLE pet_recognition_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    screenshot_path TEXT,
                    player_pet_id INTEGER,
                    opponent_pet_id INTEGER,
                    player_confidence REAL,
                    opponent_confidence REAL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()
            conn.close()

            PetRecognitionSampleStore(database_path)

            conn = sqlite3.connect(database_path)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(pet_recognition_events)")}
            conn.close()
            self.assertIn("player_confirmed_pet_id", columns)
            self.assertIn("opponent_confirmed_name", columns)


if __name__ == "__main__":
    unittest.main()
