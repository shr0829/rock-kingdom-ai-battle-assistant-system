from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class PetCrop:
    side: str
    image_bytes: bytes
    path: str
    roi: dict[str, int]
    source_screenshot_path: str


@dataclass(frozen=True, slots=True)
class PetCandidate:
    pet_id: int | None
    name: str
    confidence: float
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "pet_id": self.pet_id,
            "name": self.name,
            "confidence": self.confidence,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class PetRecognitionResult:
    side: str
    pet_id: int | None
    name: str
    confidence: float
    top_candidates: list[PetCandidate] = field(default_factory=list)
    source: str = ""
    crop_path: str = ""
    crop: PetCrop | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "pet_id": self.pet_id,
            "name": self.name,
            "confidence": self.confidence,
            "top_candidates": [candidate.to_dict() for candidate in self.top_candidates],
            "source": self.source,
            "crop_path": self.crop_path,
            "roi": self.crop.roi if self.crop else {},
        }


@dataclass(frozen=True, slots=True)
class DualPetRecognitionResult:
    player: PetRecognitionResult
    opponent: PetRecognitionResult
    screenshot_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "player": self.player.to_dict(),
            "opponent": self.opponent.to_dict(),
            "screenshot_path": self.screenshot_path,
        }


@dataclass(frozen=True, slots=True)
class PetCatalogEntry:
    id: int
    name: str
    no: str = ""
    aliases: list[str] = field(default_factory=list)
    primary_attribute: str = ""
    secondary_attribute: str = ""
    source: str = ""
