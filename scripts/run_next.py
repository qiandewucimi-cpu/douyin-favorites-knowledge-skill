#!/usr/bin/env python3
"""Discover when needed and prepare one favorite through a single command."""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from discover import discover
from discover_browser import run as discover_in_browser
from pipeline import db_session, enqueue_one, initialize, paths, redact_error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=".", type=Path)
    parser.add_argument("--downloader-root", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--profile", choices=("fast", "balanced", "full"), default="fast")
    parser.add_argument("--discovery-limit", type=int, default=100)
    parser.add_argument("--include-folders", action="store_true")
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    resolved = paths(workspace)
    if not resolved["db"].is_file():
        initialize(workspace)

    with db_session(resolved["db"]) as connection:
        pending = int(connection.execute("SELECT COUNT(*) FROM items WHERE status='pending'").fetchone()[0])
        known_ids = {str(row[0]) for row in connection.execute("SELECT aweme_id FROM items")}

    discovered_count = 0
    if pending == 0:
        discovery_args = SimpleNamespace(
            downloader_root=args.downloader_root,
            config=args.config,
            limit=max(1, min(args.discovery_limit, 100)),
            output=None,
            include_folders=args.include_folders,
            exclude_ids=known_ids,
        )
        api_error = None
        try:
            items = asyncio.run(discover(discovery_args))
            discovery_backend = "api"
        except Exception as exc:
            api_error = redact_error(f"{type(exc).__name__}: {exc}")
            items = []
        if not items:
            browser_args = SimpleNamespace(
                downloader_root=args.downloader_root,
                config=args.config,
                limit=min(20, discovery_args.limit),
                output=None,
                headless=True,
                exclude_ids=known_ids,
            )
            try:
                items = asyncio.run(discover_in_browser(browser_args))
                discovery_backend = "browser"
            except Exception as exc:
                browser_error = redact_error(f"{type(exc).__name__}: {exc}")
                if api_error:
                    raise RuntimeError(
                        f"favorites discovery failed; api={api_error}; browser={browser_error}"
                    ) from exc
                raise
        discovered_count = len(items)
        with db_session(resolved["db"]) as connection:
            for item in items:
                enqueue_one(connection, item)
            connection.commit()
            pending = int(connection.execute("SELECT COUNT(*) FROM items WHERE status='pending'").fetchone()[0])

    print(
        json.dumps(
            {
                "phase": "discovery",
                "backend": locals().get("discovery_backend", "queue"),
                "discovered": discovered_count,
                "pending": pending,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    if pending == 0:
        print(json.dumps({"state": "empty", "message": "no unprocessed favorite found"}, ensure_ascii=False))
        return 0

    for _ in range(20):
        command = [
            sys.executable,
            str(Path(__file__).with_name("prepare_next.py")),
            "--workspace", str(workspace),
            "--downloader-root", str(args.downloader_root.resolve()),
            "--config", str(args.config.resolve()),
            "--profile", args.profile,
        ]
        returncode = subprocess.run(command, stdin=subprocess.DEVNULL).returncode
        if returncode != 3:
            return returncode
        print(json.dumps({"phase": "continue", "reason": "skipped non-video favorite"}, ensure_ascii=False), flush=True)
    print("ERROR: too many consecutive non-video favorites", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
