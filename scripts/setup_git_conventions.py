from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_git_config(*args: str) -> None:
    subprocess.run(
        ["git", "config", "--local", *args],
        cwd=REPO_ROOT,
        check=True,
    )


def main() -> None:
    run_git_config("commit.template", str(REPO_ROOT / ".gitmessage-zh-CN.txt"))
    run_git_config("core.hooksPath", str(REPO_ROOT / ".githooks"))
    run_git_config("i18n.commitEncoding", "utf-8")
    run_git_config("i18n.logOutputEncoding", "utf-8")

    print("已启用中文 commit 模板与校验：")
    print(f"- commit.template = {REPO_ROOT / '.gitmessage-zh-CN.txt'}")
    print(f"- core.hooksPath = {REPO_ROOT / '.githooks'}")
    print("- i18n.commitEncoding = utf-8")
    print("- i18n.logOutputEncoding = utf-8")


if __name__ == "__main__":
    main()
