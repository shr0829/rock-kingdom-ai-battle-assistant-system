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
from typing import Callable, Iterable
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
    race_total: str
    race_stats: dict[str, str]
    characteristics: list[dict[str, str]]
    skills: list[dict[str, str]]
    bloodline_skills: list[dict[str, str]]
    learnable_skills: list[dict[str, str]]
    filters: dict[str, str]
    source: str
    detail_error: str = ""


@dataclass(slots=True)
class SkillEntry:
    name: str
    page_url: str
    icon_url: str
    attribute_icon_url: str
    power: str
    energy: str
    category: str
    attribute: str
    effect: str
    learned_by_pets: list[dict[str, str]]
    filters: dict[str, str]
    source: str
    detail_error: str = ""


LINK_FIELD_NAMES = {
    "page_url",
    "image_url",
    "icon_url",
    "attribute_icon_url",
    "attribute_icons",
    "source",
}


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


def clean_text(fragment: str) -> str:
    fragment = re.sub(r"(?is)<script\b.*?</script>|<style\b.*?</style>", " ", fragment)
    fragment = re.sub(r"(?i)<br\s*/?>", "\n", fragment)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    text = html.unescape(fragment).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip(" \t\r\n:：")


def clean_effect(text: str) -> str:
    return clean_text(text).lstrip("✦").strip()


def attr_value(tag: str, name: str) -> str:
    match = re.search(rf'\b{re.escape(name)}="([^"]*)"', tag, re.I)
    return html.unescape(match.group(1)) if match else ""


def tag_has_class(tag: str, class_name: str) -> bool:
    classes = attr_value(tag, "class").split()
    return class_name in classes


def iter_tags(fragment: str, tag_name: str) -> Iterable[str]:
    yield from re.findall(rf"<{re.escape(tag_name)}\b[^>]*>", fragment, re.I)


def text_by_class(fragment: str, class_name: str) -> str:
    pattern = (
        rf'<(?P<tag>[A-Za-z0-9]+)\b[^>]*class="[^"]*\b{re.escape(class_name)}\b[^"]*"[^>]*>'
        rf"(?P<body>.*?)</(?P=tag)>"
    )
    match = re.search(pattern, fragment, re.S | re.I)
    return clean_text(match.group("body")) if match else ""


def normalize_attribute(attribute: str) -> str:
    attribute = clean_text(attribute)
    return attribute[:-1] if attribute.endswith("系") else attribute


def icon_label_from_alt(alt: str) -> str:
    alt = re.sub(r"\.(png|jpg|jpeg|webp|bmp)$", "", html.unescape(alt), flags=re.I)
    parts = [part for part in re.split(r"[\s_]+", alt) if part]
    return parts[-1] if parts else ""


def img_label_by_class(fragment: str, class_name: str) -> str:
    for tag in iter_tags(fragment, "img"):
        if tag_has_class(tag, class_name):
            return icon_label_from_alt(attr_value(tag, "alt"))
    return ""


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
    for tag in iter_tags(segment, "img"):
        if tag_has_class(tag, class_name):
            return urljoin(BASE_URL, attr_value(tag, "src"))
    return ""


def images_by_class(segment: str, class_name: str) -> list[str]:
    return [
        urljoin(BASE_URL, attr_value(tag, "src"))
        for tag in iter_tags(segment, "img")
        if tag_has_class(tag, class_name) and attr_value(tag, "src")
    ]


def parse_race_total(page_html: str) -> str:
    match = re.search(r"种族值\s*</p>\s*<p>\s*([^<]+)\s*</p>", page_html)
    return clean_text(match.group(1)) if match else ""


def parse_race_stats(page_html: str) -> dict[str, str]:
    stats: dict[str, str] = {}
    block_match = re.search(
        r'<div\b[^>]*class="[^"]*\brocom_sprite_info_qualification\b[^"]*"[^>]*>(.*?)'
        r'<div\b[^>]*class="[^"]*\brocom_sprite_info_distribution\b',
        page_html,
        re.S | re.I,
    )
    block = block_match.group(1) if block_match else page_html
    for item in re.findall(r"<li\b[^>]*>(.*?)</li>", block, re.S | re.I):
        name = text_by_class(item, "rocom_sprite_info_qualification_name")
        value = text_by_class(item, "rocom_sprite_info_qualification_value")
        if name and value:
            stats[name] = value
    return stats


