from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin
from urllib.request import Request, urlopen


BASE_URL = "https://wiki.biligame.com"
PETS_URL = "https://wiki.biligame.com/rocom/%E7%B2%BE%E7%81%B5%E5%9B%BE%E9%89%B4"
SKILLS_URL = "https://wiki.biligame.com/rocom/%E6%8A%80%E8%83%BD%E5%9B%BE%E9%89%B4"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/124 Safari/537.36 AILockLocalDataImporter/1.0"
)


@dataclass(slots=True)
class PetEntry:
    no: str
    name: str
    page_url: str
    image_url: str
    attribute_icons: list[str]
    stage: str
    primary_attribute: str
    secondary_attribute: str
    origin_form: str
    display_form: str
    limited: str
    filters: dict[str, str]
    source: str


@dataclass(slots=True)
class SkillEntry:
    name: str
    page_url: str
    icon_url: str
    attribute_icon_url: str
    power: str
    category: str
    attribute: str
    filters: dict[str, str]
    source: str


def fetch_html(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": "https://wiki.biligame.com/rocom/%E9%A6%96%E9%A1%B5",
        },
    )
    with urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", "replace")


def parse_data_attrs(start_tag: str) -> dict[str, str]:
    return {
        key: html.unescape(value)
        for key, value in re.findall(r'(data-param\d+|data-reverse)="([^"]*)"', start_tag)
    }


def divsort_segments(page_html: str) -> Iterable[tuple[dict[str, str], str]]:
    starts = list(re.finditer(r'<div class="divsort"([^>]*)>', page_html))
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(page_html)
        yield parse_data_attrs(match.group(1)), page_html[match.start() : end]


def first_title_link(segment: str) -> tuple[str, str]:
    match = re.search(r'<a\s+href="([^"]+)"\s+title="([^"]+)"', segment)
    if not match:
        return "", ""
    return urljoin(BASE_URL, match.group(1)), html.unescape(match.group(2))


def image_by_class(segment: str, class_name: str) -> str:
    pattern = rf'<img\s+[^>]*src="([^"]+)"[^>]*class="[^"]*\b{re.escape(class_name)}\b[^"]*"'
    match = re.search(pattern, segment)
    return html.unescape(match.group(1)) if match else ""


def images_by_class(segment: str, class_name: str) -> list[str]:
    pattern = rf'<img\s+[^>]*src="([^"]+)"[^>]*class="[^"]*\b{re.escape(class_name)}\b[^"]*"'
    return [html.unescape(match) for match in re.findall(pattern, segment)]


def parse_pets(page_html: str) -> list[PetEntry]:
    pets: list[PetEntry] = []
    for attrs, segment in divsort_segments(page_html):
        page_url, name = first_title_link(segment)
        no_match = re.search(r"NO\.\d+", segment)
        if not page_url or not name or not no_match:
            continue
        pet = PetEntry(
            no=no_match.group(0),
            name=name,
            page_url=page_url,
            image_url=image_by_class(segment, "rocom_prop_icon"),
            attribute_icons=images_by_class(segment, "rocom_pet_icon"),
            stage=attrs.get("data-param1", ""),
            primary_attribute=attrs.get("data-param2", ""),
            secondary_attribute=attrs.get("data-param3", ""),
            origin_form=attrs.get("data-param4", ""),
            display_form=attrs.get("data-param5", ""),
            limited=attrs.get("data-param6", ""),
            filters=attrs,
            source=PETS_URL,
        )
        pets.append(pet)
    return dedupe_by_key(pets, lambda item: item.page_url or item.name)


