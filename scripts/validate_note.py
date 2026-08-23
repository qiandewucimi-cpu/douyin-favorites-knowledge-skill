#!/usr/bin/env python3
"""Validate a completed Douyin Markdown knowledge-note bundle."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REQUIRED_FRONTMATTER = (
    "title",
    "source",
    "source_url",
    "aweme_id",
    "author",
    "favorite_folder",
    "published_at",
    "processed_at",
    "tags",
    "confidence",
)
REQUIRED_HEADINGS = (
    "# 一句话摘要",
    "## 核心观点",
    "## 方法与步骤",
    "## 画面中的重要信息",
    "## 案例、数据与原话",
    "## 可执行行动",
    "## 待验证与不确定内容",
    "## 时间轴证据",
    "## 来源",
)


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    parts = text.split("\n---\n", 1)
    if len(parts) != 2:
        return {}
    values: dict[str, str] = {}
    for line in parts[0].splitlines()[1:]:
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", line)
        if match:
            values[match.group(1)] = match.group(2).strip().strip('"\'')
    return values


def validate_note_bundle(
    note_dir: Path,
    expected_aweme_id: str | None = None,
    expected_source_url: str | None = None,
) -> list[str]:
    note_dir = note_dir.resolve()
    note = note_dir / "note.md"
    transcript = note_dir / "transcript.md"
    evidence_path = note_dir / "visual-evidence.json"
    errors: list[str] = []

    if not note.is_file():
        return ["note.md is missing"]
    text = note.read_text(encoding="utf-8")
    frontmatter = parse_frontmatter(text)
    for key in REQUIRED_FRONTMATTER:
        if key not in frontmatter:
            errors.append(f"frontmatter key is missing: {key}")
    if frontmatter.get("source") != "douyin":
        errors.append("frontmatter source must be douyin")
    if frontmatter.get("confidence") not in {"low", "medium", "high"}:
        errors.append("frontmatter confidence must be low, medium, or high")
    if expected_aweme_id and frontmatter.get("aweme_id") != expected_aweme_id:
        errors.append("frontmatter aweme_id does not match the queue item")
    if expected_source_url and frontmatter.get("source_url") != expected_source_url:
        errors.append("frontmatter source_url does not match the queue item")
    for heading in REQUIRED_HEADINGS:
        if not re.search(rf"(?m)^{re.escape(heading)}\s*$", text):
            errors.append(f"required heading is missing: {heading}")

    if not transcript.is_file():
        errors.append("transcript.md is missing")
    else:
        transcript_text = transcript.read_text(encoding="utf-8")
        if "# 完整转写" not in transcript_text or "## 转写正文" not in transcript_text:
            errors.append("transcript.md is missing required headings")
        if expected_aweme_id and f"作品 ID：{expected_aweme_id}" not in transcript_text:
            errors.append("transcript.md is missing the expected work ID")

    if not evidence_path.is_file():
        errors.append("visual-evidence.json is missing")
        return errors
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        errors.append("visual-evidence.json is invalid")
        return errors
    frames = evidence.get("frames")
    if not isinstance(frames, list) or len(frames) > 5:
        errors.append("visual evidence must contain zero to five frames")
        return errors
    frame_dir = note_dir / "frames"
    for frame in frames:
        name = frame.get("file") if isinstance(frame, dict) else None
        if not isinstance(name, str) or Path(name).name != name:
            errors.append("visual evidence contains an unsafe frame name")
        elif not (frame_dir / name).is_file():
            errors.append(f"evidence frame is missing: {name}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--note-dir", required=True, type=Path)
    parser.add_argument("--aweme-id")
    parser.add_argument("--source-url")
    args = parser.parse_args()
    errors = validate_note_bundle(args.note_dir, args.aweme_id, args.source_url)
    if errors:
        print(json.dumps({"valid": False, "errors": errors}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"valid": True, "note_dir": str(args.note_dir.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
