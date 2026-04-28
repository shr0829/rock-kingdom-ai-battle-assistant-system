from __future__ import annotations

import json
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import AppSettings


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    root: Path
    data_dir: Path
    captures_dir: Path
    knowledge_dir: Path
    logs_dir: Path
    database_path: Path
    settings_path: Path
    config_path: Path

    @classmethod
    def discover(cls) -> "ProjectPaths":
        if getattr(sys, "frozen", False):
            root = Path(sys.executable).resolve().parent
        else:
            root = Path(__file__).resolve().parents[2]
        data_dir = root / "data"
        captures_dir = data_dir / "captures"
        knowledge_dir = data_dir / "knowledge"
        logs_dir = data_dir / "logs"
        return cls(
            root=root,
            data_dir=data_dir,
            captures_dir=captures_dir,
            knowledge_dir=knowledge_dir,
            logs_dir=logs_dir,
            database_path=data_dir / "knowledge.db",
            settings_path=data_dir / "settings.json",
            config_path=root / "config.toml",
        )

    def ensure(self) -> None:
        self.data_dir.mkdir(exist_ok=True)
        self.captures_dir.mkdir(exist_ok=True)
        self.knowledge_dir.mkdir(exist_ok=True)
        self.logs_dir.mkdir(exist_ok=True)


class SettingsStore:
    def __init__(self, path: Path, config_path: Path | None = None) -> None:
        self.path = path
        self.config_path = config_path

    def load(self) -> AppSettings:
        settings = AppSettings()
        if self.path.exists():
            user_payload = json.loads(self.path.read_text(encoding="utf-8"))
            settings = AppSettings(**{**settings.to_dict(), **user_payload})
        project_config_path = self._resolve_project_config_path()
        if project_config_path is not None:
            settings = self._apply_project_config(settings, self._load_toml(project_config_path))
        if not settings.api_key.strip():
            settings = AppSettings(**{**settings.to_dict(), "api_key": self._load_codex_auth_key()})
        return settings

    def save(self, settings: AppSettings) -> None:
        self.path.write_text(
            json.dumps(settings.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _load_toml(path: Path) -> dict[str, Any]:
        with path.open("rb") as file:
            return tomllib.load(file)

    def _resolve_project_config_path(self) -> Path | None:
        if self.config_path is None:
            return None
        if self.config_path.exists():
            return self.config_path
        with_name = getattr(self.config_path, "with_name", None)
        if callable(with_name):
            example_path = with_name("config.example.toml")
            if example_path.exists():
                return example_path
        return None

    @staticmethod
    def _apply_project_config(settings: AppSettings, payload: dict[str, Any]) -> AppSettings:
        values = settings.to_dict()
        for key in (
            "model_provider",
            "model",
            "review_model",
            "model_reasoning_effort",
            "disable_response_storage",
            "network_access",
            "windows_wsl_setup_acknowledged",
            "model_context_window",
            "model_auto_compact_token_limit",
        ):
            if key in payload:
                values[key] = payload[key]

        provider_name = values.get("model_provider", "OpenAI")
        provider_config = payload.get("model_providers", {}).get(provider_name, {})
        if provider_config:
            values["model_provider"] = provider_config.get("name", provider_name)
            values["base_url"] = provider_config.get("base_url", values["base_url"])
            values["wire_api"] = provider_config.get("wire_api", values["wire_api"])
            values["requires_openai_auth"] = provider_config.get(
                "requires_openai_auth",
                values["requires_openai_auth"],
            )
        return AppSettings(**values)

    @staticmethod
    def _load_codex_auth_key() -> str:
        auth_path = Path.home() / ".codex" / "auth.json"
        if not auth_path.exists():
            return ""
        try:
            payload = json.loads(auth_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return ""
        return str(payload.get("OPENAI_API_KEY", "")).strip()