def parse_characteristics(page_html: str) -> list[dict[str, str]]:
    titles = re.findall(
        r'<p\b[^>]*class="[^"]*\brocom_sprite_info_characteristic_title\b[^"]*"[^>]*>(.*?)</p>',
        page_html,
        re.S | re.I,
    )
    effects = re.findall(
        r'<p\b[^>]*class="[^"]*\brocom_sprite_info_characteristic_text\b[^"]*"[^>]*>(.*?)</p>',
        page_html,
        re.S | re.I,
    )
    traits: list[dict[str, str]] = []
    for index, raw_name in enumerate(titles):
        name = clean_text(raw_name)
        effect = clean_effect(effects[index]) if index < len(effects) else ""
        if name or effect:
            traits.append({"name": name, "effect": effect})
    return dedupe_by_key(traits, lambda item: item.get("name", "") or item.get("effect", ""))


def parse_pet_skill_box(box: str) -> dict[str, str]:
    link = re.search(r'<a\s+href="([^"]+)"\s+title="([^"]+)"', box)
    name = text_by_class(box, "rocom_sprite_skillName")
    page_url = urljoin(BASE_URL, html.unescape(link.group(1))) if link else ""
    link_title = html.unescape(link.group(2)) if link else ""
    icon_url = ""
    if link:
        link_fragment = box[link.start() :]
        icon_match = re.search(r"<img\b[^>]*src=\"([^\"]+)\"", link_fragment, re.I)
        if icon_match:
            icon_url = urljoin(BASE_URL, html.unescape(icon_match.group(1)))
    return {
        "level": clean_text(text_by_class(box, "rocom_sprite_skill_level")),
        "name": name or link_title,
        "page_url": page_url,
        "icon_url": icon_url,
        "attribute": normalize_attribute(img_label_by_class(box, "rocom_sprite_skill_attr")),
        "energy": text_by_class(box, "rocom_sprite_skillDamage"),
        "category": text_by_class(box, "rocom_sprite_skillType"),
        "power": text_by_class(box, "rocom_sprite_skill_power"),
        "effect": clean_effect(text_by_class(box, "rocom_sprite_skillContent")),
    }


def parse_pet_skill_boxes(segment: str) -> list[dict[str, str]]:
    starts = list(
        re.finditer(r'<div\b[^>]*class="[^"]*\brocom_sprite_skill_box\b[^"]*"[^>]*>', segment, re.I)
    )
    skills: list[dict[str, str]] = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(segment)
        skill = parse_pet_skill_box(segment[match.start() : end])
        if skill["name"]:
            skills.append(skill)
    return dedupe_by_key(skills, lambda item: "|".join([item.get("level", ""), item.get("name", "")]))


def parse_pet_skill_tabs(page_html: str) -> dict[str, list[dict[str, str]]]:
    tabs = [
        (match, attr_value(match.group(0), "title"))
        for match in re.finditer(r'<div\b[^>]*class="[^"]*\btabbertab\b[^"]*"[^>]*>', page_html, re.I)
    ]
    result = {"skills": [], "bloodline_skills": [], "learnable_skills": []}
    for index, (match, title) in enumerate(tabs):
        end = tabs[index + 1][0].start() if index + 1 < len(tabs) else len(page_html)
        skills = parse_pet_skill_boxes(page_html[match.start() : end])
        if not skills:
            continue
        if "血脉" in title:
            result["bloodline_skills"].extend(skills)
        elif "可学" in title or "技能石" in title:
            result["learnable_skills"].extend(skills)
        elif "技能" in title:
            result["skills"].extend(skills)
    return result


