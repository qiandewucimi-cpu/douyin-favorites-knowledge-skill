#!/usr/bin/env python3
"""Read-only readiness checks for the ingest-douyin-favorites skill."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def command_path(name: str) -> str | None:
    return shutil.which(name)


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def ffmpeg_detail() -> tuple[bool, str]:
    executable = command_path("ffmpeg")
    if executable:
        return True, executable
    if module_available("imageio_ffmpeg"):
        try:
            import imageio_ffmpeg  # type: ignore

            return True, imageio_ffmpeg.get_ffmpeg_exe()
        except Exception as exc:  # pragma: no cover - environment-specific
            return False, f"imageio-ffmpeg is installed but unusable: {exc}"
    return False, "ffmpeg command and imageio-ffmpeg are both unavailable"


def playwright_detail() -> tuple[bool, str]:
    """Check the installed browser without starting Playwright's driver process."""
    if not module_available("playwright"):
        return False, "Playwright module missing"
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "--dry-run", "chromium"],
            check=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Playwright browser check failed: {type(exc).__name__}: {exc}"[:500]
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "dry-run failed").strip()
        return False, f"Playwright browser check failed: {detail}"[:500]

    match = re.search(r"Install location:\s*(.+)", result.stdout)
    if not match:
        return False, "Playwright did not report a Chromium install location"
    reported_location = Path(match.group(1).strip())
    locations = [reported_location]
    browser_root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if browser_root and browser_root != "0":
        locations.append(Path(browser_root) / reported_location.name)
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        locations.append(
            Path(os.environ["LOCALAPPDATA"]) / "ms-playwright" / reported_location.name
        )
    elif sys.platform == "darwin":
        locations.append(Path.home() / "Library" / "Caches" / "ms-playwright" / reported_location.name)
    else:
        locations.append(Path.home() / ".cache" / "ms-playwright" / reported_location.name)

    executable_names = {"chrome", "chrome.exe", "chromium", "headless_shell", "headless_shell.exe"}
    executable = None
    for location in locations:
        if not location.is_dir():
            continue
        executable = next(
            (
                path
                for path in location.rglob("*")
                if path.is_file() and path.name.lower() in executable_names
            ),
            None,
        )
        if executable is not None:
            break
    if executable is None:
        return False, f"Chromium is not installed at {reported_location}"
    return True, str(executable)


def add_check(checks: list[dict[str, object]], name: str, ok: bool, detail: str) -> None:
    checks.append({"name": name, "ok": ok, "detail": detail})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".", help="Project workspace directory")
    parser.add_argument("--min-free-gb", type=float, default=5.0)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero unless the complete planned pipeline is ready",
    )
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    checks: list[dict[str, object]] = []

    python_ok = sys.version_info >= (3, 9)
    add_check(checks, "python", python_ok, sys.version.split()[0])

    workspace_ok = workspace.is_dir() and os.access(workspace, os.W_OK)
    add_check(checks, "workspace", workspace_ok, str(workspace))

    try:
        free_gb = shutil.disk_usage(workspace).free / (1024**3)
        disk_ok = free_gb >= args.min_free_gb
        disk_detail = f"{free_gb:.2f} GiB free; minimum {args.min_free_gb:.2f} GiB"
    except OSError as exc:
        disk_ok = False
        disk_detail = str(exc)
    add_check(checks, "disk", disk_ok, disk_detail)

    ffmpeg_ok, ffmpeg_path = ffmpeg_detail()
    add_check(checks, "ffmpeg", ffmpeg_ok, ffmpeg_path)

    whisper_ok = module_available("faster_whisper")
    add_check(
        checks,
        "faster_whisper",
        whisper_ok,
        "Python module available" if whisper_ok else "Python module missing",
    )

    paddle_ok = module_available("paddleocr")
    ocr_detail = "PaddleOCR module missing"
    if paddle_ok:
        os.environ["PADDLE_PDX_CACHE_HOME"] = os.path.relpath(
            workspace / ".douyin-kb" / "models" / "paddlex", Path.cwd()
        )
        try:
            import paddleocr  # type: ignore  # noqa: F401

            ocr_detail = "PaddleOCR import succeeded with project-local cache"
        except Exception as exc:
            paddle_ok = False
            ocr_detail = f"PaddleOCR import failed: {type(exc).__name__}: {exc}"[:500]
    ocr_ok = paddle_ok
    add_check(checks, "chinese_ocr", ocr_ok, ocr_detail)

    av_ok = module_available("av")
    add_check(checks, "media_probe", av_ok, "PyAV available" if av_ok else "Python module av is missing")

    pillow_ok = module_available("PIL")
    add_check(checks, "image_analysis", pillow_ok, "Pillow available" if pillow_ok else "Python module Pillow is missing")

    playwright_ok, browser_detail = playwright_detail()
    add_check(checks, "browser_fallback", playwright_ok, browser_detail)

    downloader = workspace / "douyin-downloader"
    downloader_ok = (downloader / "run.py").is_file() and (downloader / "core").is_dir()
    add_check(
        checks,
        "douyin_discovery_source",
        downloader_ok,
        str(downloader) if downloader_ok else "douyin-downloader checkout not found",
    )
    config = downloader / "config.yml"
    add_check(
        checks,
        "douyin_login_config",
        config.is_file(),
        str(config) if config.is_file() else "config.yml not found; login is not configured",
    )

    by_name = {str(item["name"]): bool(item["ok"]) for item in checks}
    readiness = {
        "foundation": by_name["python"] and by_name["workspace"] and by_name["disk"],
        "discovery": by_name["douyin_discovery_source"] and by_name["douyin_login_config"],
        "analysis": by_name["ffmpeg"] and by_name["media_probe"] and by_name["image_analysis"],
        "transcription": by_name["faster_whisper"] and by_name["media_probe"],
        "ocr": by_name["chinese_ocr"],
        "browser_fallback": by_name["browser_fallback"],
    }
    readiness["end_to_end"] = all(readiness.values())

    result = {"workspace": str(workspace), "checks": checks, "readiness": readiness}
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for item in checks:
            label = "OK" if item["ok"] else "MISSING"
            print(f"[{label:7}] {item['name']}: {item['detail']}")
        print(f"end_to_end_ready={str(readiness['end_to_end']).lower()}")

    return 2 if args.strict and not readiness["end_to_end"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
