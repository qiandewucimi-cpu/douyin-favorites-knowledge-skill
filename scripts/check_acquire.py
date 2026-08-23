#!/usr/bin/env python3
"""Read a tracked acquisition status without exposing downloader logs."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import time
from pathlib import Path

SAFE_ITEM_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def process_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def directory_bytes(path: Path) -> int:
    total = 0
    if path.is_dir():
        for file in path.rglob("*"):
            if file.is_file():
                try:
                    total += file.stat().st_size
                except OSError:
                    pass
    return total


def read_status(status_file: Path, output_dir: Path) -> dict:
    if not status_file.is_file():
        return {"state": "starting", "downloaded_bytes": directory_bytes(output_dir)}
    payload = json.loads(status_file.read_text(encoding="utf-8"))
    if payload.get("state") == "running":
        pid = int(payload.get("pid") or 0)
        payload["process_running"] = process_is_running(pid)
        if not payload["process_running"]:
            payload["state"] = "orphaned"
    payload["downloaded_bytes"] = directory_bytes(output_dir)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--item-id", required=True)
    parser.add_argument("--wait-seconds", type=float, default=0.0)
    args = parser.parse_args()
    if not SAFE_ITEM_ID.fullmatch(args.item_id):
        raise SystemExit("unsafe item id")
    workspace = args.workspace.resolve()
    status_file = workspace / ".douyin-kb" / "jobs" / args.item_id / "status.json"
    output_dir = workspace / ".douyin-kb" / "tmp" / args.item_id
    deadline = time.monotonic() + max(0.0, min(args.wait_seconds, 60.0))
    while True:
        payload = read_status(status_file, output_dir)
        if payload.get("state") not in {"starting", "running"} or time.monotonic() >= deadline:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        time.sleep(1.0)


if __name__ == "__main__":
    raise SystemExit(main())
