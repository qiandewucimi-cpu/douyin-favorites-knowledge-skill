#!/usr/bin/env python3
"""Read a few favorite links from a visible, cookie-backed Douyin page."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

FAVORITES_URL = "https://www.douyin.com/user/self?showTab=favorite_collection"


def args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--downloader-root", required=True, type=Path)
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--limit", type=int, default=1)
    p.add_argument("--headless", action="store_true")
    return p.parse_args()


def item_from_aweme(raw: Any) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    raw = raw.get("aweme_info") if isinstance(raw.get("aweme_info"), dict) else raw
    ident = str(raw.get("aweme_id") or raw.get("group_id") or "")
    if not ident:
        return None
    author = raw.get("author") if isinstance(raw.get("author"), dict) else {}
    return {"aweme_id": ident, "source_url": f"https://www.douyin.com/video/{ident}", "title": str(raw.get("desc") or ""), "author": str(author.get("nickname") or ""), "favorite_folder": ""}


async def run(a: argparse.Namespace) -> list[dict[str, str]]:
    if not 1 <= a.limit <= 20:
        raise RuntimeError("--limit must be between 1 and 20")
    root, config = a.downloader_root.resolve(), a.config.resolve()
    if not root.is_dir() or not config.is_file():
        raise RuntimeError("downloader root or config is missing")
    sys.path.insert(0, str(root))
    from config import ConfigLoader
    from playwright.async_api import async_playwright

    loaded = ConfigLoader(str(config))
    cookies = loaded.get_cookies()
    if not cookies:
        raise RuntimeError("no cookies in config")
    results: list[dict[str, str]] = []
    seen: set[str] = {str(value) for value in getattr(a, "exclude_ids", [])}

    def add(item: dict[str, str] | None) -> None:
        if item and item["aweme_id"] not in seen and len(results) < a.limit:
            seen.add(item["aweme_id"])
            results.append(item)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=a.headless, args=["--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(locale="zh-CN", viewport={"width": 1600, "height": 900})
        await context.add_cookies([{"name": k, "value": v, "domain": ".douyin.com", "path": "/"} for k, v in cookies.items()])
        page = await context.new_page()

        async def response(res: Any) -> None:
            if res.status != 200 or not any(part in (res.url or "") for part in ("listcollection", "collects/video/list")):
                return
            try:
                data = await res.json()
            except Exception:
                return
            for raw in data.get("aweme_list", []) if isinstance(data, dict) else []:
                add(item_from_aweme(raw))

        tasks: list[asyncio.Task] = []
        page.on("response", lambda res: tasks.append(asyncio.create_task(response(res))))
        await page.goto(FAVORITES_URL, wait_until="domcontentloaded", timeout=60000)
        for _ in range(60):
            if len(results) >= a.limit:
                break
            if len(results) < a.limit:
                await page.mouse.wheel(0, 1800)
                await page.wait_for_timeout(1000)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await context.close()
        await browser.close()
    return results


def main() -> int:
    a = args()
    try:
        found = asyncio.run(run(a))
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in found), encoding="utf-8")
        print(json.dumps({"discovered": len(found), "output": str(a.output.resolve())}, ensure_ascii=False))
        return 0 if found else 4
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