def parse_pet_detail(page_html: str) -> dict[str, object]:
    tabs = parse_pet_skill_tabs(page_html)
    return {
        "race_total": parse_race_total(page_html),
        "race_stats": parse_race_stats(page_html),
        "characteristics": parse_characteristics(page_html),
        **tabs,
    }


def parse_can_learn_pets(page_html: str) -> list[dict[str, str]]:
    block_match = re.search(
        r'<div\b[^>]*class="[^"]*\brocom_canlearn_box\b[^"]*"[^>]*>(.*?)(?:<div\b[^>]*class="[^"]*\bfooter\b|$)',
        page_html,
        re.S | re.I,
    )
    block = block_match.group(1) if block_match else ""
    pets: list[dict[str, str]] = []
    matches = list(
        re.finditer(
            r'<div\b[^>]*class="[^"]*\brocom_canlearn_img_box\b[^"]*"[^>]*>\s*'
            r'<a\s+href="([^"]+)"\s+title="([^"]+)"[^>]*>',
            block,
            re.S | re.I,
        )
    ) or list(re.finditer(r'<a\s+href="([^"]+)"\s+title="([^"]+)"[^>]*>', block))
    for match in matches:
        pets.append(
            {
                "name": html.unescape(match.group(2)),
                "page_url": urljoin(BASE_URL, html.unescape(match.group(1))),
            }
        )
    return dedupe_by_key(pets, lambda item: item["page_url"] or item["name"])


def parse_skill_detail(page_html: str) -> dict[str, object]:
    power_match = re.search(
        r'<div\b[^>]*class="[^"]*\brocom_skill_template_skillPower\b[^"]*"[^>]*>.*?'
        r"<b\b[^>]*>(.*?)</b>",
        page_html,
        re.S | re.I,
    )
    attribute = normalize_attribute(text_by_class(page_html, "rocom_skill_template_skillAttribute"))
    return {
        "power": clean_text(power_match.group(1)) if power_match else "",
        "energy": text_by_class(page_html, "rocom_skill_template_skillConsume_box"),
        "category": text_by_class(page_html, "rocom_skill_template_skillSort"),
        "attribute": attribute,
        "effect": clean_effect(text_by_class(page_html, "rocom_skill_template_skillEffect")),
        "learned_by_pets": parse_can_learn_pets(page_html),
    }


def enrich_entries(
    entries,
    parser: Callable[[str], dict[str, object]],
    *,
    limit: int,
    sleep_seconds: float,
) -> None:
    selected = entries if limit <= 0 else entries[:limit]
    for index, entry in enumerate(selected, start=1):
        try:
            details = parser(fetch_html(entry.page_url))
            for key, value in details.items():
                if value:
                    setattr(entry, key, value)
        except Exception as exc:  # pragma: no cover - network/site failures are recorded in data.
            entry.detail_error = f"{type(exc).__name__}: {exc}"
        if sleep_seconds > 0 and index < len(selected):
            time.sleep(sleep_seconds)


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
            race_total="",
            race_stats={},
            characteristics=[],
            skills=[],
            bloodline_skills=[],
            learnable_skills=[],
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
            energy="",
            category=attrs.get("data-param1", ""),
            attribute=attrs.get("data-param2", ""),
            effect="",
            learned_by_pets=[],
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


