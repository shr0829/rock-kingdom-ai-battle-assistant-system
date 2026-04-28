from __future__ import annotations

import re
import sys
from pathlib import Path


CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")
SKIP_PREFIXES = ("Merge ", "Revert ", "fixup!", "squash!")
REQUIRED_TRAILERS = (
    "约束",
    "备选方案",
    "信心",
    "风险范围",
    "提醒",
    "已验证",
    "未验证",
)
PLACEHOLDER_MARKERS = (
    "<一句话说明本次提交的意图>",
    "<补充说明：问题背景、修改思路、影响范围、为什么这样做。>",
)


def _meaningful_lines(text: str) -> list[str]:
    lines = [line.rstrip() for line in text.splitlines() if not line.lstrip().startswith("#")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def validate_commit_message_text(text: str) -> list[str]:
    lines = _meaningful_lines(text)
    if not lines:
        return ["提交说明不能为空。"]

    subject = lines[0].strip()
    if subject.startswith(SKIP_PREFIXES):
        return []

    errors: list[str] = []

    if any(marker == subject for marker in PLACEHOLDER_MARKERS):
        errors.append("首行仍是模板占位符，请改成“为什么要改”。")

    if not CHINESE_RE.search(subject):
        errors.append("首行需要默认使用中文，直接说明本次提交的意图。")

    remainder = lines[1:]
    trailer_index_by_name: dict[str, int] = {}
    for index, line in enumerate(remainder):
        stripped = line.strip()
        for trailer in REQUIRED_TRAILERS:
            prefix = f"{trailer}:"
            if stripped.startswith(prefix):
                trailer_index_by_name.setdefault(trailer, index)
                if not stripped[len(prefix) :].strip():
                    errors.append(f"“{trailer}:” 后面需要填写内容。")

    missing_trailers = [trailer for trailer in REQUIRED_TRAILERS if trailer not in trailer_index_by_name]
    if missing_trailers:
        errors.append(f"缺少必填尾注：{', '.join(missing_trailers)}。")

    if trailer_index_by_name:
        first_trailer_index = min(trailer_index_by_name.values())
        body_lines = [line for line in remainder[:first_trailer_index] if line.strip()]
        if not body_lines:
            errors.append("首行下面需要补充背景说明，解释为什么这样改。")
    else:
        if not [line for line in remainder if line.strip()]:
            errors.append("提交说明缺少正文与尾注。")

    return errors


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    if len(args) != 1:
        print("用法: python scripts/validate_commit_message.py <commit-message-file>", file=sys.stderr)
        return 2

    message_path = Path(args[0])
    errors = validate_commit_message_text(message_path.read_text(encoding="utf-8"))
    if not errors:
        return 0

    print("提交信息不符合仓库约定：", file=sys.stderr)
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    print("", file=sys.stderr)
    print("请按 .gitmessage-zh-CN.txt 模板填写：", file=sys.stderr)
    print("1. 第一行写“为什么要改”；", file=sys.stderr)
    print("2. 正文写背景、取舍、风险和验证；", file=sys.stderr)
    print("3. 默认使用中文。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
