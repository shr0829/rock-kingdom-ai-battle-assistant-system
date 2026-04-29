from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from ailock.pet_vision import PetCatalogStore, PetRecognitionSampleStore, PetVisionIndexStore  # noqa: E402

LIST_URL = "https://morefun.game.qq.com/rocom/280PI4UQ/search?X-Mcube-Act-Id=280PI4UQ&open_id=8484835307887669799"
REFERER = "https://rocom.qq.com/act/a20250719icreate/images.html"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


@dataclass(frozen=True, slots=True)
class EvolutionArtwork:
    item_id: int
    name: str
    icon_url: str
    keywords: list[str]
    file_name: str


def fetch_evolution_list() -> list[EvolutionArtwork]:
    body = urllib.parse.urlencode({"keyword": "", "type": "evolution"}).encode("utf-8")
    request = urllib.request.Request(
        LIST_URL,
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": REFERER,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if int(payload.get("code", 0)) != 0:
        raise RuntimeError(f"精灵立绘列表接口返回失败：{payload}")
    items = payload.get("data", payload if isinstance(payload, list) else [])
    artworks: list[EvolutionArtwork] = []
    for item in items:
        icon_url = str(item.get("icon", "")).strip()
        name = str(item.get("name", "")).strip()
        if not icon_url or not name:
            continue
        try:
            file_info = json.loads(str(item.get("fileInfo") or "{}"))
        except json.JSONDecodeError:
            file_info = {}
        keywords = [part.strip() for part in str(item.get("keywords", "")).split(",") if part.strip()]
        artworks.append(
            EvolutionArtwork(
                item_id=int(item.get("id") or 0),
                name=name,
                icon_url=icon_url,
                keywords=keywords,
                file_name=str(file_info.get("name") or f"{name}.png"),
            )
        )
    return artworks


def download_one(artwork: EvolutionArtwork, output_dir: Path) -> tuple[EvolutionArtwork, bytes, Path, str]:
    request = urllib.request.Request(
        artwork.icon_url,
        headers={"User-Agent": USER_AGENT, "Referer": REFERER},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        image_bytes = response.read()
        content_type = str(response.headers.get("content-type") or "")
    suffix = _suffix_from_content_type(content_type) or Path(urllib.parse.urlparse(artwork.icon_url).path).suffix or ".png"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{_safe_filename(artwork.name)}-{artwork.item_id}{suffix}"
    output_path.write_bytes(image_bytes)
    return artwork, image_bytes, output_path, content_type


def import_artworks(root: Path, workers: int = 12, limit: int | None = None) -> dict[str, int]:
    data_dir = root / "data"
    database_path = data_dir / "knowledge.db"
    catalog = PetCatalogStore(database_path)
    sample_store = PetRecognitionSampleStore(database_path)
    catalog.ensure_from_defaults(data_dir)
    artworks = fetch_evolution_list()
    if limit is not None:
        artworks = artworks[:limit]
    output_dir = data_dir / "pet_vision" / "artworks"
    downloaded = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(download_one, artwork, output_dir) for artwork in artworks]
        for future in as_completed(futures):
            try:
                artwork, image_bytes, output_path, content_type = future.result()
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"[WARN] 下载失败：{exc}")
                continue
            pet_id = _upsert_catalog_for_artwork(catalog, artwork)
            sample_store.upsert_artwork(
                pet_id=pet_id,
                name=artwork.name,
                source_url=artwork.icon_url,
                local_path=str(output_path),
                image_bytes=image_bytes,
                content_type=content_type,
                source="rocom_creator_evolution_icon",
            )
            downloaded += 1
            print(f"[OK] {downloaded}/{len(artworks)} {artwork.name} -> {output_path}")
    PetVisionIndexStore(data_dir, sample_store).rebuild_index()
    return {"listed": len(artworks), "downloaded": downloaded, "failed": failed}


def _upsert_catalog_for_artwork(catalog: PetCatalogStore, artwork: EvolutionArtwork) -> int | None:
    primary_name = artwork.keywords[0] if artwork.keywords else artwork.name.removesuffix("进化链")
    if not primary_name:
        return None
    existing = catalog.find_by_name(primary_name)
    aliases = [*artwork.keywords, artwork.name, artwork.file_name]
    if existing is not None:
        catalog.upsert(name=existing.name, aliases=[*existing.aliases, *aliases], source=existing.source or "rocom_creator")
        return existing.id
    return catalog.upsert(name=primary_name, aliases=aliases, source="rocom_creator")


def _suffix_from_content_type(content_type: str) -> str:
    if "png" in content_type:
        return ".png"
    if "jpeg" in content_type or "jpg" in content_type:
        return ".jpg"
    if "webp" in content_type:
        return ".webp"
    return ""


def _safe_filename(value: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value).strip(" ._") or "pet-artwork"


def main() -> int:
    parser = argparse.ArgumentParser(description="并行下载洛克王国创作者社区精灵立绘缩略图并写入 SQLite。")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    stats = import_artworks(args.root, workers=args.workers, limit=args.limit)
    print(json.dumps(stats, ensure_ascii=False))
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
