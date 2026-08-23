#!/usr/bin/env python3
"""Resumable queue and guarded temp-file lifecycle for Douyin knowledge ingestion."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

VALID_STATUSES = ("pending", "processing", "completed", "failed", "skipped")
SAFE_ITEM_ID = re.compile(r"^[A-Za-z0-9._-]+$")
AWEME_PATTERNS = (
    re.compile(r"/(?:video|note)/(\d+)", re.IGNORECASE),
    re.compile(r"\b(\d{15,22})\b"),
)
MARKER_NAME = ".managed-by-ingest-douyin-favorites"
DOUYIN_HOSTS = {"douyin.com", "www.douyin.com", "v.douyin.com", "iesdouyin.com", "v.iesdouyin.com"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def paths(workspace: Path) -> dict[str, Path]:
    runtime = workspace / ".douyin-kb"
    return {
        "workspace": workspace,
        "runtime": runtime,
        "db": runtime / "state.sqlite3",
        "tmp": runtime / "tmp",
        "knowledge": workspace / "knowledge" / "douyin",
    }


def connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


@contextmanager
def db_session(db_path: Path):
    connection = connect(db_path)
    try:
        yield connection
    finally:
        connection.close()


def initialize(workspace: Path) -> dict[str, str]:
    resolved = paths(workspace)
    resolved["runtime"].mkdir(parents=True, exist_ok=True)
    resolved["tmp"].mkdir(parents=True, exist_ok=True)
    resolved["knowledge"].mkdir(parents=True, exist_ok=True)
    marker = resolved["tmp"] / MARKER_NAME
    marker.write_text("Managed temporary root. Delete children only through the skill.\n", encoding="utf-8")

    with db_session(resolved["db"]) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS items (
                aweme_id TEXT PRIMARY KEY,
                source_url TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                author TEXT NOT NULL DEFAULT '',
                favorite_folder TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','processing','completed','failed','skipped')),
                attempts INTEGER NOT NULL DEFAULT 0,
                discovered_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                output_path TEXT,
                error TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_items_status_discovered
                ON items(status, discovered_at, aweme_id);
            """
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(items)")}
        if "published_at" not in columns:
            connection.execute("ALTER TABLE items ADD COLUMN published_at TEXT NOT NULL DEFAULT ''")
    return {key: str(value) for key, value in resolved.items()}


def require_initialized(workspace: Path) -> dict[str, Path]:
    resolved = paths(workspace)
    if not resolved["db"].is_file():
        raise RuntimeError("State is not initialized. Run the init command first.")
    return resolved


def extract_aweme_id(url: str) -> str:
    for pattern in AWEME_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    digest = hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:20]
    return f"url-{digest}"


def normalize_source_url(value: str) -> str:
    value = value.strip()
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme.lower() not in {"http", "https"} or host not in DOUYIN_HOSTS:
        raise ValueError("Source URL must be an http(s) Douyin URL")
    match = re.search(r"/(video|note)/(\d{15,22})(?:/|$)", parsed.path, re.IGNORECASE)
    if match:
        return f"https://www.douyin.com/{match.group(1).lower()}/{match.group(2)}"
    if host in {"v.douyin.com", "iesdouyin.com", "v.iesdouyin.com"} and parsed.path.strip("/"):
        return urlunsplit(("https", host, parsed.path.rstrip("/"), "", ""))
    raise ValueError("Source URL must identify a Douyin video, note, or short link")


def validate_item_id(item_id: str) -> str:
    if not SAFE_ITEM_ID.fullmatch(item_id):
        raise ValueError(f"Unsafe item id: {item_id!r}")
    return item_id


def redact_error(value: str) -> str:
    value = re.sub(
        r"https?://[^\s]+",
        lambda match: urlunsplit((*urlsplit(match.group(0))[:3], "", "")),
        value,
    )
    value = re.sub(
        r"(?i)(token|cookie|authorization|api[_-]?key)\s*[:=]\s*\S+",
        r"\1=[REDACTED]",
        value,
    )
    return value[:2000]


