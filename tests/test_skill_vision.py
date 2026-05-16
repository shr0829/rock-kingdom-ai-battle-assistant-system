import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from ailock.skill_vision import SkillUseTextDetector


def write_png(path: Path, image: np.ndarray) -> None:
    encoded, buffer = cv2.imencode(".png", image)
    assert encoded
    buffer.tofile(str(path))


def synthetic_battle_image(width: int = 1000, height: int = 600, *, side: str = "right") -> tuple[np.ndarray, dict[str, int]]:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :] = (90, 130, 90)
    cv2.rectangle(image, (0, 0), (width, round(height * 0.09)), (40, 80, 120), -1)
    banner_width = round(width * 0.28)
    banner_height = round(height * 0.05)
    x = 0 if side == "left" else width - banner_width
    y = round(height * 0.17)
    cv2.rectangle(image, (x, y), (x + banner_width, y + banner_height), (39, 39, 39), -1)
    cv2.putText(
        image,
        "Pet used *0 Skill!",
        (x + 28, y + round(banner_height * 0.68)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.68,
        (245, 245, 245),
        2,
        cv2.LINE_AA,
    )
    return image, {"x": x, "y": y, "width": banner_width, "height": banner_height}


class SkillVisionTests(unittest.TestCase):
    def test_detector_finds_right_aligned_skill_use_banner_and_text_crop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            screenshot = root / "capture.png"
            image, expected = synthetic_battle_image(side="right")
            write_png(screenshot, image)

            detection = SkillUseTextDetector(root / "data").detect_screenshot(screenshot)

            self.assertTrue(detection.found)
            self.assertEqual(detection.side, "right")
            self.assertGreaterEqual(detection.confidence, 0.75)
            self.assertIsNotNone(detection.banner_crop)
            self.assertIsNotNone(detection.text_crop)
            banner_roi = detection.banner_crop.roi  # type: ignore[union-attr]
            self.assertLessEqual(abs(banner_roi["y"] - expected["y"]), 3)
            self.assertGreaterEqual(banner_roi["width"], expected["width"] - 4)
            self.assertTrue(Path(detection.banner_crop.path).exists())  # type: ignore[union-attr]
            self.assertTrue(Path(detection.text_crop.path).exists())  # type: ignore[union-attr]

    def test_detector_supports_left_aligned_skill_use_banner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            screenshot = root / "capture.png"
            image, _ = synthetic_battle_image(side="left")
            write_png(screenshot, image)

            detection = SkillUseTextDetector(root / "data").detect_screenshot(screenshot)

            self.assertTrue(detection.found)
            self.assertEqual(detection.side, "left")
            self.assertEqual(detection.banner_crop.roi["x"], 0)  # type: ignore[union-attr]

    def test_detector_returns_not_found_without_skill_use_banner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            screenshot = root / "capture.png"
            image = np.zeros((600, 1000, 3), dtype=np.uint8)
            image[:, :] = (90, 130, 90)
            write_png(screenshot, image)

            detection = SkillUseTextDetector(root / "data").detect_screenshot(screenshot)

            self.assertFalse(detection.found)
            self.assertIsNone(detection.banner_crop)
            self.assertIsNone(detection.text_crop)


if __name__ == "__main__":
    unittest.main()
