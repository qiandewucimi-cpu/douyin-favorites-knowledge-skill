#!/usr/bin/env python3
"""Launch one acquisition as a tracked background job."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SAFE_ITEM_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--item-id", required=True)
    parser.add_argument("--downloader-root", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--url", required=True)
    parser.add_argument("--video-quality", default="lowest")
    args = parser.parse_args()

    if not SAFE_ITEM_ID.fullmatch(args.item_id):
        raise SystemExit("unsafe item id")
    workspace = args.workspace.resolve()
    jobs_root = (workspace / ".douyin-kb" / "jobs").resolve()
    job_dir = (jobs_root / args.item_id).resolve()
    if job_dir.parent != jobs_root:
        raise SystemExit("unsafe job directory")
    job_dir.mkdir(parents=True, exist_ok=True)
    status_file = job_dir / "status.json"
    stdout_file = job_dir / "stdout.log"
    stderr_file = job_dir / "stderr.log"
    output_dir = workspace / ".douyin-kb" / "tmp" / args.item_id
    command = [
        sys.executable,
        str(Path(__file__).with_name("acquire_one.py")),
        "--downloader-root",
        str(args.downloader_root.resolve()),
        "--config",
        str(args.config.resolve()),
        "--url",
        args.url,
        "--output-dir",
        str(output_dir),
        "--status-file",
        str(status_file),
        "--video-quality",
        args.video_quality,
    ]
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    with stdout_file.open("w", encoding="utf-8") as stdout, stderr_file.open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(
            command,
            cwd=workspace,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
        )
    print(
        json.dumps(
            {
                "item_id": args.item_id,
                "pid": process.pid,
                "status_file": str(status_file),
                "stdout_log": str(stdout_file),
                "stderr_log": str(stderr_file),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
