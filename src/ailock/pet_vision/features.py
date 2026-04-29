from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage


class ImageFeatureExtractor:
    def __init__(self, size: int = 16) -> None:
        self.size = size

    def extract_from_path(self, path: Path) -> list[float]:
        image = QImage(str(path))
        if image.isNull():
            raise ValueError(f"无法读取图片特征：{path}")
        return self.extract_from_image(image)

    def extract_from_bytes(self, image_bytes: bytes) -> list[float]:
        image = QImage()
        if not image.loadFromData(image_bytes):
            raise ValueError("无法读取图片字节特征")
        return self.extract_from_image(image)

    def extract_from_image(self, image: QImage) -> list[float]:
        scaled = image.convertToFormat(QImage.Format.Format_RGB32).scaled(
            self.size,
            self.size,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        values: list[float] = []
        for y in range(self.size):
            for x in range(self.size):
                color = scaled.pixelColor(x, y)
                values.extend([color.redF(), color.greenF(), color.blueF()])
        mean = sum(values) / len(values)
        centered = [value - mean for value in values]
        norm = math.sqrt(sum(value * value for value in centered))
        if norm == 0:
            return [0.0 for _ in centered]
        return [round(value / norm, 8) for value in centered]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    score = sum(a * b for a, b in zip(left, right, strict=True))
    return max(0.0, min(1.0, (score + 1.0) / 2.0))
