from __future__ import annotations

import math
from collections import deque
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, qGray


class ImageFeatureExtractor:
    DEFAULT_ONNX_MODEL_PATH = Path("data") / "pet_vision" / "models" / "reference_embedding.onnx"

    def __init__(self, size: int = 24, model_path: Path | None = None) -> None:
        self.fallback = _HandcraftedFeatureExtractor(size)
        self.model_backend = _OnnxImageEmbeddingBackend.try_create(model_path or self.DEFAULT_ONNX_MODEL_PATH)
        self.feature_version = self.model_backend.feature_version if self.model_backend else self.fallback.feature_version
        self.backend_name = self.model_backend.backend_name if self.model_backend else self.fallback.backend_name

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
        if self.model_backend is not None:
            try:
                return self.model_backend.extract_from_image(image)
            except Exception:  # noqa: BLE001 - 本地模型不可用时保持应用可用
                self.model_backend = None
                self.feature_version = self.fallback.feature_version
                self.backend_name = self.fallback.backend_name
        return self.fallback.extract_from_image(image)


class _OnnxImageEmbeddingBackend:
    def __init__(self, model_path: Path) -> None:
        import numpy as np  # noqa: PLC0415
        import onnxruntime as ort  # noqa: PLC0415

        options = ort.SessionOptions()
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.intra_op_num_threads = self._cpu_thread_count()
        self.session = ort.InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])
        self.input = self.session.get_inputs()[0]
        self.output = self.session.get_outputs()[-1]
        self.input_name = self.input.name
        self.output_name = self.output.name
        self.input_size = self._input_size(self.input.shape)
        self.np = np
        self.subject_helper = _HandcraftedFeatureExtractor()
        self.feature_version = self._feature_version(model_path)
        self.backend_name = f"onnx:{model_path.name}"

    @classmethod
    def try_create(cls, model_path: Path) -> "_OnnxImageEmbeddingBackend | None":
        if not model_path.exists() or model_path.stat().st_size < 1024:
            return None
        if not cls._looks_like_embedding_model(model_path):
            return None
        try:
            return cls(model_path)
        except Exception:  # noqa: BLE001
            return None

    def extract_from_image(self, image: QImage) -> list[float]:
        tensor = self._image_to_tensor(self.subject_helper._subject_image(image))
        raw = self.session.run([self.output_name], {self.input_name: tensor})[0]
        values = self.np.asarray(raw, dtype=self.np.float32).reshape(-1)
        values = values - values.mean()
        norm = float(self.np.linalg.norm(values))
        if norm <= 0:
            return [0.0 for _ in values.tolist()]
        return [round(float(value / norm), 8) for value in values]

    def _image_to_tensor(self, image: QImage) -> Any:
        rgb = image.convertToFormat(QImage.Format.Format_RGB888).scaled(
            self.input_size,
            self.input_size,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        raw = self.np.frombuffer(bytes(rgb.constBits()), dtype=self.np.uint8)
        rows = raw.reshape((rgb.height(), rgb.bytesPerLine()))[:, : rgb.width() * 3]
        array = rows.reshape((rgb.height(), rgb.width(), 3)).astype(self.np.float32) / 255.0
        mean = self.np.array([0.485, 0.456, 0.406], dtype=self.np.float32)
        std = self.np.array([0.229, 0.224, 0.225], dtype=self.np.float32)
        array = (array - mean) / std
        return self.np.transpose(array, (2, 0, 1))[self.np.newaxis, :, :, :]

    @staticmethod
    def _input_size(shape: list[Any]) -> int:
        for value in reversed(shape):
            if isinstance(value, int) and value > 1:
                return value
        return 224

    @staticmethod
    def _cpu_thread_count() -> int:
        import os

        logical = max(1, os.cpu_count() or 1)
        if logical <= 2:
            return 1
        if logical <= 4:
            return 2
        if logical <= 12:
            return 3
        return 4

    @staticmethod
    def _feature_version(model_path: Path) -> int:
        stat = model_path.stat()
        return 3000 + (stat.st_size % 997)

    @staticmethod
    def _looks_like_embedding_model(model_path: Path) -> bool:
        name = model_path.stem.lower()
        return any(token in name for token in ("embedding", "embed", "feature", "clip", "dino"))


class _HandcraftedFeatureExtractor:
    feature_version = 2
    backend_name = "handcrafted-reference-v2"

    def __init__(self, size: int = 24) -> None:
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
        subject = self._subject_image(image)
        scaled = subject.convertToFormat(QImage.Format.Format_RGB32).scaled(
            self.size,
            self.size,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        values: list[float] = []
        for y in range(self.size):
            for x in range(self.size):
                color = scaled.pixelColor(x, y)
                values.extend([color.redF() * 0.55, color.greenF() * 0.55, color.blueF() * 0.55])
        values.extend(value * 2.4 for value in self._color_histogram(subject))
        values.extend(value * 0.9 for value in self._edge_grid(scaled))
        mean = sum(values) / len(values)
        centered = [value - mean for value in values]
        norm = math.sqrt(sum(value * value for value in centered))
        if norm == 0:
            return [0.0 for _ in centered]
        return [round(value / norm, 8) for value in centered]

    def _subject_image(self, image: QImage) -> QImage:
        bbox = self._foreground_bbox(image)
        if bbox is None:
            return image
        x, y, width, height = bbox
        pad_x = max(2, round(width * 0.08))
        pad_y = max(2, round(height * 0.08))
        left = max(0, x - pad_x)
        top = max(0, y - pad_y)
        right = min(image.width(), x + width + pad_x)
        bottom = min(image.height(), y + height + pad_y)
        cropped = image.copy(left, top, max(1, right - left), max(1, bottom - top))
        return cropped if not cropped.isNull() else image

    def _foreground_bbox(self, image: QImage) -> tuple[int, int, int, int] | None:
        if image.width() <= 0 or image.height() <= 0:
            return None
        max_side = 144
        scale = min(1.0, max_side / max(image.width(), image.height()))
        mask_image = image
        if scale < 1.0:
            mask_image = image.scaled(
                max(1, round(image.width() * scale)),
                max(1, round(image.height() * scale)),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )

        has_transparency = self._has_meaningful_transparency(mask_image)
        mask: list[list[bool]] = []
        for y in range(mask_image.height()):
            row: list[bool] = []
            for x in range(mask_image.width()):
                color = mask_image.pixelColor(x, y)
                if has_transparency:
                    row.append(color.alphaF() > 0.12)
                    continue
                hue, saturation, value = self._hsv(color.redF(), color.greenF(), color.blueF())
                row.append(saturation > 0.30 and value > 0.22 and not (0.19 < hue < 0.46 and value < 0.42))
            mask.append(row)

        component = self._best_component(mask)
        if component is None:
            return None
        x, y, width, height = component
        inv_scale = 1.0 / scale
        return (
            max(0, math.floor(x * inv_scale)),
            max(0, math.floor(y * inv_scale)),
            min(image.width(), math.ceil(width * inv_scale)),
            min(image.height(), math.ceil(height * inv_scale)),
        )

    @staticmethod
    def _has_meaningful_transparency(image: QImage) -> bool:
        if not image.hasAlphaChannel():
            return False
        step_x = max(1, image.width() // 32)
        step_y = max(1, image.height() // 32)
        for y in range(0, image.height(), step_y):
            for x in range(0, image.width(), step_x):
                if image.pixelColor(x, y).alpha() < 250:
                    return True
        return False

    @classmethod
    def _best_component(cls, mask: list[list[bool]]) -> tuple[int, int, int, int] | None:
        height = len(mask)
        width = len(mask[0]) if height else 0
        if width == 0:
            return None
        visited = [[False for _ in range(width)] for _ in range(height)]
        best: tuple[float, tuple[int, int, int, int]] | None = None
        for start_y in range(height):
            for start_x in range(width):
                if visited[start_y][start_x] or not mask[start_y][start_x]:
                    continue
                area, min_x, min_y, max_x, max_y = cls._flood_component(mask, visited, start_x, start_y)
                if area < 8:
                    continue
                box_w = max_x - min_x + 1
                box_h = max_y - min_y + 1
                score = cls._component_score(area, min_x, min_y, box_w, box_h, width, height)
                if best is None or score > best[0]:
                    best = (score, (min_x, min_y, box_w, box_h))
        return best[1] if best is not None else None

    @staticmethod
    def _flood_component(
        mask: list[list[bool]],
        visited: list[list[bool]],
        start_x: int,
        start_y: int,
    ) -> tuple[int, int, int, int, int]:
        height = len(mask)
        width = len(mask[0])
        queue: deque[tuple[int, int]] = deque([(start_x, start_y)])
        visited[start_y][start_x] = True
        area = 0
        min_x = max_x = start_x
        min_y = max_y = start_y
        while queue:
            x, y = queue.popleft()
            area += 1
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if nx < 0 or ny < 0 or nx >= width or ny >= height:
                    continue
                if visited[ny][nx] or not mask[ny][nx]:
                    continue
                visited[ny][nx] = True
                queue.append((nx, ny))
        return area, min_x, min_y, max_x, max_y

    @staticmethod
    def _component_score(area: int, x: int, y: int, width: int, height: int, image_width: int, image_height: int) -> float:
        center_x = (x + width / 2) / image_width
        center_y = (y + height / 2) / image_height
        distance = math.sqrt((center_x - 0.5) ** 2 + (center_y - 0.45) ** 2)
        center_weight = max(0.25, 1.25 - distance * 1.6)
        border_touch_count = int(x <= 1) + int(y <= 1) + int(x + width >= image_width - 1) + int(y + height >= image_height - 1)
        border_weight = 0.55**border_touch_count
        coverage = (width * height) / max(1, image_width * image_height)
        size_weight = 0.35 if coverage > 0.70 else 1.0
        return area * center_weight * border_weight * size_weight

    def _color_histogram(self, image: QImage) -> list[float]:
        hue_bins = [0.0] * 24
        saturation_bins = [0.0] * 6
        value_bins = [0.0] * 6
        total = 0.0
        scaled = image.convertToFormat(QImage.Format.Format_RGBA8888).scaled(
            64,
            64,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        for y in range(scaled.height()):
            for x in range(scaled.width()):
                color = scaled.pixelColor(x, y)
                alpha = color.alphaF()
                if alpha <= 0.08:
                    continue
                hue, saturation, value = self._hsv(color.redF(), color.greenF(), color.blueF())
                weight = alpha * (0.35 + saturation) * max(0.18, value)
                hue_bins[min(23, int(hue * 24))] += weight
                saturation_bins[min(5, int(saturation * 6))] += weight
                value_bins[min(5, int(value * 6))] += weight
                total += weight
        if total <= 0:
            return [0.0] * (len(hue_bins) + len(saturation_bins) + len(value_bins))
        return [value / total for value in [*hue_bins, *saturation_bins, *value_bins]]

    def _silhouette_grid(self, image: QImage) -> list[float]:
        scaled = image.scaled(
            self.size,
            self.size,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        has_transparency = self._has_meaningful_transparency(scaled)
        values: list[float] = []
        for y in range(scaled.height()):
            for x in range(scaled.width()):
                color = scaled.pixelColor(x, y)
                if has_transparency:
                    values.append(color.alphaF())
                    continue
                _hue, saturation, value = self._hsv(color.redF(), color.greenF(), color.blueF())
                values.append(1.0 if saturation > 0.26 and value > 0.20 else 0.0)
        return values

    @staticmethod
    def _edge_grid(image: QImage) -> list[float]:
        values: list[float] = []
        width = image.width()
        height = image.height()
        for y in range(height):
            for x in range(width):
                current = qGray(image.pixel(x, y)) / 255.0
                right = qGray(image.pixel(min(width - 1, x + 1), y)) / 255.0
                down = qGray(image.pixel(x, min(height - 1, y + 1))) / 255.0
                values.append(abs(current - right) + abs(current - down))
        max_value = max(values) if values else 0.0
        if max_value <= 0:
            return [0.0 for _ in values]
        return [value / max_value for value in values]

    @staticmethod
    def _hsv(red: float, green: float, blue: float) -> tuple[float, float, float]:
        max_value = max(red, green, blue)
        min_value = min(red, green, blue)
        delta = max_value - min_value
        if delta == 0:
            hue = 0.0
        elif max_value == red:
            hue = ((green - blue) / delta) % 6
        elif max_value == green:
            hue = ((blue - red) / delta) + 2
        else:
            hue = ((red - green) / delta) + 4
        hue /= 6
        saturation = 0.0 if max_value == 0 else delta / max_value
        return hue, saturation, max_value


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    score = sum(a * b for a, b in zip(left, right, strict=True))
    return max(0.0, min(1.0, (score + 1.0) / 2.0))
