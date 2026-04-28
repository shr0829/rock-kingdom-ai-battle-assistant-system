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

    def answer_image(self, prompt: str, image_bytes: bytes, mime_type: str = "image/png") -> str:
        data_url = self._to_data_url(image_bytes, mime_type)
        errors: list[str] = []
        for strategy in self._image_request_strategies():
            try:
                payload = self._build_image_payload(prompt, data_url, strategy)
                return self._parse_text_output(self._post(payload, strategy["endpoint"]))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"[{strategy['label']}] {exc}")
        raise RuntimeError("所有图片输入纯文本兼容策略均失败：\n" + "\n".join(errors))

    def describe_battle_state(self, image_bytes: bytes) -> BattleState:
        prompt = (
            "你是洛克王国 PVP 战局识别助手。请直接看图，不要编造，只提取你能明确看见的内容。"
            "不要输出 JSON，不要输出 markdown 表格，不要额外解释。"
            "严格按下面格式逐行输出，字段名不要改，未知就写“未知”或“无”：\n"
            "我方精灵: ...\n"
            "对方精灵: ...\n"
            "我方血量: ...\n"
            "可见技能: 技能1 | 技能2 | 技能3\n"
            "已观察伤害: ...\n"
            "速度判断: ...\n"
            "状态效果: 状态1 | 状态2\n"
            "场地信息: ...\n"
            "战术总结: ...\n"
            "检索关键词: 关键词1 | 关键词2 | 关键词3\n"
            "不确定点: 疑点1 | 疑点2\n"
            "置信度: 我方精灵=0.80; 对方精灵=0.75; 速度判断=0.40"
        )
        try:
            parsed = self._parse_battle_state_text(self.answer_image(prompt, image_bytes))
        except Exception as exc:  # noqa: BLE001
            return self._fallback_battle_state(f"截图已发送，但识别失败：{exc}")
        if self._battle_state_is_insufficient(parsed):
            return self._fallback_battle_state(
                parsed.tactical_summary or "截图里缺少足够的战斗信息，暂时无法稳定判断回合。",
                parsed,
            )
        return parsed

    def describe_knowledge_image(self, path: Path) -> dict[str, Any]:
        prompt = (
            "这是一张本地洛克王国 PVP 资料图。请直接看图并提炼可检索信息。"
            "不要输出 JSON，严格按下面格式逐行输出：\n"
            "标题: ...\n"
            "摘要: ...\n"
            "关键词: 关键词1 | 关键词2 | 关键词3\n"
            "要点: 要点1 | 要点2 | 要点3"
        )
        text = self.answer_image(prompt, path.read_bytes(), mime_type=self._guess_mime_type(path))
        return self._parse_knowledge_image_text(text, path)

    def generate_advice(self, battle_state: BattleState, knowledge_hits: list[KnowledgeEntry]) -> AdviceResult:
        if self._battle_state_is_insufficient(battle_state):
            return self._fallback_advice(battle_state)
        knowledge_text = "\n\n".join(
            f"[Knowledge {index + 1}]\n{entry.to_prompt_block()}"
            for index, entry in enumerate(knowledge_hits)
        ) or "No local knowledge matched. Give a cautious recommendation and state uncertainty."
        prompt = (
            "你是洛克王国 PVP 回合决策助手。"
            "请基于 battle_state 和本地知识命中，给出当前回合最可执行的建议。"
            "不要输出 JSON，不要写多段散文。严格按下面格式逐行输出：\n"
            "推荐操作: ...\n"
            "原因: ...\n"
            "资料依据: 依据1 | 依据2 | 依据3\n"
            "置信度: 高 / 中 / 低\n"
            "注意事项: 注意1 | 注意2"
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
        try:
            return self._parse_advice_text(self._post_text_for_answer(prompt, user_text))
        except Exception as exc:  # noqa: BLE001
            return self._fallback_advice(battle_state, f"建议生成失败：{exc}")

    def _parse_battle_state_text(self, text: str) -> BattleState:
        player_pet = self._extract_labeled_value(text, "我方精灵")
        opponent_pet = self._extract_labeled_value(text, "对方精灵")
        player_hp = self._extract_labeled_value(text, "我方血量")
        visible_moves = self._split_labeled_list(text, "可见技能")
        observed_damage = self._extract_labeled_value(text, "已观察伤害")
        speed_judgement = self._extract_labeled_value(text, "速度判断")
        status_effects = self._split_labeled_list(text, "状态效果")
        field_info = self._extract_labeled_value(text, "场地信息")
        tactical_summary = self._extract_labeled_value(text, "战术总结")
        query_terms = self._split_labeled_list(text, "检索关键词")
        unknowns = self._split_labeled_list(text, "不确定点")
        confidence_map = self._parse_confidence_map(self._extract_labeled_value(text, "置信度"))

        field_notes = [
            note
            for note in (observed_damage, speed_judgement, field_info)
            if note and not self._is_placeholder(note)
        ]

        if not query_terms:
            query_terms = self._build_query_terms(
                player_pet,
                opponent_pet,
                visible_moves,
                status_effects,
                field_notes,
                tactical_summary,
            )

        if not unknowns and (self._is_placeholder(player_pet) or self._is_placeholder(opponent_pet)):
            unknowns = ["未能稳定识别双方精灵"]

        return BattleState(
            player_pet="" if self._is_placeholder(player_pet) else player_pet,
            opponent_pet="" if self._is_placeholder(opponent_pet) else opponent_pet,
            player_hp_state="" if self._is_placeholder(player_hp) else player_hp,
            visible_moves=visible_moves,
            status_effects=status_effects,
            field_notes=field_notes,
            tactical_summary="" if self._is_placeholder(tactical_summary) else tactical_summary,
            suggested_query_terms=query_terms,
            unknowns=unknowns,
            confidence_map=confidence_map,
        )

    def _parse_knowledge_image_text(self, text: str, path: Path) -> dict[str, Any]:
        title = self._extract_labeled_value(text, "标题") or path.stem
        summary = self._extract_labeled_value(text, "摘要")
        keywords = self._split_labeled_list(text, "关键词")
        facts = self._split_labeled_list(text, "要点")
        if not summary:
            summary = "；".join(facts[:3]) or path.stem
        if not keywords:
            keywords = self._build_query_terms(title, "", [], [], facts, summary)
        return {
            "title": title,
            "summary": summary,
            "keywords": keywords,
            "facts": facts,
        }

    def _parse_advice_text(self, text: str) -> AdviceResult:
        recommended_action = self._extract_labeled_value(text, "推荐操作")
        reason = self._extract_labeled_value(text, "原因")
        evidence = self._split_labeled_list(text, "资料依据")
        confidence = self._extract_labeled_value(text, "置信度")
        caveats = self._split_labeled_list(text, "注意事项")
        return AdviceResult(
            recommended_action=self._fallback_value(
                recommended_action,
                "先补一张包含完整战斗区的截图，再决定出招或换宠。",
            ),
            reason=self._fallback_value(
                reason,
                "当前返回内容不足以支持稳定决策，因此优先补全战斗信息。",
            ),
            evidence=evidence,
            confidence=self._fallback_value(confidence, "中"),
            caveats=caveats,
        )

    def _post_text_for_answer(self, prompt: str, user_text: str) -> str:
        errors: list[str] = []
        for strategy in self._text_request_strategies():
            try:
                payload = self._build_text_payload(prompt, user_text, strategy)
                return self._parse_text_output(self._post(payload, strategy["endpoint"]))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"[{strategy['label']}] {exc}")
        raise RuntimeError("所有纯文本兼容策略均失败：\n" + "\n".join(errors))

    @staticmethod
    def _extract_labeled_value(text: str, label: str) -> str:
        match = re.search(rf"(?mi)^\s*{re.escape(label)}\s*[：:]\s*(.*?)\s*$", text)
        return match.group(1).strip() if match else ""

    def _split_labeled_list(self, text: str, label: str) -> list[str]:
        return self._split_items(self._extract_labeled_value(text, label))

    def _split_items(self, raw_value: str) -> list[str]:
        if not raw_value or self._is_placeholder(raw_value):
            return []
        items = [
            item.strip()
            for item in re.split(r"[|｜,，、/；;]+", raw_value)
            if item.strip()
        ]
        return [item for item in items if not self._is_placeholder(item)]

    @staticmethod
    def _is_placeholder(value: str) -> bool:
        normalized = value.strip().lower()
        return normalized in {"", "无", "未知", "未见", "不明", "none", "n/a", "na", "-", "null"}

    @staticmethod
    def _parse_confidence_map(raw_value: str) -> dict[str, float]:
        key_aliases = {
            "我方精灵": "player_pet",
            "对方精灵": "opponent_pet",
            "我方血量": "player_hp_state",
            "速度判断": "speed_judgement",
            "可见技能": "visible_moves",
            "状态效果": "status_effects",
        }
        confidence_map: dict[str, float] = {}
        for key, value in re.findall(r"([^=；;,\n]+)\s*=\s*([01](?:\.\d+)?)", raw_value):
            normalized_key = key_aliases.get(key.strip(), key.strip())
            try:
                confidence_map[normalized_key] = float(value)
            except ValueError:
                continue
        return confidence_map

    def _build_query_terms(
        self,
        player_pet: str,
        opponent_pet: str,
        visible_moves: list[str],
        status_effects: list[str],
        field_notes: list[str],
        tactical_summary: str,
    ) -> list[str]:
        raw_terms = [
            player_pet,
            opponent_pet,
            *visible_moves,
            *status_effects,
            *field_notes,
            tactical_summary,
        ]
        unique_terms: list[str] = []
        seen: set[str] = set()
        for raw_term in raw_terms:
            if not raw_term or self._is_placeholder(raw_term):
                continue
            for term in self._split_items(raw_term) or [raw_term.strip()]:
                normalized = term.lower()
                if normalized and normalized not in seen and len(term) > 1:
                    unique_terms.append(term)
                    seen.add(normalized)
        return unique_terms[:12]

    def _battle_state_is_insufficient(self, battle_state: BattleState) -> bool:
        return not any(
            [
                battle_state.player_pet,
                battle_state.player_hp_state,
                battle_state.visible_moves,
                battle_state.status_effects,
            ]
        )

    def _fallback_battle_state(self, reason: str, partial: BattleState | None = None) -> BattleState:
        partial = partial or BattleState()
        query_terms = partial.suggested_query_terms or self._build_query_terms(
            partial.player_pet,
            partial.opponent_pet,
            partial.visible_moves,
            partial.status_effects,
            partial.field_notes,
            partial.tactical_summary or reason,
        )
        unknowns = partial.unknowns or ["请截到完整的战斗区域后再分析"]
        field_notes = partial.field_notes or [reason]
        return BattleState(
            player_pet=partial.player_pet,
            opponent_pet=partial.opponent_pet,
            player_hp_state=partial.player_hp_state,
            visible_moves=partial.visible_moves,
            status_effects=partial.status_effects,
            field_notes=field_notes,
            tactical_summary=partial.tactical_summary or reason,
            suggested_query_terms=query_terms,
            unknowns=unknowns,
            confidence_map=partial.confidence_map,
        )

    def _fallback_advice(self, battle_state: BattleState, error: str | None = None) -> AdviceResult:
        notes = battle_state.unknowns or battle_state.field_notes or ["请重新截图"]
        return AdviceResult(
            recommended_action="先补一张包含完整战斗区域的截图，再决定出招或换宠。",
            reason=error or battle_state.tactical_summary or "当前识别信息不足，无法给出可靠回合建议。",
            evidence=notes[:3],
            confidence="高",
            caveats=["截图中尽量包含我方状态、可见技能、速度先后手信息"],
        )

    def _fallback_value(self, value: str, fallback: str) -> str:
        return fallback if self._is_placeholder(value) else value

    @staticmethod
    def _text_request_strategies() -> list[dict[str, str]]:
        return [
            {"label": "responses-text", "endpoint": "responses", "mode": "responses"},
            {"label": "chat-text", "endpoint": "chat/completions", "mode": "chat"},
        ]

    @staticmethod
    def _image_request_strategies() -> list[dict[str, str]]:
        return [
            {"label": "responses-input-image-string", "endpoint": "responses", "mode": "responses_string"},
            {"label": "responses-input-image-object", "endpoint": "responses", "mode": "responses_object"},
            {"label": "chat-image-url-object", "endpoint": "chat/completions", "mode": "chat_object"},
            {"label": "chat-image-url-string", "endpoint": "chat/completions", "mode": "chat_string"},
        ]

    def _build_text_payload(
        self,
        prompt: str,
        user_text: str,
        strategy: dict[str, str],
    ) -> dict[str, Any]:
        if strategy["endpoint"] == "responses":
            payload = {
                "model": self.settings.model,
                "input": [
                    {"role": "developer", "content": [{"type": "input_text", "text": prompt}]},
                    {"role": "user", "content": [{"type": "input_text", "text": user_text}]},
                ],
            }
            self._apply_common_options(payload)
            return payload

        return {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0,
        }

    def _build_image_payload(
        self,
        prompt: str,
        data_url: str,
        strategy: dict[str, str],
    ) -> dict[str, Any]:
        if strategy["endpoint"] == "responses":
            image_part: dict[str, Any] = (
                {
                    "type": "input_image",
                    "image_url": {"url": data_url},
                    "detail": self.settings.screenshot_detail,
                }
                if strategy["mode"] == "responses_object"
                else {
                    "type": "input_image",
                    "image_url": data_url,
                    "detail": self.settings.screenshot_detail,
                }
            )
            payload = {
                "model": self.settings.model,
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": prompt},
                            image_part,
                        ],
                    },
                ],
            }
            self._apply_common_options(payload)
            return payload

        image_part = (
            {"type": "image_url", "image_url": data_url}
            if strategy["mode"] == "chat_string"
            else {"type": "image_url", "image_url": {"url": data_url, "detail": self.settings.screenshot_detail}}
        )
        return {
            "model": self.settings.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
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
    def _parse_text_output(response_data: dict[str, Any]) -> str:
        if isinstance(response_data.get("output_text"), str) and response_data["output_text"].strip():
            return response_data["output_text"].strip()
        choice_content = response_data.get("choices", [{}])[0].get("message", {}).get("content")
        if isinstance(choice_content, str) and choice_content.strip():
            return MultimodalClient._strip_json_fence(choice_content)
        if isinstance(choice_content, list):
            text_parts = [
                part.get("text", "")
                for part in choice_content
                if isinstance(part, dict) and part.get("type") in {"text", "output_text"} and part.get("text")
            ]
            if text_parts:
                return "\n".join(text_parts).strip()
        for item in response_data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    return content["text"].strip()
        raise RuntimeError("Model did not return parseable text output.")

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
