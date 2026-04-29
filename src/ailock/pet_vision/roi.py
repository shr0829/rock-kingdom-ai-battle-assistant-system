from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtGui import QImage

from .types import PetCrop, PetCropSet


@dataclass(frozen=True, slots=True)
class RatioRoi:
    x_ratio: float
    y_ratio: float
    w_ratio: float
    h_ratio: float


class BattlePetCropper:
    DEFAULT_PLAYER_BODY_ROI = RatioRoi(0.17, 0.45, 0.36, 0.53)
    DEFAULT_OPPONENT_BODY_ROI = RatioRoi(0.55, 0.25, 0.32, 0.48)
    DEFAULT_PLAYER_AVATAR_ROI = RatioRoi(0.02, 0.08, 0.055, 0.11)
    DEFAULT_OPPONENT_AVATAR_ROI = RatioRoi(0.835, 0.08, 0.055, 0.11)
    DEFAULT_PLAYER_ROI = DEFAULT_PLAYER_BODY_ROI
    DEFAULT_OPPONENT_ROI = DEFAULT_OPPONENT_BODY_ROI

    def __init__(
        self,
        data_dir: Path,
        player_roi: RatioRoi | None = None,
        opponent_roi: RatioRoi | None = None,
        player_avatar_roi: RatioRoi | None = None,
        opponent_avatar_roi: RatioRoi | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.player_roi = player_roi or self.DEFAULT_PLAYER_BODY_ROI
        self.opponent_roi = opponent_roi or self.DEFAULT_OPPONENT_BODY_ROI
        self.player_avatar_roi = player_avatar_roi or self.DEFAULT_PLAYER_AVATAR_ROI
        self.opponent_avatar_roi = opponent_avatar_roi or self.DEFAULT_OPPONENT_AVATAR_ROI
        self.runtime_crop_dir = data_dir / "pet_vision" / "runtime_crops"

    def crop_both(self, screenshot_path: Path) -> dict[str, PetCrop]:
        crop_sets = self.crop_both_sets(screenshot_path)
        return {
            "player": crop_sets["player"].body,
            "opponent": crop_sets["opponent"].body,
        }

    def crop_both_sets(self, screenshot_path: Path) -> dict[str, PetCropSet]:
        image = QImage(str(screenshot_path))
        if image.isNull():
            raise ValueError(f"无法读取截图：{screenshot_path}")
        return {
            "player": PetCropSet(
                side="player",
                avatar=self._crop_one("player", "avatar", image, screenshot_path, self.player_avatar_roi),
                body=self._crop_one("player", "body", image, screenshot_path, self.player_roi),
            ),
            "opponent": PetCropSet(
                side="opponent",
                avatar=self._crop_one("opponent", "avatar", image, screenshot_path, self.opponent_avatar_roi),
                body=self._crop_one("opponent", "body", image, screenshot_path, self.opponent_roi),
            ),
        }

    def _crop_one(self, side: str, crop_kind: str, image: QImage, screenshot_path: Path, roi: RatioRoi) -> PetCrop:
        rect = self._ratio_to_rect(image.width(), image.height(), roi)
        cropped = image.copy(rect["x"], rect["y"], rect["width"], rect["height"])
        if cropped.isNull():
            raise ValueError(f"{side} {crop_kind} 宠物 ROI 裁剪失败：{rect}")
        output_dir = self.runtime_crop_dir / crop_kind / side
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        output_path = output_dir / f"{side}-{crop_kind}-{timestamp}.png"
        if not cropped.save(str(output_path), "PNG"):
            raise ValueError(f"{side} {crop_kind} 宠物 crop 写入失败：{output_path}")
        return PetCrop(
            side=side,
            image_bytes=output_path.read_bytes(),
            path=str(output_path),
            roi=rect,
            source_screenshot_path=str(screenshot_path),
            crop_kind=crop_kind,
        )

    @staticmethod
    def _ratio_to_rect(width: int, height: int, roi: RatioRoi) -> dict[str, int]:
        x = max(0, min(width - 1, round(width * roi.x_ratio)))
        y = max(0, min(height - 1, round(height * roi.y_ratio)))
        crop_w = max(1, min(width - x, round(width * roi.w_ratio)))
        crop_h = max(1, min(height - y, round(height * roi.h_ratio)))
        return {"x": x, "y": y, "width": crop_w, "height": crop_h}
