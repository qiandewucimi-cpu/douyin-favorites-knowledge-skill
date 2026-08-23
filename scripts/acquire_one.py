#!/usr/bin/env python3
"""Acquire exactly one URL through douyin-downloader without its configured batch links."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--downloader-root", required=True, type=Path)
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--url", required=True)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--status-file", type=Path)
    p.add_argument("--video-quality", default="lowest")
    return p.parse_args()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def safe_error(exc: Exception) -> str:
    text = re.sub(r"https?://\S+", "<redacted-url>", str(exc))
    text = re.sub(
        r"(?i)(token|cookie|authorization|api[_-]?key)\s*[:=]\s*\S+",
        r"\1=[REDACTED]",
        text,
    )
    return f"{type(exc).__name__}: {text}"[:500]


def write_status(path: Path | None, payload: dict) -> None:
    if path is None:
        return
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


async def acquire(a: argparse.Namespace) -> dict:
    root, config_path, output = a.downloader_root.resolve(), a.config.resolve(), a.output_dir.resolve()
    if not root.is_dir() or not config_path.is_file():
        raise RuntimeError("downloader root or config is missing")
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(root))
    from auth import CookieManager
    from cli.main import download_url
    from config import ConfigLoader

    config = ConfigLoader(str(config_path))
    config.update(path=str(output), thread=1, link=[a.url], video_quality=a.video_quality)
    cookie_manager = CookieManager()
    cookie_manager.set_cookies(config.get_cookies())
    result = await download_url(a.url, config, cookie_manager, database=None, progress_reporter=None)
    if result is None:
        raise RuntimeError("downloader returned no result")
    return {"total": result.total, "success": result.success, "failed": result.failed, "skipped": result.skipped, "output_dir": str(output)}


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    a = parse_args()
    started_at = now()
    write_status(
        a.status_file,
        {"state": "running", "pid": os.getpid(), "started_at": started_at, "updated_at": started_at},
    )
    try:
        result = asyncio.run(acquire(a))
        write_status(
            a.status_file,
            {"state": "completed", "pid": os.getpid(), "started_at": started_at, "updated_at": now(), **result},
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        error = safe_error(exc)
        write_status(
            a.status_file,
            {"state": "failed", "pid": os.getpid(), "started_at": started_at, "updated_at": now(), "error": error},
        )
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
