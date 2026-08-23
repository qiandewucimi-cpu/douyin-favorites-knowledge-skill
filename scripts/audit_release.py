#!/usr/bin/env python3
"""Fail when a release tree is incomplete or appears to contain private data."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

REQUIRED = {
    "SKILL.md",
    "README.md",
    "LICENSE",
    "requirements.txt",
    "agents/openai.yaml",
    "scripts/pipeline.py",
    "references/pipeline.md",
    "references/note-schema.md",
}
FORBIDDEN_NAMES = {
    ".cookies.json",
    "config.yml",
    "cookies.json",
    "state.sqlite3",
    "dy_downloader.db",
}
FORBIDDEN_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".wav", ".mp3", ".sqlite", ".sqlite3", ".db", ".pyc"}
FORBIDDEN_DIR_NAMES = {".pytest_cache", ".ruff_cache", "__pycache__"}
SECRET_PATTERNS = (
    re.compile(r"(?i)['\"]?(?:sessionid|sid_guard|passport_csrf_token|msToken)['\"]?\s*[:=]\s*['\"]?[A-Za-z0-9%._-]{16,}"),
    re.compile(r"(?i)['\"]?(?:authorization|api[_-]?key)['\"]?\s*[:=]\s*['\"]?(?!\[REDACTED\])[A-Za-z0-9._-]{16,}"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,})\b"),
    re.compile(r"(?i)[A-Z]:\\Users\\[^\\\s]+"),
)


def audit(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    files = [path for path in root.rglob("*") if path.is_file() and ".git" not in path.parts]
    relative = {path.relative_to(root).as_posix() for path in files}
    for required in sorted(REQUIRED - relative):
        errors.append(f"required file is missing: {required}")
    for path in files:
        rel = path.relative_to(root).as_posix()
        if any(part in FORBIDDEN_DIR_NAMES for part in path.relative_to(root).parts):
            errors.append(f"generated cache file is present: {rel}")
            continue
        if path.name in FORBIDDEN_NAMES:
            errors.append(f"private runtime file is present: {rel}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"generated media/database file is present: {rel}")
        if path.stat().st_size > 2 * 1024 * 1024:
            errors.append(f"unexpected file larger than 2 MiB: {rel}")
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(f"possible secret or personal path in: {rel}")
                break
    skill_md = root / "SKILL.md"
    if skill_md.is_file():
        skill_text = skill_md.read_text(encoding="utf-8")
        frontmatter = skill_text.split("---", 2)
        if len(frontmatter) < 3:
            errors.append("SKILL.md has no YAML frontmatter")
        else:
            header = frontmatter[1]
            if not re.search(r"(?m)^name:\s*ingest-douyin-favorites\s*$", header):
                errors.append("SKILL.md has an unexpected or missing name")
            if not re.search(r"(?m)^description:\s*\S", header):
                errors.append("SKILL.md has no description")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    errors = audit(args.root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 2
    print(f"Release audit passed: {args.root.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
