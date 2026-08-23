#!/usr/bin/env python3
"""Retry OCR for frames already selected by analyze_frames.py."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from analyze_frames import run_ocr


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames-dir", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--ocr-model", choices=("fast", "accurate"), default="fast")
    args = parser.parse_args()

    frames_dir = args.frames_dir.resolve()
    evidence_path = args.evidence.resolve()
    workspace = args.workspace.resolve()
    if not frames_dir.is_dir() or not evidence_path.is_file():
        raise SystemExit("frames directory and existing evidence JSON are required")
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    frames = payload.get("frames")
    if not isinstance(frames, list) or len(frames) > 5:
        raise SystemExit("evidence must contain a frames list with at most five entries")
    for frame in frames:
        if not isinstance(frame, dict) or not isinstance(frame.get("file"), str):
            raise SystemExit("invalid frame entry in evidence")
        name = frame["file"]
        if Path(name).name != name or not (frames_dir / name).is_file():
            raise SystemExit(f"missing or unsafe evidence frame: {name}")
        frame["absolute_path"] = str((frames_dir / name).resolve())

    backend, error = run_ocr(
        frames, workspace / ".douyin-kb" / "models" / "paddlex", args.ocr_model
    )
    payload["ocr_backend"] = backend
    payload["ocr_model"] = args.ocr_model
    payload["ocr_error"] = error
    for frame in frames:
        frame.pop("absolute_path", None)
    temporary = evidence_path.with_suffix(evidence_path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(evidence_path)
    print(json.dumps({"frames": len(frames), "ocr_backend": backend, "output": str(evidence_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
