from __future__ import annotations

import base64
import json
import mimetypes
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .models import AdviceResult, AppSettings, BattleState, KnowledgeEntry


class MultimodalClient:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def describe_battle_state(self, image_bytes: bytes) -> BattleState:
        schema = {
            "name": "battle_state",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "player_pet": {"type": "string"},
                    "opponent_pet": {"type": "string"},
                    "player_hp_state": {"type": "string"},
                    "opponent_hp_state": {"type": "string"},
                    "visible_moves": {"type": "array", "items": {"type": "string"}},
                    "status_effects": {"type": "array", "items": {"type": "string"}},
                    "field_notes": {"type": "array", "items": {"type": "string"}},
                    "tactical_summary": {"type": "string"},
                    "suggested_query_terms": {"type": "array", "items": {"type": "string"}},
                    "unknowns": {"type": "array", "items": {"type": "string"}},
                    "confidence_map": {
                        "type": "object",
                        "additionalProperties": {"type": "number"},
                    },
                },
                "required": [
                    "player_pet",
                    "opponent_pet",
                    "player_hp_state",
                    "opponent_hp_state",
                    "visible_moves",
                    "status_effects",
                    "field_notes",
                    "tactical_summary",
                    "suggested_query_terms",
                    "unknowns",
                    "confidence_map",
                ],
                "additionalProperties": False,
            },
        }
        prompt = (
            "You are a visual battle-state analyzer for Rock Kingdom PVP. "
            "Extract only what is clearly visible in the screenshot. Do not invent facts. "
            "Put uncertain fields in unknowns and use low confidence scores."
        )
        payload = self._build_image_payload(prompt, image_bytes, schema)
        return BattleState(**self._parse_structured_output(self._post(payload)))

    def describe_knowledge_image(self, path: Path) -> dict[str, Any]:
        schema = {
            "name": "knowledge_image",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "facts": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "summary", "keywords", "facts"],
                "additionalProperties": False,
            },
        }
        prompt = (
            "This image is local Rock Kingdom PVP reference material. "
            "Summarize pet, skill, type matchup, and strategy facts as structured JSON."
        )
        payload = self._build_image_payload(
            prompt,
            path.read_bytes(),
            schema,
            mime_type=self._guess_mime_type(path),
        )
        return self._parse_structured_output(self._post(payload))

    def generate_advice(self, battle_state: BattleState, knowledge_hits: list[KnowledgeEntry]) -> AdviceResult:
        schema = {
            "name": "advice_result",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "recommended_action": {"type": "string"},
                    "reason": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "string"},
                    "caveats": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["recommended_action", "reason", "evidence", "confidence", "caveats"],
                "additionalProperties": False,
            },
        }
        knowledge_text = "\n\n".join(
            f"[Knowledge {index + 1}]\n{entry.to_prompt_block()}"
            for index, entry in enumerate(knowledge_hits)
        ) or "No local knowledge matched. Give a cautious recommendation and state uncertainty."
        prompt = (
            "You are a Rock Kingdom PVP strategy assistant. "
            "Use the battle_state and local knowledge hits to recommend the best current-turn action. "
            "Be concise, useful, executable, and cite local evidence titles when possible."
        )
        user_text = json.dumps(
            {
                "battle_state": battle_state.to_dict(),
                "knowledge_hits": [entry.to_prompt_block() for entry in knowledge_hits],
                "knowledge_summary": knowledge_text,
            },
            ensure_ascii=False,
            indent=2,
        )
        payload = {
            "model": self.settings.model,
            "input": [
                {"role": "developer", "content": [{"type": "input_text", "text": prompt}]},
                {"role": "user", "content": [{"type": "input_text", "text": user_text}]},
            ],
            "text": {"format": {"type": "json_schema", **schema}},
        }
        self._apply_common_options(payload)
        return AdviceResult(**self._parse_structured_output(self._post(payload)))

    def _build_image_payload(
        self,
        prompt: str,
        image_bytes: bytes,
        schema: dict[str, Any],
        mime_type: str = "image/png",
    ) -> dict[str, Any]:
        payload = {
            "model": self.settings.model,
            "input": [
                {"role": "developer", "content": [{"type": "input_text", "text": prompt}]},
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "Return structured JSON."},
                        {
                            "type": "input_image",
                            "image_url": self._to_data_url(image_bytes, mime_type),
                            "detail": self.settings.screenshot_detail,
                        },
                    ],
                },
            ],
            "text": {"format": {"type": "json_schema", **schema}},
        }
        self._apply_common_options(payload)
        return payload

    def _apply_common_options(self, payload: dict[str, Any]) -> None:
        if self.settings.disable_response_storage:
            payload["store"] = False
        if self.settings.model_reasoning_effort in {"minimal", "low", "medium", "high"}:
            payload["reasoning"] = {"effort": self.settings.model_reasoning_effort}

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.settings.wire_api != "responses":
            raise RuntimeError(f"Only Responses wire_api is supported, got: {self.settings.wire_api}")
        if self.settings.requires_openai_auth and not self.settings.api_key.strip():
            raise RuntimeError("Please enter an API Key in the app settings first.")

        endpoint = self.settings.base_url.rstrip("/") + "/responses"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.settings.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Model API request failed ({exc.code}): {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not connect to model API: {exc.reason}") from exc

    @staticmethod
    def _parse_structured_output(response_data: dict[str, Any]) -> dict[str, Any]:
        if response_data.get("output_text"):
            return json.loads(response_data["output_text"])
        for item in response_data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    return json.loads(content["text"])
        raise RuntimeError("Model did not return parseable structured output.")

    @staticmethod
    def _to_data_url(image_bytes: bytes, mime_type: str) -> str:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    @staticmethod
    def _guess_mime_type(path: Path) -> str:
        return mimetypes.guess_type(path.name)[0] or "image/png"
