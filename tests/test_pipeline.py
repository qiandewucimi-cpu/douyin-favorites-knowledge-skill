from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pipeline  # noqa: E402
from helpers import write_valid_bundle  # noqa: E402


class PipelineTests(unittest.TestCase):
    def test_url_normalization_removes_queries_and_rejects_other_hosts(self) -> None:
        self.assertEqual(
            pipeline.normalize_source_url(
                "https://www.douyin.com/video/7653821390349722021?token=secret#fragment"
            ),
            "https://www.douyin.com/video/7653821390349722021",
        )
        self.assertEqual(
            pipeline.normalize_source_url("https://v.douyin.com/AbCdEf/?share_token=secret"),
            "https://v.douyin.com/AbCdEf",
        )
        with self.assertRaises(ValueError):
            pipeline.normalize_source_url("https://example.com/video/7653821390349722021")

    def test_queue_completion_validation_index_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            workspace = Path(name)
            resolved = pipeline.paths(workspace)
            pipeline.initialize(workspace)
            source_url = "https://www.douyin.com/video/7653821390349722021"
            with pipeline.db_session(resolved["db"]) as connection:
                item_id = pipeline.enqueue_one(
                    connection,
                    {
                        "source_url": source_url,
                        "title": "测试视频",
                        "author": "作者",
                        "published_at": "2026-01-01T00:00:00+00:00",
                    },
                )
                connection.commit()
                claimed = pipeline.claim_next(connection)
                self.assertEqual(claimed["aweme_id"], item_id)
                self.assertEqual(claimed["published_at"], "2026-01-01T00:00:00+00:00")

                note = write_valid_bundle(
                    resolved["knowledge"] / "2026" / f"test_{item_id}", item_id, source_url
                )
                pipeline.ensure_note_output(note, resolved["knowledge"], item_id, source_url)
                now = pipeline.utc_now()
                connection.execute(
                    "UPDATE items SET status='completed', output_path=?, completed_at=?, updated_at=? WHERE aweme_id=?",
                    (str(note.resolve()), now, now, item_id),
                )
                connection.commit()
                index = pipeline.rebuild_index(connection, resolved["knowledge"])
                self.assertIn("测试视频", index.read_text(encoding="utf-8"))

            temp = pipeline.guarded_temp_path(resolved["tmp"], item_id, create=True)
            (temp / "video.mp4").write_bytes(b"temporary")
            self.assertTrue(temp.is_dir())
            import shutil

            shutil.rmtree(temp)
            self.assertFalse(temp.exists())

    def test_schema_migration_adds_published_at(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            workspace = Path(name)
            runtime = workspace / ".douyin-kb"
            runtime.mkdir()
            db = runtime / "state.sqlite3"
            with closing(sqlite3.connect(db)) as connection:
                connection.executescript(
                    """
                    CREATE TABLE items (
                        aweme_id TEXT PRIMARY KEY,
                        source_url TEXT NOT NULL,
                        title TEXT NOT NULL DEFAULT '',
                        author TEXT NOT NULL DEFAULT '',
                        favorite_folder TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'pending',
                        attempts INTEGER NOT NULL DEFAULT 0,
                        discovered_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        completed_at TEXT,
                        output_path TEXT,
                        error TEXT
                    );
                    """
                )
            pipeline.initialize(workspace)
            with closing(sqlite3.connect(db)) as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(items)")}
            self.assertIn("published_at", columns)

    def test_error_redaction(self) -> None:
        redacted = pipeline.redact_error(
            "request https://example.com/path?token=secret authorization=abcdef123456"
        )
        self.assertNotIn("secret", redacted)
        self.assertNotIn("abcdef", redacted)


if __name__ == "__main__":
    unittest.main()
