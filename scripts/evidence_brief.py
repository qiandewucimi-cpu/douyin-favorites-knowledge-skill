#!/usr/bin/env python3
"""Print a compact, agent-facing view of visual-evidence.json."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def normalized(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def build_brief(payload: dict) -> dict:
    seen: set[str] = set()
    frames = []
    raw_lines = 0
    unique_lines = 0

    for frame in payload.get("frames", []):
        kept = []
        raw_ocr = frame.get("ocr_text", frame.get("ocr", []))
        for item in raw_ocr:
            text = str(item.get("text", "") if isinstance(item, dict) else item).strip()
            if not text:
                continue
            raw_lines += 1
            key = normalized(text)
            if not key or key in seen:
                continue
            seen.add(key)
            kept.append(text)
            unique_lines += 1

        frames.append(
            {
                "file": frame.get("file"),
                "timestamp_seconds": frame.get("timestamp_seconds"),
                "selection_score": frame.get("selection_score"),
                "ocr_text": kept,
            }
        )

    return {
        "duration_seconds": payload.get("duration_seconds"),
        "selection_mode": payload.get("selection_mode"),
        "candidate_count": payload.get("candidate_count"),
        "ocr_backend": payload.get("ocr_backend"),
        "ocr_model": payload.get("ocr_model"),
        "ocr_line_count": raw_lines,
        "unique_ocr_line_count": unique_lines,
        "frames": frames,
        "ocr_error": payload.get("ocr_error"),
    }


def render_text(brief: dict) -> str:
    header = (
        f"duration={brief['duration_seconds']}s; selection={brief['selection_mode']}; "
        f"candidates={brief['candidate_count']}; ocr={brief['ocr_backend']}; "
        f"lines={brief['ocr_line_count']}; unique={brief['unique_ocr_line_count']}"
    )
    lines = [header]
    for frame in brief["frames"]:
        lines.append(f"\n[{frame['timestamp_seconds']}s] {frame['file']}")
        lines.extend(f"- {text}" for text in frame["ocr_text"])
    if brief.get("ocr_error"):
        lines.append(f"\nOCR error: {brief['ocr_error']}")
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--json", action="store_true", help="Print compact JSON instead of token-efficient text")
    args = parser.parse_args()
    payload = json.loads(args.evidence.read_text(encoding="utf-8"))
    brief = build_brief(payload)
    if args.json:
        print(json.dumps(brief, ensure_ascii=False, indent=2))
    else:
        print(render_text(brief))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
