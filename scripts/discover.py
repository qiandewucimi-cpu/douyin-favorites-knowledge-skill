#!/usr/bin/env python3
"""Discover a small number of Douyin favorites without downloading media."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read favorite metadata through an existing douyin-downloader login."
    )
    parser.add_argument("--downloader-root", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--exclude-id", action="append", default=[], help="Skip an already-known work ID")
    parser.add_argument(
        "--include-folders",
        action="store_true",
        help="If the account-level feed is empty, inspect custom collection folders.",
    )
    return parser.parse_args()


def unwrap_aweme(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    for key in ("aweme_info", "aweme"):
        nested = item.get(key)
        if isinstance(nested, dict):
            return nested
    return item


def folder_id(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    info = item.get("collects_info") if isinstance(item.get("collects_info"), dict) else {}
    return str(
        item.get("collects_id")
        or item.get("collects_id_str")
        or item.get("id")
        or info.get("collects_id")
        or info.get("collects_id_str")
        or ""
    )


def folder_name(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    info = item.get("collects_info") if isinstance(item.get("collects_info"), dict) else {}
    return str(
        item.get("collects_name")
        or item.get("name")
        or item.get("title")
        or info.get("collects_name")
        or info.get("name")
        or ""
    )


def normalize_aweme(item: Any, favorite_folder: str = "") -> dict[str, Any] | None:
    aweme = unwrap_aweme(item)
    if not aweme:
        return None
    aweme_id = str(aweme.get("aweme_id") or aweme.get("group_id") or "").strip()
    if not aweme_id.isdigit() or not 15 <= len(aweme_id) <= 22:
        return None
    author = aweme.get("author") if isinstance(aweme.get("author"), dict) else {}
    create_time = aweme.get("create_time")
    published_at = ""
    if isinstance(create_time, (int, float)) and create_time > 0:
        published_at = datetime.fromtimestamp(create_time, timezone.utc).isoformat()
    return {
        "aweme_id": aweme_id,
        "source_url": f"https://www.douyin.com/video/{aweme_id}",
        "title": str(aweme.get("desc") or "").strip(),
        "author": str(author.get("nickname") or "").strip(),
        "favorite_folder": favorite_folder,
        "published_at": published_at,
    }


async def discover(args: argparse.Namespace) -> list[dict[str, Any]]:
    root = args.downloader_root.resolve()
    config_path = args.config.resolve()
    if not root.is_dir():
        raise RuntimeError(f"douyin-downloader not found: {root}")
    if not config_path.is_file():
        raise RuntimeError(f"config not found: {config_path}")
    if args.limit < 1 or args.limit > 100:
        raise RuntimeError("--limit must be between 1 and 100")

    sys.path.insert(0, str(root))
    from config import ConfigLoader
    from core import DouyinAPIClient, LoginRequiredError

    config = ConfigLoader(str(config_path))
    cookies = config.get_cookies()
    if not cookies:
        raise RuntimeError("No Douyin cookies found in config")

    found: list[dict[str, Any]] = []
    excluded = {str(value) for value in getattr(args, "exclude_ids", getattr(args, "exclude_id", []))}
    seen: set[str] = set(excluded)

    def add_items(items: Any, name: str = "") -> None:
        for raw in items if isinstance(items, list) else []:
            normalized = normalize_aweme(raw, name)
            if not normalized or normalized["aweme_id"] in seen:
                continue
            seen.add(normalized["aweme_id"])
            found.append(normalized)
            if len(found) >= args.limit:
                return

    try:
        async with DouyinAPIClient(cookies, proxy=config.get("proxy")) as client:
            cursor = 0
            visited_cursors: set[int] = set()
            while len(found) < args.limit:
                page = await client.get_user_collection("self", max_cursor=cursor, count=20)
                add_items(page.get("items", []), "默认收藏")
                if not page.get("has_more") or len(found) >= args.limit:
                    break
                next_cursor = int(page.get("max_cursor") or 0)
                if next_cursor == cursor or next_cursor in visited_cursors:
                    raise RuntimeError("Douyin collection pagination returned a repeated cursor")
                visited_cursors.add(cursor)
                cursor = next_cursor

            if args.include_folders and len(found) < args.limit:
                folder_cursor = 0
                folders_seen: set[str] = set()
                visited_folder_cursors: set[int] = set()
                while len(found) < args.limit:
                    folders = await client.get_user_collects("self", max_cursor=folder_cursor, count=20)
                    for folder in folders.get("items", []):
                        collect_id = folder_id(folder)
                        if collect_id and collect_id not in folders_seen:
                            folders_seen.add(collect_id)
                            video_cursor = 0
                            visited_video_cursors: set[int] = set()
                            while len(found) < args.limit:
                                page = await client.get_collect_aweme(
                                    collect_id, max_cursor=video_cursor, count=20
                                )
                                add_items(page.get("items", []), folder_name(folder))
                                if not page.get("has_more") or len(found) >= args.limit:
                                    break
                                next_video_cursor = int(page.get("max_cursor") or 0)
                                if next_video_cursor == video_cursor or next_video_cursor in visited_video_cursors:
                                    raise RuntimeError("Douyin folder pagination returned a repeated cursor")
                                visited_video_cursors.add(video_cursor)
                                video_cursor = next_video_cursor
                    if not folders.get("has_more") or len(found) >= args.limit:
                        break
                    next_folder_cursor = int(folders.get("max_cursor") or 0)
                    if next_folder_cursor == folder_cursor or next_folder_cursor in visited_folder_cursors:
                        raise RuntimeError("Douyin folder list returned a repeated cursor")
                    visited_folder_cursors.add(folder_cursor)
                    folder_cursor = next_folder_cursor
    except LoginRequiredError as exc:
        message = exc.status_msg or "login required"
        raise RuntimeError(f"Douyin login expired: {message}") from exc

    return found[: args.limit]


def main() -> int:
    args = parse_args()
    try:
        items = asyncio.run(discover(args))
        payload = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items)
        if args.output:
            output = args.output.resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(payload, encoding="utf-8")
            print(json.dumps({"discovered": len(items), "output": str(output)}, ensure_ascii=False))
        else:
            print(payload, end="")
        return 0 if items else 4
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
