from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True, slots=True)
class SkillUseTextCrop:
    image_bytes: bytes
    path: str
    roi: dict[str, int]
    source_screenshot_path: str
    crop_kind: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "bytes": len(self.image_bytes),
            "path": self.path,
            "roi": self.roi,
            "source_screenshot_path": self.source_screenshot_path,
            "crop_kind": self.crop_kind,
        }


@dataclass(frozen=True, slots=True)
class SkillUseTextDetection:
    found: bool
    confidence: float
    side: str = ""
    banner_crop: SkillUseTextCrop | None = None
    text_crop: SkillUseTextCrop | None = None
    candidates: list[dict[str, Any]] | None = None
    source: str = "opencv_skill_use_text"

    def to_dict(self) -> dict[str, Any]:
        return {
            "found": self.found,
            "confidence": self.confidence,
            "side": self.side,
            "banner_crop": self.banner_crop.to_dict() if self.banner_crop else None,
            "text_crop": self.text_crop.to_dict() if self.text_crop else None,
            "candidates": self.candidates or [],
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class _BannerCandidate:
    x: int
    y: int
    width: int
    height: int
    confidence: float
    fill_density: float
    text_pixel_count: int

    @property
    def roi(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.roi,
            "confidence": self.confidence,
            "fill_density": self.fill_density,
            "text_pixel_count": self.text_pixel_count,
        }


class SkillUseTextDetector:
    # Reference screenshots place the announcement in the upper battle field, but
    # either left- or right-aligned. Search vertically and let OpenCV locate the
    # black banner so later resolution/aspect changes do not need fixed pixels.
    SEARCH_TOP_RATIO = 0.10
    SEARCH_BOTTOM_RATIO = 0.36
    MIN_BANNER_WIDTH_RATIO = 0.18
    MIN_BANNER_HEIGHT_RATIO = 0.025
    MAX_BANNER_HEIGHT_RATIO = 0.09
    MIN_ASPECT_RATIO = 4.0
    MIN_CONFIDENCE = 0.35

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.runtime_crop_dir = data_dir / "skill_vision" / "runtime_crops"

    def detect_screenshot(self, screenshot_path: Path) -> SkillUseTextDetection:
        image = self._read_image(screenshot_path)
        candidates = self._find_banner_candidates(image)
        if not candidates or candidates[0].confidence < self.MIN_CONFIDENCE:
            return SkillUseTextDetection(
                found=False,
                confidence=0.0,
                candidates=[candidate.to_dict() for candidate in candidates[:5]],
            )

        banner = candidates[0]
        banner_crop = self._write_crop(
            image,
            screenshot_path=screenshot_path,
            roi=banner.roi,
            crop_kind="skill_use_banner",
        )
        text_roi = self._find_text_roi(image, banner)
        text_crop = self._write_crop(
            image,
            screenshot_path=screenshot_path,
            roi=text_roi,
            crop_kind="skill_use_text",
        )
        side = self._side_for_banner(image.shape[1], banner)

        return SkillUseTextDetection(
            found=True,
            confidence=banner.confidence,
            side=side,
            banner_crop=banner_crop,
            text_crop=text_crop,
            candidates=[candidate.to_dict() for candidate in candidates[:5]],
        )

    def _find_banner_candidates(self, image: np.ndarray) -> list[_BannerCandidate]:
        height, width = image.shape[:2]
        search_top = round(height * self.SEARCH_TOP_RATIO)
        search_bottom = round(height * self.SEARCH_BOTTOM_RATIO)
        search = image[search_top:search_bottom]
        hsv = cv2.cvtColor(search, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(search, cv2.COLOR_BGR2GRAY)

        dark_neutral_mask = ((gray >= 18) & (gray <= 95) & (hsv[:, :, 1] <= 80)).astype(np.uint8) * 255
        close_kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (max(25, width // 45), max(3, height // 300)),
        )
        open_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(5, width // 200), 2))
        mask = cv2.morphologyEx(dark_neutral_mask, cv2.MORPH_CLOSE, close_kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, open_kernel)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates: list[_BannerCandidate] = []
        for contour in contours:
            x, y, candidate_width, candidate_height = cv2.boundingRect(contour)
            absolute_y = y + search_top
            fill_density = cv2.contourArea(contour) / max(1, candidate_width * candidate_height)
            if not self._looks_like_banner(width, height, candidate_width, candidate_height, fill_density):
                continue
            text_pixel_count = self._count_text_pixels(search[y : y + candidate_height, x : x + candidate_width])
            confidence = self._score_candidate(
                image_width=width,
                image_height=height,
                candidate_width=candidate_width,
                candidate_height=candidate_height,
                fill_density=fill_density,
                text_pixel_count=text_pixel_count,
            )
            candidates.append(
                _BannerCandidate(
                    x=x,
                    y=absolute_y,
                    width=candidate_width,
                    height=candidate_height,
                    confidence=confidence,
                    fill_density=fill_density,
                    text_pixel_count=text_pixel_count,
                )
            )

        candidates.sort(key=lambda candidate: candidate.confidence, reverse=True)
        return candidates

    def _looks_like_banner(
        self,
        image_width: int,
        image_height: int,
        width: int,
        height: int,
        fill_density: float,
    ) -> bool:
        return (
            width >= image_width * self.MIN_BANNER_WIDTH_RATIO
            and image_width * 0.015 <= height <= image_height * self.MAX_BANNER_HEIGHT_RATIO
            and height >= image_height * self.MIN_BANNER_HEIGHT_RATIO
            and width / max(1, height) >= self.MIN_ASPECT_RATIO
            and fill_density >= 0.35
        )

    def _score_candidate(
        self,
        *,
        image_width: int,
        image_height: int,
        candidate_width: int,
        candidate_height: int,
        fill_density: float,
        text_pixel_count: int,
    ) -> float:
        width_score = min(candidate_width / max(1, image_width * 0.30), 1.0)
        height_score = min(candidate_height / max(1, image_height * 0.05), 1.0)
        fill_score = min(fill_density, 1.0)
        text_score = min(text_pixel_count / 2000, 1.0)
        return round((width_score * 0.30) + (height_score * 0.20) + (fill_score * 0.25) + (text_score * 0.25), 4)

    def _find_text_roi(self, image: np.ndarray, banner: _BannerCandidate) -> dict[str, int]:
        banner_image = image[banner.y : banner.y + banner.height, banner.x : banner.x + banner.width]
        text_mask = self._text_mask(banner_image)
        points = cv2.findNonZero(text_mask)
        if points is None:
            return banner.roi

        x, y, width, height = cv2.boundingRect(points)
        pad_x = max(4, round(banner.width * 0.015))
        pad_y = max(3, round(banner.height * 0.10))
        absolute_x = banner.x + max(0, x - pad_x)
        absolute_y = banner.y + max(0, y - pad_y)
        right = min(banner.x + banner.width, banner.x + x + width + pad_x)
        bottom = min(banner.y + banner.height, banner.y + y + height + pad_y)
        return {
            "x": absolute_x,
            "y": absolute_y,
            "width": max(1, right - absolute_x),
            "height": max(1, bottom - absolute_y),
        }

    def _count_text_pixels(self, image: np.ndarray) -> int:
        return int(np.count_nonzero(self._text_mask(image)))

    @staticmethod
    def _text_mask(image: np.ndarray) -> np.ndarray:
        if image.size == 0:
            return np.zeros((1, 1), dtype=np.uint8)
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        white_text = (gray > 150) & (hsv[:, :, 1] < 120)
        orange_text = (hsv[:, :, 0] >= 5) & (hsv[:, :, 0] <= 35) & (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 120)
        mask = (white_text | orange_text).astype(np.uint8) * 255
        return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))

    def _write_crop(
        self,
        image: np.ndarray,
        *,
        screenshot_path: Path,
        roi: dict[str, int],
        crop_kind: str,
    ) -> SkillUseTextCrop:
        self.runtime_crop_dir.mkdir(parents=True, exist_ok=True)
        crop = image[roi["y"] : roi["y"] + roi["height"], roi["x"] : roi["x"] + roi["width"]]
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        output_path = self.runtime_crop_dir / f"{crop_kind}-{timestamp}.png"
        encoded, buffer = cv2.imencode(".png", crop)
        if not encoded:
            raise ValueError(f"Failed to encode {crop_kind} crop: {roi}")
        buffer.tofile(str(output_path))
        return SkillUseTextCrop(
            image_bytes=output_path.read_bytes(),
            path=str(output_path),
            roi=roi,
            source_screenshot_path=str(screenshot_path),
            crop_kind=crop_kind,
        )

    @staticmethod
    def _read_image(path: Path) -> np.ndarray:
        buffer = np.fromfile(str(path), dtype=np.uint8)
        image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"Cannot read screenshot: {path}")
        return image

    @staticmethod
    def _side_for_banner(image_width: int, banner: _BannerCandidate) -> str:
        center_x = banner.x + banner.width / 2
        if center_x < image_width * 0.40:
            return "left"
        if center_x > image_width * 0.60:
            return "right"
        return "center"