def unique_nonempty(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _strip_links(value):
    if isinstance(value, dict):
        return {
            key: _strip_links(item)
            for key, item in value.items()
            if key not in LINK_FIELD_NAMES
        }
    if isinstance(value, list):
        return [_strip_links(item) for item in value]
    return value


def serialize_entry(entry) -> dict[str, object]:
    data = asdict(entry)
    data.pop("filters", None)
    if not data.get("detail_error"):
        data.pop("detail_error", None)
    return _strip_links(data)


def write_json(path: Path, entries) -> None:
    path.write_text(
        json.dumps([serialize_entry(entry) for entry in entries], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_csv(path: Path, entries) -> None:
    rows = [serialize_entry(entry) for entry in entries]
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
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
            race_stats = "，".join(f"{name}{value}" for name, value in pet.race_stats.items())
            trait_names = unique_nonempty(item["name"] for item in pet.characteristics if item.get("name"))
            trait_effects = unique_nonempty(item["effect"] for item in pet.characteristics if item.get("effect"))
            skill_names = unique_nonempty(skill["name"] for skill in pet.skills if skill.get("name"))
            bloodline_names = unique_nonempty(skill["name"] for skill in pet.bloodline_skills if skill.get("name"))
            learnable_names = unique_nonempty(skill["name"] for skill in pet.learnable_skills if skill.get("name"))
            content = (
                f"宠物编号: {pet.no}; 名称: {pet.name}; 阶段: {pet.stage}; "
                f"属性: {'/'.join(x for x in [pet.primary_attribute, pet.secondary_attribute] if x)}; "
                f"形态: {pet.origin_form} / {pet.display_form}; 种族值: {pet.race_total}; "
                f"特性: {'、'.join(trait_names)}; 特性效果: {'；'.join(trait_effects[:4])}; "
                f"种族分项: {race_stats}; 精灵技能: {'、'.join(skill_names[:24])}; "
                f"血脉技能: {'、'.join(bloodline_names[:16])}; 可学技能石: {'、'.join(learnable_names[:16])}; "
                f"限时标记: {pet.limited}"
            )
            keywords = [
                pet.name,
                pet.no,
                pet.primary_attribute,
                pet.secondary_attribute,
                pet.stage,
                *trait_names,
                *skill_names,
                *bloodline_names,
                *learnable_names,
            ]
            upsert_document(connection, f"rocom_pet::{pet.name}", "rocom_pet", pet.name, content, keywords)
        for skill in skills:
            learned_by_names = unique_nonempty(pet["name"] for pet in skill.learned_by_pets if pet.get("name"))
            content = (
                f"技能名称: {skill.name}; 属性: {skill.attribute}; 类型: {skill.category}; "
                f"耗能: {skill.energy}; 威力/伤害: {skill.power}; 效果: {skill.effect}; "
                f"可学习精灵: {'、'.join(learned_by_names[:32])}"
            )
            keywords = [skill.name, skill.attribute, skill.category, skill.power, skill.energy, *learned_by_names]
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
    parser.add_argument(
        "--skip-detail-pages",
        action="store_true",
        help="Only parse encyclopedia index cards; skip per-pet/per-skill detail pages.",
    )
    parser.add_argument(
        "--detail-limit",
        type=int,
        default=0,
        help="Limit per-type detail page fetches for smoke tests; 0 means all entries.",
    )
    parser.add_argument(
        "--detail-sleep",
        type=float,
        default=0.2,
        help="Seconds to sleep between detail page requests.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pets_html = fetch_html(PETS_URL)
    time.sleep(1)
    skills_html = fetch_html(SKILLS_URL)

    pets = parse_pets(pets_html)
    skills = parse_skills(skills_html)
    detail_pages_enabled = not args.skip_detail_pages

    if detail_pages_enabled:
        enrich_entries(pets, parse_pet_detail, limit=args.detail_limit, sleep_seconds=args.detail_sleep)
        enrich_entries(skills, parse_skill_detail, limit=args.detail_limit, sleep_seconds=args.detail_sleep)

    write_json(output_dir / "pets.json", pets)
    write_csv(output_dir / "pets.csv", pets)
    write_json(output_dir / "skills.json", skills)
    write_csv(output_dir / "skills.csv", skills)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_site": "BiliGame Wiki / 洛克王国 Wiki",
        "counts": {"pets": len(pets), "skills": len(skills)},
        "detail_pages_enabled": detail_pages_enabled,
        "detail_limit": args.detail_limit,
        "notes": (
            "Factual encyclopedia card/detail data parsed for pet race values, pet characteristics, "
            "pet skill tabs, and skill attribute/category/energy/power/effect plus learnable-pet lists; "
            "export files intentionally omit page/image links and do not copy article prose."
        ),
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.skip_db:
        upsert_knowledge_db(Path(args.knowledge_db), pets, skills)

    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
