from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from helpers import write_valid_bundle  # noqa: E402
from validate_note import validate_note_bundle  # noqa: E402


class NoteValidationTests(unittest.TestCase):
    def test_valid_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            note_dir = Path(name)
            item_id = "7653821390349722021"
            source = f"https://www.douyin.com/video/{item_id}"
            write_valid_bundle(note_dir, item_id, source)
            self.assertEqual(validate_note_bundle(note_dir, item_id, source), [])

    def test_missing_heading_and_mismatched_id(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            note_dir = Path(name)
            item_id = "7653821390349722021"
            source = f"https://www.douyin.com/video/{item_id}"
            note = write_valid_bundle(note_dir, item_id, source)
            note.write_text(
                note.read_text(encoding="utf-8").replace("## 时间轴证据", "## 其他"),
                encoding="utf-8",
            )
            errors = validate_note_bundle(note_dir, "9999999999999999999", source)
            self.assertTrue(any("时间轴证据" in error for error in errors))
            self.assertTrue(any("aweme_id" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
