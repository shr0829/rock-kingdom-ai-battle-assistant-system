from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ailock.pet_vision import PetCatalogStore, PetRecognitionSampleStore, PetVisionIndexStore  # noqa: E402
from scripts.fetch_rocom_wiki import PETS_URL, fetch_html, parse_pets  # noqa: E402

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AILockWikiArtworkImporter/1.0"
IMAGE_SUFFIX_BY_TYPE = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
}


@dataclass(frozen=True, slots=True)
class DownloadedWikiArtwork:
    name: str
    no: str
    source_url: str
    final_url: str
    local_path: Path
    image_bytes: bytes
    content_type: str


def normalize_mediawiki_original_url(url: str) -> str:
    """Return the original MediaWiki file URL for a thumbnail URL when possible."""
    parsed = urllib.parse.urlparse(url)
    marker = "/thumb/"
    if marker not in parsed.path:
        return url
    before, after = parsed.path.split(marker, 1)
    parts = after.split("/")
    if len(parts) < 4:
        return url
    original_path = before + "/" + "/".join(parts[:3])
    return urllib.parse.urlunparse(parsed._replace(path=original_path))


def safe_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" ._") or "pet"


def suffix_for(content_type: str, url: str) -> str:
    content_type = content_type.split(";", 1)[0].lower().strip()
    if content_type in IMAGE_SUFFIX_BY_TYPE:
        return IMAGE_SUFFIX_BY_TYPE[content_type]
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    return suffix if suffix in {".png", ".jpg", ".jpeg", ".webp"} else ".png"


def rename_creator_artworks(database_path: Path, artwork_root: Path) -> int:
    creator_dir = artwork_root / "creator"
    creator_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    renamed = 0
    try:
        rows = conn.execute(
            """
            SELECT a.id, a.name, a.local_path, a.pet_id, c.name AS catalog_name
            FROM pet_artworks a
            LEFT JOIN pet_catalog c ON c.id = a.pet_id
            WHERE a.source = 'rocom_creator_evolution_icon'
            ORDER BY a.id
            """
        ).fetchall()
        used_paths: set[Path] = set()
        for row in rows:
            old_path = Path(str(row["local_path"] or ""))
            pet_name = str(row["catalog_name"] or row["name"] or "").removesuffix("进化链").strip()
            if not pet_name:
                continue
            suffix = old_path.suffix.lower() if old_path.suffix else ".png"
            target_path = creator_dir / f"{safe_filename(pet_name)}{suffix}"
            new_path = target_path if target_path.exists() and not old_path.exists() else unique_path(target_path, used_paths)
            used_paths.add(new_path)
            if old_path.exists() and old_path.resolve() != new_path.resolve():
                new_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(old_path, new_path)
                try:
                    old_path.unlink()
                except PermissionError:
                    pass
                renamed += 1
            conn.execute(
                "UPDATE pet_artworks SET name = ?, local_path = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (pet_name, str(new_path), int(row["id"])),
            )
        conn.commit()
    finally:
        conn.close()
    return renamed


def unique_path(candidate: Path, used_paths: set[Path]) -> Path:
    if candidate not in used_paths and not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    for index in range(2, 1000):
        option = candidate.with_name(f"{stem}_{index}{suffix}")
        if option not in used_paths and not option.exists():
            return option
    raise RuntimeError(f"无法为文件生成唯一命名：{candidate}")


def fetch_image(name: str, no: str, image_url: str, wiki_dir: Path) -> DownloadedWikiArtwork:
    final_url = normalize_mediawiki_original_url(image_url)
    request = urllib.request.Request(
        final_url,
        headers={"User-Agent": USER_AGENT, "Referer": PETS_URL},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            image_bytes = response.read()
            content_type = str(response.headers.get("content-type") or "")
    except urllib.error.HTTPError:
        request = urllib.request.Request(
            image_url,
            headers={"User-Agent": USER_AGENT, "Referer": PETS_URL},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            image_bytes = response.read()
            content_type = str(response.headers.get("content-type") or "")
            final_url = image_url
    suffix = suffix_for(content_type, final_url)
    local_path = wiki_dir / f"{safe_filename(name)}{suffix}"
    local_path.write_bytes(image_bytes)
    return DownloadedWikiArtwork(
        name=name,
        no=no,
        source_url=image_url,
        final_url=final_url,
        local_path=local_path,
        image_bytes=image_bytes,
        content_type=content_type,
    )


def import_wiki_artworks(root: Path, workers: int = 16, limit: int | None = None) -> dict[str, int]:
    data_dir = root / "data"
    database_path = data_dir / "knowledge.db"
    artwork_root = data_dir / "pet_vision" / "artworks"
    wiki_dir = artwork_root / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)

    catalog = PetCatalogStore(database_path)
    sample_store = PetRecognitionSampleStore(database_path)
    renamed = rename_creator_artworks(database_path, artwork_root)

    pets = parse_pets(fetch_html(PETS_URL))
    pets = [pet for pet in pets if pet.image_url]
    if limit is not None:
        pets = pets[:limit]

    downloaded = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(fetch_image, pet.name, pet.no, pet.image_url, wiki_dir) for pet in pets]
        for future in as_completed(futures):
            try:
                item = future.result()
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"[WARN] wiki image download failed: {exc}")
                continue
            pet_id = catalog.upsert(name=item.name, no=item.no, aliases=[item.name], source="rocom_wiki")
            sample_store.upsert_artwork(
                pet_id=pet_id,
                name=item.name,
                source_url=item.final_url,
                local_path=str(item.local_path),
                image_bytes=item.image_bytes,
                content_type=item.content_type,
                source="rocom_wiki_pet_artwork",
            )
            downloaded += 1
            print(f"[OK] wiki {downloaded}/{len(pets)} {item.name} -> {item.local_path.name}")

    indexed = len(PetVisionIndexStore(data_dir, sample_store).rebuild_index())
    return {
        "wiki_listed": len(pets),
        "wiki_downloaded": downloaded,
        "wiki_failed": failed,
        "creator_renamed": renamed,
        "indexed_features": indexed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="下载 Biligame 精灵图鉴图片并规范本地立绘文件命名。")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    stats = import_wiki_artworks(args.root, workers=args.workers, limit=args.limit)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0 if stats["wiki_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
