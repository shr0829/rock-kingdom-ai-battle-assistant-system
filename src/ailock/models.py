from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class AppSettings:
    api_key: str = ""
    model_provider: str = "OpenAI"
    model: str = "gpt-5.5"
    review_model: str = "gpt-5.5"
    model_reasoning_effort: str = "xhigh"
    base_url: str = "https://api.asxs.top/v1"
    wire_api: str = "responses"
    requires_openai_auth: bool = True
    disable_response_storage: bool = True
    network_access: str = "enabled"
    windows_wsl_setup_acknowledged: bool = True
    model_context_window: int = 400000
    model_auto_compact_token_limit: int = 360000
    hotkey: str = "Ctrl+Shift+A"
    max_knowledge_hits: int = 5
    screenshot_detail: str = "high"
    capture_window_title: str = "洛克王国"
    capture_window_client_area: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BattleState:
    player_pet: str = ""
    opponent_pet: str = ""
    player_hp_state: str = ""
    visible_moves: list[str] = field(default_factory=list)
    status_effects: list[str] = field(default_factory=list)
    field_notes: list[str] = field(default_factory=list)
    tactical_summary: str = ""
    suggested_query_terms: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    confidence_map: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_query(self) -> str:
        parts = [
            self.player_pet,
            self.opponent_pet,
            *self.visible_moves,
            *self.status_effects,
            *self.field_notes,
            *self.suggested_query_terms,
            self.tactical_summary,
        ]
        return " ".join(part for part in parts if part).strip()


@dataclass(slots=True)
class KnowledgeEntry:
    source_path: str
    source_type: str
    title: str
    content: str
    keywords: list[str] = field(default_factory=list)
    score: float = 0.0

    def to_prompt_block(self) -> str:
        keyword_text = ", ".join(self.keywords) if self.keywords else "none"
        return (
            f"Title: {self.title}\n"
            f"Source: {self.source_type} | {self.source_path}\n"
            f"Keywords: {keyword_text}\n"
            f"Summary: {self.content}"
        )


@dataclass(slots=True)
class AdviceResult:
    recommended_action: str
    reason: str
    evidence: list[str] = field(default_factory=list)
    confidence: str = ""
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AnalysisResult:
    battle_state: BattleState
    advice: AdviceResult
    knowledge_hits: list[KnowledgeEntry] = field(default_factory=list)
    screenshot_path: str = ""
    timing_log_path: str = ""
    timing_events: list[dict[str, Any]] = field(default_factory=list)
