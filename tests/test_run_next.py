from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pipeline  # noqa: E402
import run_next  # noqa: E402


class RunNextTests(unittest.TestCase):
    def test_api_failure_falls_back_to_browser_and_enqueues(self) -> None:
        item_id = "7653821390349722021"
        item = {
            "aweme_id": item_id,
            "source_url": f"https://www.douyin.com/video/{item_id}",
            "title": "测试",
            "author": "作者",
        }
        with tempfile.TemporaryDirectory() as name:
            workspace = Path(name)
            downloader = workspace / "douyin-downloader"
            downloader.mkdir()
            config = downloader / "config.yml"
            config.write_text("test: true", encoding="utf-8")
            argv = [
                "run_next.py",
                "--workspace",
                str(workspace),
                "--downloader-root",
                str(downloader),
                "--config",
                str(config),
            ]
            completed = SimpleNamespace(returncode=0)
            with (
                patch.object(sys, "argv", argv),
                patch.object(run_next, "discover", AsyncMock(side_effect=RuntimeError("HTTP 403"))),
                patch.object(run_next, "discover_in_browser", AsyncMock(return_value=[item])),
                patch.object(run_next.subprocess, "run", return_value=completed),
                patch("builtins.print") as output,
            ):
                self.assertEqual(run_next.main(), 0)
            with pipeline.db_session(pipeline.paths(workspace)["db"]) as connection:
                row = connection.execute("SELECT * FROM items WHERE aweme_id=?", (item_id,)).fetchone()
            self.assertIsNotNone(row)
            messages = "\n".join(str(call.args[0]) for call in output.call_args_list if call.args)
            self.assertIn('"backend": "browser"', messages)


if __name__ == "__main__":
    unittest.main()
