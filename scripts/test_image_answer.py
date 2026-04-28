from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from ailock.config import ProjectPaths, SettingsStore
from ailock.knowledge import KnowledgeStore
from ailock.llm_client import MultimodalClient


def _load_api_key() -> str:
    env_key = os.getenv("OPENAI_API_KEY", "").strip()
    if env_key:
        return env_key

    auth_path = Path.home() / ".codex" / "auth.json"
    if auth_path.exists():
        try:
            payload = json.loads(auth_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return ""
        return str(payload.get("OPENAI_API_KEY", "")).strip()
    return ""


def _resolve_image_path(paths: ProjectPaths, requested: str | None) -> Path:
    if requested:
        path = Path(requested).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {path}")
        return path

    captures = sorted(paths.captures_dir.glob("*.png"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not captures:
        raise FileNotFoundError("No PNG screenshots found under data/captures")
    return captures[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Test image answering / battle-state extraction without strict schema.")
    parser.add_argument("--image", help="Optional image path. Defaults to the latest PNG in data/captures.")
    parser.add_argument(
        "--mode",
        choices=("raw", "battle-state", "full-flow"),
        default="battle-state",
        help="raw=print plain image answer, battle-state=run screenshot extraction, full-flow=extraction + knowledge search + advice",
    )
    parser.add_argument(
        "--prompt",
        default="请直接看图并用中文回答：先描述你能明确看见的战局信息，再给出一个当前回合建议，不要输出 JSON。",
        help="Prompt to send alongside the image.",
    )
    args = parser.parse_args()

    paths = ProjectPaths.discover()
    settings = SettingsStore(paths.settings_path, paths.config_path).load()
    if not settings.api_key.strip():
        settings.api_key = _load_api_key()
    client = MultimodalClient(settings)

    image_path = _resolve_image_path(paths, args.image)
    print(f"IMAGE={image_path}")
    image_bytes = image_path.read_bytes()

    if args.mode == "raw":
        answer = client.answer_image(
            prompt=args.prompt,
            image_bytes=image_bytes,
            mime_type=client._guess_mime_type(image_path),
        )
        print("ANSWER_START")
        print(answer)
        print("ANSWER_END")
        return 0

    battle_state = client.describe_battle_state(image_bytes)
    print("BATTLE_STATE_START")
    print(json.dumps(battle_state.to_dict(), ensure_ascii=False, indent=2))
    print("BATTLE_STATE_END")

    if args.mode == "full-flow":
        knowledge_store = KnowledgeStore(paths.database_path)
        hits = knowledge_store.search(battle_state.to_query(), limit=settings.max_knowledge_hits)
        advice = client.generate_advice(battle_state, hits)
        print("ADVICE_START")
        print(json.dumps(advice.to_dict(), ensure_ascii=False, indent=2))
        print("ADVICE_END")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
