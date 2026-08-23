#!/usr/bin/env python3
"""Claim and prepare one pending favorite with one permission-scoped command."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from pipeline import (
    claim_next,
    db_session,
    guarded_temp_path,
    redact_error,
    require_initialized,
    utc_now,
)

INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MEDIA_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".avif"}


class UnsupportedMedia(RuntimeError):
    pass


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def safe_title(value: str, item_id: str) -> str:
    value = INVALID_NAME.sub("_", value).replace("\n", " ").replace("\r", " ")
    value = re.sub(r"\s+", " ", value).strip(" ._")
    value = re.sub(r"[#@][^\s]+", "", value).strip()
    return (value[:36].rstrip(" ._") or "抖音收藏") + f"_{item_id}"


def largest_media(root: Path) -> Path:
    candidates = [path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES]
    if not candidates:
        if any(path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES for path in root.rglob("*")):
            raise UnsupportedMedia("favorite is an image post, not a video")
        raise RuntimeError("acquisition completed without a supported video file")
    return max(candidates, key=lambda path: path.stat().st_size)


def has_audio_stream(path: Path) -> bool:
    import av

    with av.open(str(path)) as container:
        return bool(container.streams.audio)


def run_logged(command: list[str], stdout_path: Path, stderr_path: Path) -> None:
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
    for log_path in (stdout_path, stderr_path):
        try:
            sanitized = redact_error(log_path.read_text(encoding="utf-8", errors="replace"))
            log_path.write_text(sanitized + ("\n" if sanitized else ""), encoding="utf-8")
        except OSError:
            pass
    if result.returncode:
        raise RuntimeError(f"media preparation command failed with exit code {result.returncode}")


def mark_failed(db: Path, item_id: str, error: str) -> None:
    with db_session(db) as connection:
        connection.execute(
            "UPDATE items SET status='failed', error=?, updated_at=? WHERE aweme_id=?",
            (redact_error(error), utc_now(), item_id),
        )
        connection.commit()


def mark_skipped(db: Path, item_id: str, reason: str) -> None:
    with db_session(db) as connection:
        connection.execute(
            "UPDATE items SET status='skipped', error=?, updated_at=? WHERE aweme_id=?",
            (redact_error(reason), utc_now(), item_id),
        )
        connection.commit()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=".", type=Path)
    parser.add_argument("--downloader-root", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--profile", choices=("fast", "balanced", "full"), default="fast")
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    resolved = require_initialized(workspace)
    with db_session(resolved["db"]) as connection:
        item = claim_next(connection)
    if item is None:
        print(json.dumps({"state": "empty", "message": "no pending item"}, ensure_ascii=False))
        return 0

    item_id = item["aweme_id"]
    jobs_dir = workspace / ".douyin-kb" / "jobs" / item_id
    status_path = jobs_dir / "prepare-status.json"
    temp_dir = guarded_temp_path(resolved["tmp"], item_id, create=True)
    published_year = str(item.get("published_at") or "")[:4]
    year = published_year if re.fullmatch(r"20\d{2}", published_year) else str(__import__("datetime").datetime.now().year)
    note_dir = resolved["knowledge"] / year / safe_title(item.get("title") or "", item_id)
    note_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir = Path(__file__).resolve().parent
    settings = {
        "fast": {"quality": "lowest", "transcript": "fast", "frames": "fast", "ocr": True, "ocr_model": "fast"},
        "balanced": {"quality": "720p", "transcript": "balanced", "frames": "balanced", "ocr": True, "ocr_model": "fast"},
        "full": {"quality": "highest", "transcript": "accurate", "frames": "full", "ocr": True, "ocr_model": "accurate"},
    }[args.profile]

    def phase(name: str, **extra: object) -> None:
        payload = {"state": "running", "phase": name, "item_id": item_id, "profile": args.profile, **extra}
        write_json(status_path, payload)
        print(json.dumps(payload, ensure_ascii=False), flush=True)

    try:
        frames_output = note_dir / "frames"
        if frames_output.is_dir():
            shutil.rmtree(frames_output)
        for stale_output in (note_dir / "note.md", note_dir / "transcript.md", note_dir / "visual-evidence.json"):
            if stale_output.is_file():
                stale_output.unlink()
        existing_media = [
            path for path in temp_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES
        ]
        if existing_media:
            video = max(existing_media, key=lambda path: path.stat().st_size)
            phase("reusing_download", downloaded_bytes=video.stat().st_size)
        else:
            phase("acquiring", video_quality=settings["quality"])
            acquire_command = [
                sys.executable,
                str(scripts_dir / "acquire_one.py"),
                "--downloader-root", str(args.downloader_root.resolve()),
                "--config", str(args.config.resolve()),
                "--url", item["source_url"],
                "--output-dir", str(temp_dir),
                "--status-file", str(jobs_dir / "acquire-status.json"),
                "--video-quality", str(settings["quality"]),
            ]
            run_logged(acquire_command, jobs_dir / "acquire-stdout.log", jobs_dir / "acquire-stderr.log")
            video = largest_media(temp_dir)
        has_audio = has_audio_stream(video)
        if not has_audio and args.profile == "fast" and settings["quality"] == "lowest":
            phase("reacquiring_audio", previous_bytes=video.stat().st_size, video_quality="720p")
            shutil.rmtree(temp_dir)
            temp_dir.mkdir(parents=True, exist_ok=True)
            acquire_command = [
                sys.executable,
                str(scripts_dir / "acquire_one.py"),
                "--downloader-root", str(args.downloader_root.resolve()),
                "--config", str(args.config.resolve()),
                "--url", item["source_url"],
                "--output-dir", str(temp_dir),
                "--status-file", str(jobs_dir / "acquire-status.json"),
                "--video-quality", "720p",
            ]
            run_logged(acquire_command, jobs_dir / "acquire-stdout.log", jobs_dir / "acquire-stderr.log")
            video = largest_media(temp_dir)
            has_audio = has_audio_stream(video)

        phase("transcribing", downloaded_bytes=video.stat().st_size, has_audio=has_audio)
        subprocess.run(
            [
                sys.executable, str(scripts_dir / "transcribe.py"),
                "--input", str(video),
                "--output", str(note_dir / "transcript.md"),
                "--model-dir", str(workspace / ".douyin-kb" / "models" / "whisper"),
                "--preset", str(settings["transcript"]),
            ],
            check=True,
        )

        frame_profile = str(settings["frames"]) if has_audio else "balanced"
        use_ocr = bool(settings["ocr"]) or not has_audio
        phase(
            "extracting_frames",
            downloaded_bytes=video.stat().st_size,
            visual_priority=not has_audio,
            ocr=use_ocr,
        )
        frame_command = [
            sys.executable, str(scripts_dir / "analyze_frames.py"),
            "--input", str(video),
            "--frames-dir", str(note_dir / "frames"),
            "--ocr-output", str(note_dir / "visual-evidence.json"),
            "--workspace", str(workspace),
            "--max-frames", "5",
            "--profile", frame_profile,
            "--ocr-model", str(settings["ocr_model"]),
        ]
        if not use_ocr:
            frame_command.append("--skip-ocr")
        subprocess.run(frame_command, check=True)

        payload = {
            "state": "prepared",
            "item_id": item_id,
            "profile": args.profile,
            "note_dir": str(note_dir),
            "transcript": str(note_dir / "transcript.md"),
            "visual_evidence": str(note_dir / "visual-evidence.json"),
            "downloaded_bytes": video.stat().st_size,
            "source_url": item["source_url"],
            "title": item.get("title") or "",
            "author": item.get("author") or "",
            "favorite_folder": item.get("favorite_folder") or "",
            "published_at": item.get("published_at") or "",
        }
        write_json(status_path, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except UnsupportedMedia as exc:
        reason = str(exc)
        mark_skipped(resolved["db"], item_id, reason)
        if temp_dir.is_dir():
            shutil.rmtree(temp_dir)
        write_json(status_path, {"state": "skipped", "item_id": item_id, "reason": reason})
        print(json.dumps({"state": "skipped", "item_id": item_id, "reason": reason}, ensure_ascii=False))
        return 3
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        mark_failed(resolved["db"], item_id, error)
        write_json(status_path, {"state": "failed", "item_id": item_id, "error": redact_error(error)})
        print(f"ERROR: {redact_error(error)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
