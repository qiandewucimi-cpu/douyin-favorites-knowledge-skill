from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analyze_frames import choose_frames, timestamp  # noqa: E402
from evidence_brief import build_brief  # noqa: E402


class EvidenceAndFrameTests(unittest.TestCase):
    def test_evidence_brief_deduplicates_text(self) -> None:
        payload = {
            "frames": [
                {"file": "a.jpg", "timestamp_seconds": 1, "ocr_text": ["合同", " 押金 "]},
                {"file": "b.jpg", "timestamp_seconds": 2, "ocr_text": ["合同", "租金"]},
            ]
        }
        brief = build_brief(payload)
        self.assertEqual(brief["ocr_line_count"], 4)
        self.assertEqual(brief["unique_ocr_line_count"], 3)
        self.assertEqual(brief["frames"][1]["ocr_text"], ["租金"])

    def test_text_aware_selection_respects_limit(self) -> None:
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            self.skipTest("Pillow is not installed")
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            candidates = []
            for index in range(12):
                image = Image.new("RGB", (320, 180), (25 + index * 5, 30, 35))
                ImageDraw.Draw(image).text((20, 120), f"section {index}", fill="white")
                path = root / f"{index:02}.jpg"
                image.save(path)
                candidates.append(path)
            selected = choose_frames(candidates, 120.0, 5, 3.0, "text-aware")
            self.assertGreaterEqual(len(selected), 1)
            self.assertLessEqual(len(selected), 5)
            self.assertEqual([item[1] for item in selected], sorted(item[1] for item in selected))
            self.assertEqual(timestamp(65.2), "00-01-05")


if __name__ == "__main__":
    unittest.main()