def json_record(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at line {line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"JSONL line {line_number} is not an object")
            yield value


def enqueue_one(connection: sqlite3.Connection, item: dict[str, Any]) -> str:
    source_url = str(item.get("source_url") or item.get("url") or "").strip()
    if not source_url:
        raise ValueError("Each item requires source_url or url")
    source_url = normalize_source_url(source_url)
    aweme_id = validate_item_id(str(item.get("aweme_id") or item.get("id") or extract_aweme_id(source_url)))
    now = utc_now()
    connection.execute(
        """
        INSERT INTO items (
            aweme_id, source_url, title, author, favorite_folder, published_at,
            status, attempts, discovered_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?)
        ON CONFLICT(aweme_id) DO UPDATE SET
            source_url = excluded.source_url,
            title = CASE WHEN excluded.title <> '' THEN excluded.title ELSE items.title END,
            author = CASE WHEN excluded.author <> '' THEN excluded.author ELSE items.author END,
            favorite_folder = CASE
                WHEN excluded.favorite_folder <> '' THEN excluded.favorite_folder
                ELSE items.favorite_folder
            END,
            published_at = CASE
                WHEN excluded.published_at <> '' THEN excluded.published_at
                ELSE items.published_at
            END,
            updated_at = CASE
                WHEN items.status = 'completed' THEN items.updated_at
                ELSE excluded.updated_at
            END
        """,
        (
            aweme_id,
            source_url,
            str(item.get("title") or "").strip(),
            str(item.get("author") or "").strip(),
            str(item.get("favorite_folder") or "").strip(),
            str(item.get("published_at") or "").strip(),
            now,
            now,
        ),
    )
    return aweme_id


def claim_next(connection: sqlite3.Connection) -> dict[str, Any] | None:
    connection.execute("BEGIN IMMEDIATE")
    row = connection.execute(
        "SELECT * FROM items WHERE status = 'pending' ORDER BY discovered_at, aweme_id LIMIT 1"
    ).fetchone()
    if row is None:
        connection.commit()
        return None
    now = utc_now()
    connection.execute(
        """
        UPDATE items
        SET status = 'processing', attempts = attempts + 1, updated_at = ?, error = NULL
        WHERE aweme_id = ? AND status = 'pending'
        """,
        (now, row["aweme_id"]),
    )
    connection.commit()
    return json_record(
        connection.execute("SELECT * FROM items WHERE aweme_id = ?", (row["aweme_id"],)).fetchone()
    )


def ensure_note_output(
    output: Path,
    knowledge_root: Path,
    expected_aweme_id: str | None = None,
    expected_source_url: str | None = None,
) -> Path:
    output = output.expanduser().resolve()
    knowledge_root = knowledge_root.resolve()
    try:
        output.relative_to(knowledge_root)
    except ValueError as exc:
        raise ValueError(f"Output must be inside {knowledge_root}") from exc
    if output.name.lower() != "note.md" or not output.is_file():
        raise ValueError("Output must point to an existing note.md")
    transcript = output.with_name("transcript.md")
    if not transcript.is_file():
        raise ValueError(f"Missing required transcript: {transcript}")
    evidence_path = output.with_name("visual-evidence.json")
    if not evidence_path.is_file():
        raise ValueError(f"Missing required visual evidence: {evidence_path}")
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid visual evidence JSON: {evidence_path}") from exc
    evidence_frames = evidence.get("frames")
    if not isinstance(evidence_frames, list):
        raise ValueError("visual-evidence.json must contain a frames list")
    if len(evidence_frames) > 5:
        raise ValueError(f"Too many evidence frames: {len(evidence_frames)}; maximum is 5")
    frames = output.parent / "frames"
    if frames.is_dir():
        frame_count = sum(1 for path in frames.iterdir() if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
        if frame_count > 5:
            raise ValueError(f"Too many retained keyframes: {frame_count}; maximum is 5")
    for frame in evidence_frames:
        name = frame.get("file") if isinstance(frame, dict) else None
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError("Every evidence frame must contain a safe relative file name")
        if not (frames / name).is_file():
            raise ValueError(f"Evidence frame is missing: {frames / name}")
    from validate_note import validate_note_bundle

    errors = validate_note_bundle(
        output.parent,
        expected_aweme_id=expected_aweme_id,
        expected_source_url=expected_source_url,
    )
    if errors:
        raise ValueError("Invalid note bundle: " + "; ".join(errors))
    return output


def rebuild_index(connection: sqlite3.Connection, knowledge_root: Path) -> Path:
    rows = connection.execute(
        """
        SELECT title, author, completed_at, output_path
        FROM items
        WHERE status = 'completed' AND output_path IS NOT NULL
        ORDER BY completed_at DESC, aweme_id DESC
        """
    ).fetchall()
    lines = ["# 抖音收藏知识库", ""]
    included = 0
    for row in rows:
        note = Path(row["output_path"]).expanduser().resolve()
        if not note.is_file():
            continue
        try:
            relative = note.relative_to(knowledge_root.resolve()).as_posix()
        except ValueError:
            continue
        title = str(row["title"] or note.parent.name).replace("[", "［").replace("]", "］")
        suffix = " · ".join(part for part in (str(row["author"] or ""), str(row["completed_at"] or "")[:10]) if part)
        lines.append(f"- [{title}]({relative})" + (f" — {suffix}" if suffix else ""))
        included += 1
    if not included:
        lines.append("暂无已完成条目。")
    index_path = knowledge_root / "index.md"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = index_path.with_suffix(".md.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(index_path)
    return index_path


def guarded_temp_path(temp_root: Path, item_id: str, create: bool = False) -> Path:
    validate_item_id(item_id)
    marker = temp_root / MARKER_NAME
    if not marker.is_file():
        raise RuntimeError(f"Managed temp marker is missing: {marker}")
    root = temp_root.resolve()
    target = (temp_root / item_id).resolve()
    if target.parent != root:
        raise RuntimeError("Refusing an unsafe temp path")
    if create:
        target.mkdir(parents=False, exist_ok=True)
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".", help="Project workspace directory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Create state, knowledge, and managed temp directories")

    enqueue = subparsers.add_parser("enqueue", help="Add URLs or discovery JSONL to the queue")
    enqueue.add_argument("--url", action="append", default=[])
    enqueue.add_argument("--jsonl", type=Path)
    enqueue.add_argument("--title", default="")
    enqueue.add_argument("--author", default="")
    enqueue.add_argument("--favorite-folder", default="")

    listing = subparsers.add_parser("list", help="List queue records")
    listing.add_argument("--status", choices=VALID_STATUSES)
    listing.add_argument("--limit", type=int, default=50)

    subparsers.add_parser("status", help="Show counts by status")
    subparsers.add_parser("claim", help="Atomically claim the next pending item")

    complete = subparsers.add_parser("complete", help="Mark an item complete after output checks")
    complete.add_argument("item_id")
    complete.add_argument("--output", required=True, type=Path)

    fail = subparsers.add_parser("fail", help="Mark an item failed")
    fail.add_argument("item_id")
    fail.add_argument("--error", required=True)

    skip = subparsers.add_parser("skip", help="Mark an unsupported item skipped")
    skip.add_argument("item_id")
    skip.add_argument("--reason", required=True)

    retry = subparsers.add_parser("retry", help="Return failed items to pending")
    retry.add_argument("item_id", nargs="?")
    retry.add_argument("--all", action="store_true")

    stale = subparsers.add_parser("reset-stale", help="Reset old processing rows to pending")
    stale.add_argument("--minutes", type=int, default=120)

    temp_path = subparsers.add_parser("temp-path", help="Create and return a managed item temp path")
    temp_path.add_argument("item_id")

    cleanup = subparsers.add_parser("cleanup", help="Delete one managed item temp directory")
    cleanup.add_argument("item_id")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    workspace = Path(args.workspace).expanduser().resolve()
    if not workspace.is_dir():
        raise RuntimeError(f"Workspace does not exist: {workspace}")

    if args.command == "init":
        print(json.dumps(initialize(workspace), ensure_ascii=False, indent=2))
        return 0

    resolved = require_initialized(workspace)

    if args.command == "temp-path":
        print(guarded_temp_path(resolved["tmp"], args.item_id, create=True))
        return 0

    if args.command == "cleanup":
        target = guarded_temp_path(resolved["tmp"], args.item_id)
        existed = target.exists()
        if existed:
            shutil.rmtree(target)
        print(json.dumps({"item_id": args.item_id, "removed": existed, "path": str(target)}, ensure_ascii=False))
        return 0

    with db_session(resolved["db"]) as connection:
        if args.command == "enqueue":
            items: list[dict[str, Any]] = [
                {
                    "source_url": url,
                    "title": args.title,
                    "author": args.author,
                    "favorite_folder": args.favorite_folder,
                }
                for url in args.url
            ]
            if args.jsonl:
                items.extend(iter_jsonl(args.jsonl.expanduser().resolve()))
            if not items:
                raise ValueError("Provide at least one --url or --jsonl file")
            ids = [enqueue_one(connection, item) for item in items]
            connection.commit()
            print(json.dumps({"enqueued": len(ids), "item_ids": ids}, ensure_ascii=False, indent=2))
            return 0

        if args.command == "status":
            counts = {status: 0 for status in VALID_STATUSES}
            for row in connection.execute("SELECT status, COUNT(*) AS count FROM items GROUP BY status"):
                counts[row["status"]] = row["count"]
            print(json.dumps({"total": sum(counts.values()), "counts": counts}, ensure_ascii=False, indent=2))
            return 0

        if args.command == "list":
            limit = max(1, min(args.limit, 1000))
            if args.status:
                rows = connection.execute(
                    "SELECT * FROM items WHERE status = ? ORDER BY discovered_at, aweme_id LIMIT ?",
                    (args.status, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM items ORDER BY discovered_at, aweme_id LIMIT ?", (limit,)
                ).fetchall()
            print(json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2))
            return 0

        if args.command == "claim":
            print(json.dumps({"item": claim_next(connection)}, ensure_ascii=False, indent=2))
            return 0

        if args.command == "complete":
            item_id = validate_item_id(args.item_id)
            row = connection.execute("SELECT * FROM items WHERE aweme_id = ?", (item_id,)).fetchone()
            if row is None or row["status"] != "processing":
                raise RuntimeError("Item is missing or is not in processing state")
            output = ensure_note_output(
                args.output,
                resolved["knowledge"],
                expected_aweme_id=item_id,
                expected_source_url=row["source_url"],
            )
            now = utc_now()
            cursor = connection.execute(
                """
                UPDATE items SET status = 'completed', output_path = ?, completed_at = ?,
                    updated_at = ?, error = NULL
                WHERE aweme_id = ? AND status = 'processing'
                """,
                (str(output), now, now, item_id),
            )
            connection.commit()
            index_path = rebuild_index(connection, resolved["knowledge"])
            print(json.dumps({"completed": item_id, "output": str(output), "index": str(index_path)}, ensure_ascii=False))
            return 0

        if args.command == "fail":
            item_id = validate_item_id(args.item_id)
            cursor = connection.execute(
                "UPDATE items SET status = 'failed', error = ?, updated_at = ? WHERE aweme_id = ?",
                (redact_error(args.error), utc_now(), item_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Unknown item")
            connection.commit()
            print(json.dumps({"failed": item_id}, ensure_ascii=False))
            return 0

        if args.command == "skip":
            item_id = validate_item_id(args.item_id)
            cursor = connection.execute(
                "UPDATE items SET status = 'skipped', error = ?, updated_at = ? WHERE aweme_id = ?",
                (redact_error(args.reason), utc_now(), item_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Unknown item")
            connection.commit()
            print(json.dumps({"skipped": item_id, "reason": redact_error(args.reason)}, ensure_ascii=False))
            return 0

        if args.command == "retry":
            if args.all == bool(args.item_id):
                raise ValueError("Choose exactly one of ITEM_ID or --all")
            if args.all:
                cursor = connection.execute(
                    "UPDATE items SET status = 'pending', error = NULL, updated_at = ? WHERE status = 'failed'",
                    (utc_now(),),
                )
            else:
                item_id = validate_item_id(args.item_id)
                cursor = connection.execute(
                    """
                    UPDATE items SET status = 'pending', error = NULL, updated_at = ?
                    WHERE aweme_id = ? AND status = 'failed'
                    """,
                    (utc_now(), item_id),
                )
            connection.commit()
            print(json.dumps({"retried": cursor.rowcount}, ensure_ascii=False))
            return 0

        if args.command == "reset-stale":
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=max(1, args.minutes))).isoformat(
                timespec="seconds"
            ).replace("+00:00", "Z")
            cursor = connection.execute(
                """
                UPDATE items SET status = 'pending', error = 'Recovered stale processing state', updated_at = ?
                WHERE status = 'processing' AND updated_at < ?
                """,
                (utc_now(), cutoff),
            )
            connection.commit()
            print(json.dumps({"reset": cursor.rowcount, "cutoff": cutoff}, ensure_ascii=False))
            return 0

    raise RuntimeError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
