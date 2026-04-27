from __future__ import annotations

import base64
import json
import mimetypes
import re
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
        return BattleState(**self._post_image_for_json(prompt, image_bytes, schema))

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
        return self._post_image_for_json(
            prompt,
            path.read_bytes(),
            schema,
            mime_type=self._guess_mime_type(path),
        )

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
        return AdviceResult(**self._parse_structured_output(self._post(payload, "responses")))

    def _post_image_for_json(
        self,
        prompt: str,
        image_bytes: bytes,
        schema: dict[str, Any],
        mime_type: str = "image/png",
    ) -> dict[str, Any]:
        data_url = self._to_data_url(image_bytes, mime_type)
        errors: list[str] = []
        for strategy in self._image_request_strategies():
            try:
                payload = self._build_image_payload(prompt, data_url, schema, strategy)
                return self._parse_structured_output(self._post(payload, strategy["endpoint"]))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"[{strategy['label']}] {exc}")
        raise RuntimeError("所有图片输入兼容策略均失败：\n" + "\n".join(errors))

    @staticmethod
    def _image_request_strategies() -> list[dict[str, str]]:
        return [
            {"label": "responses-input-image-string", "endpoint": "responses", "mode": "responses_string"},
            {"label": "responses-input-image-object", "endpoint": "responses", "mode": "responses_object"},
            {"label": "chat-image-url-object", "endpoint": "chat/completions", "mode": "chat_object"},
            {"label": "chat-image-url-string", "endpoint": "chat/completions", "mode": "chat_string"},
        ]

    def _build_image_payload(
        self,
        prompt: str,
        data_url: str,
        schema: dict[str, Any],
        strategy: dict[str, str],
    ) -> dict[str, Any]:
        if strategy["endpoint"] == "responses":
            image_part: dict[str, Any]
            if strategy["mode"] == "responses_object":
                image_part = {
                    "type": "input_image",
                    "image_url": {"url": data_url},
                    "detail": self.settings.screenshot_detail,
                }
            else:
                image_part = {
                    "type": "input_image",
                    "image_url": data_url,
                    "detail": self.settings.screenshot_detail,
                }
            payload = {
                "model": self.settings.model,
                "input": [
                    {"role": "developer", "content": [{"type": "input_text", "text": prompt}]},
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "Return structured JSON."},
                            image_part,
                        ],
                    },
                ],
                "text": {"format": {"type": "json_schema", **schema}},
            }
            self._apply_common_options(payload)
            return payload

        image_part = (
            {"type": "image_url", "image_url": data_url}
            if strategy["mode"] == "chat_string"
            else {"type": "image_url", "image_url": {"url": data_url, "detail": self.settings.screenshot_detail}}
        )
        schema_text = json.dumps(schema["schema"], ensure_ascii=False)
        return {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Return only JSON matching this schema: {schema_text}"},
                        image_part,
                    ],
                },
            ],
            "temperature": 0,
        }

    def _apply_common_options(self, payload: dict[str, Any]) -> None:
        if self.settings.disable_response_storage:
            payload["store"] = False
        if self.settings.model_reasoning_effort in {"minimal", "low", "medium", "high"}:
            payload["reasoning"] = {"effort": self.settings.model_reasoning_effort}

    def _post(self, payload: dict[str, Any], endpoint_kind: str = "responses") -> dict[str, Any]:
        if endpoint_kind == "responses" and self.settings.wire_api not in {"responses", "auto"}:
            raise RuntimeError(f"Only Responses wire_api is supported for text requests, got: {self.settings.wire_api}")
        if self.settings.requires_openai_auth and not self.settings.api_key.strip():
            raise RuntimeError("Please enter an API Key in the app settings first.")

        endpoint = self._endpoint_url(endpoint_kind)
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=self._build_headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(self._format_http_error(exc.code, body, payload)) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not connect to model API: {exc.reason}") from exc

    def _format_http_error(self, status_code: int, body: str, payload: dict[str, Any]) -> str:
        parsed = self._try_parse_json(body)
        is_cloudflare_502 = (
            status_code == 502
            and isinstance(parsed, dict)
            and parsed.get("cloudflare_error") is True
        )
        if is_cloudflare_502 and self._payload_contains_image(payload):
            retry_after = parsed.get("retry_after", 60)
            return (
                "当前模型网关可以访问，但图片输入请求被上游网关返回 502。"
                "我已验证 api.asxs.top 的文本接口可用，但视觉图片输入会失败；"
                "因此当前 base_url 暂时不能用于截图识别。\n\n"
                f"处理建议：等待约 {retry_after} 秒后重试，或在 config.toml 中切换到支持 Responses 图片输入的模型网关。"
            )
        if isinstance(parsed, dict):
            message = parsed.get("error", {}).get("message") if isinstance(parsed.get("error"), dict) else None
            detail = parsed.get("detail") or parsed.get("message") or message
            if detail:
                return f"Model API request failed ({status_code}): {detail}"
        return f"Model API request failed ({status_code}): {body}"

    @staticmethod
    def _payload_contains_image(payload: dict[str, Any]) -> bool:
        def walk(value) -> bool:
            if isinstance(value, dict):
                if value.get("type") in {"input_image", "image_url"}:
                    return True
                return any(walk(child) for child in value.values())
            if isinstance(value, list):
                return any(walk(child) for child in value)
            return False

        return walk(payload)

    @staticmethod
    def _try_parse_json(text: str) -> Any:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def _build_headers(self) -> dict[str, str]:
        # api.asxs.top is behind Cloudflare and rejects Python urllib's default
        # User-Agent with 403 / error code 1010. A normal browser-like UA keeps
        # the OpenAI-compatible endpoint reachable while preserving the same API.
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36 AILock/0.1"
            ),
        }
        if self.settings.api_key.strip():
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        return headers

    def _endpoint_url(self, endpoint_kind: str) -> str:
        base = self.settings.base_url.rstrip("/")
        if endpoint_kind == "responses":
            return base if base.endswith("/responses") else base + "/responses"
        if endpoint_kind == "chat/completions":
            return base if base.endswith("/chat/completions") else base + "/chat/completions"
        raise RuntimeError(f"Unsupported endpoint: {endpoint_kind}")

    @staticmethod
    def _parse_structured_output(response_data: dict[str, Any]) -> dict[str, Any]:
        if response_data.get("output_text"):
            return json.loads(response_data["output_text"])
        choice_content = response_data.get("choices", [{}])[0].get("message", {}).get("content")
        if isinstance(choice_content, str) and choice_content.strip():
            return json.loads(MultimodalClient._strip_json_fence(choice_content))
        for item in response_data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    return json.loads(content["text"])
        raise RuntimeError("Model did not return parseable structured output.")

    @staticmethod
    def _strip_json_fence(text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
            stripped = re.sub(r"\s*```$", "", stripped)
        return stripped

    @staticmethod
    def _to_data_url(image_bytes: bytes, mime_type: str) -> str:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    @staticmethod
    def _guess_mime_type(path: Path) -> str:
        return mimetypes.guess_type(path.name)[0] or "image/png"
