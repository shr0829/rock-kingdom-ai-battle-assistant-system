from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtGui import QImage

from .types import PetCrop


@dataclass(frozen=True, slots=True)
class RatioRoi:
    x_ratio: float
    y_ratio: float
    w_ratio: float
    h_ratio: float


class BattlePetCropper:
    DEFAULT_PLAYER_ROI = RatioRoi(0.10, 0.35, 0.35, 0.45)
    DEFAULT_OPPONENT_ROI = RatioRoi(0.45, 0.10, 0.40, 0.45)

    def __init__(
        self,
        data_dir: Path,
        player_roi: RatioRoi | None = None,
        opponent_roi: RatioRoi | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.player_roi = player_roi or self.DEFAULT_PLAYER_ROI
        self.opponent_roi = opponent_roi or self.DEFAULT_OPPONENT_ROI
        self.player_crop_dir = data_dir / "pet_vision" / "runtime_crops" / "player"
        self.opponent_crop_dir = data_dir / "pet_vision" / "runtime_crops" / "opponent"

    def crop_both(self, screenshot_path: Path) -> dict[str, PetCrop]:
        image = QImage(str(screenshot_path))
        if image.isNull():
            raise ValueError(f"无法读取截图：{screenshot_path}")
        return {
            "player": self._crop_one("player", image, screenshot_path, self.player_roi),
            "opponent": self._crop_one("opponent", image, screenshot_path, self.opponent_roi),
        }

    def _crop_one(self, side: str, image: QImage, screenshot_path: Path, roi: RatioRoi) -> PetCrop:
        rect = self._ratio_to_rect(image.width(), image.height(), roi)
        cropped = image.copy(rect["x"], rect["y"], rect["width"], rect["height"])
        if cropped.isNull():
            raise ValueError(f"{side} 宠物 ROI 裁剪失败：{rect}")
        output_dir = self.player_crop_dir if side == "player" else self.opponent_crop_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        output_path = output_dir / f"{side}-{timestamp}.png"
        if not cropped.save(str(output_path), "PNG"):
            raise ValueError(f"{side} 宠物 crop 写入失败：{output_path}")
        return PetCrop(
            side=side,
            image_bytes=output_path.read_bytes(),
            path=str(output_path),
            roi=rect,
            source_screenshot_path=str(screenshot_path),
        )

    @staticmethod
    def _ratio_to_rect(width: int, height: int, roi: RatioRoi) -> dict[str, int]:
        x = max(0, min(width - 1, round(width * roi.x_ratio)))
        y = max(0, min(height - 1, round(height * roi.y_ratio)))
        crop_w = max(1, min(width - x, round(width * roi.w_ratio)))
        crop_h = max(1, min(height - y, round(height * roi.h_ratio)))
        return {"x": x, "y": y, "width": crop_w, "height": crop_h}