def parse_skills(page_html: str) -> list[SkillEntry]:
    skills: list[SkillEntry] = []
    for attrs, segment in divsort_segments(page_html):
        page_url, name = first_title_link(segment)
        if not page_url or not name:
            continue
        skill = SkillEntry(
            name=name,
            page_url=page_url,
            icon_url=image_by_class(segment, "rocom_skill_bg_img"),
            attribute_icon_url=image_by_class(segment, "rocom_skill_attribute_icon"),
            power=attrs.get("data-param0", ""),
            category=attrs.get("data-param1", ""),
            attribute=attrs.get("data-param2", ""),
            filters=attrs,
            source=SKILLS_URL,
        )
        skills.append(skill)
    return dedupe_by_key(skills, lambda item: item.name)


def dedupe_by_key(entries, key_func):
    seen: set[str] = set()
    output = []
    for entry in entries:
        key = key_func(entry)
        if key in seen:
            continue
        seen.add(key)
        output.append(entry)
    return output


def write_json(path: Path, entries) -> None:
    path.write_text(
        json.dumps([asdict(entry) for entry in entries], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_csv(path: Path, entries) -> None:
    rows = [asdict(entry) for entry in entries]
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
                    for key, value in row.items()
                }
            )


def upsert_knowledge_db(database_path: Path, pets: list[PetEntry], skills: list[SkillEntry]) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_path TEXT NOT NULL UNIQUE,
                source_type TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                keywords TEXT NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        for pet in pets:
            content = (
                f"宠物编号: {pet.no}; 名称: {pet.name}; 阶段: {pet.stage}; "
                f"属性: {'/'.join(x for x in [pet.primary_attribute, pet.secondary_attribute] if x)}; "
                f"形态: {pet.origin_form} / {pet.display_form}; 页面: {pet.page_url}"
            )
            keywords = [pet.name, pet.no, pet.primary_attribute, pet.secondary_attribute, pet.stage]
            upsert_document(connection, f"rocom_pet::{pet.name}", "rocom_pet", pet.name, content, keywords)
        for skill in skills:
            content = (
                f"技能名称: {skill.name}; 属性: {skill.attribute}; 类型: {skill.category}; "
                f"威力: {skill.power}; 页面: {skill.page_url}"
            )
            keywords = [skill.name, skill.attribute, skill.category, skill.power]
            upsert_document(connection, f"rocom_skill::{skill.name}", "rocom_skill", skill.name, content, keywords)
        connection.commit()
    finally:
        connection.close()


def upsert_document(
    connection: sqlite3.Connection,
    source_path: str,
    source_type: str,
    title: str,
    content: str,
    keywords: list[str],
) -> None:
    connection.execute(
        """
        INSERT INTO documents (source_path, source_type, title, content, keywords, updated_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(source_path) DO UPDATE SET
            source_type=excluded.source_type,
            title=excluded.title,
            content=excluded.content,
            keywords=excluded.keywords,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            source_path,
            source_type,
            title,
            content,
            json.dumps([keyword for keyword in keywords if keyword], ensure_ascii=False),
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Rock Kingdom encyclopedia data from BiliGame Wiki.")
    parser.add_argument("--output-dir", default="data/rocom_wiki", help="Output directory for JSON/CSV files.")
    parser.add_argument("--knowledge-db", default="data/knowledge.db", help="SQLite knowledge DB to upsert.")
    parser.add_argument("--skip-db", action="store_true", help="Only write JSON/CSV files; do not upsert knowledge DB.")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pets_html = fetch_html(PETS_URL)
    time.sleep(1)
    skills_html = fetch_html(SKILLS_URL)

    pets = parse_pets(pets_html)
    skills = parse_skills(skills_html)

    write_json(output_dir / "pets.json", pets)
    write_csv(output_dir / "pets.csv", pets)
    write_json(output_dir / "skills.json", skills)
    write_csv(output_dir / "skills.csv", skills)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {"pets": PETS_URL, "skills": SKILLS_URL},
        "counts": {"pets": len(pets), "skills": len(skills)},
        "notes": "Factual list data parsed from encyclopedia index cards; no article prose is copied.",
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.skip_db:
        upsert_knowledge_db(Path(args.knowledge_db), pets, skills)

    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
