from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import audit_release  # noqa: E402


class ReleaseAuditTests(unittest.TestCase):
    def make_release(self, root: Path) -> None:
        for relative in audit_release.REQUIRED:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("placeholder\n", encoding="utf-8")
        (root / "SKILL.md").write_text(
            "---\n"
            "name: ingest-douyin-favorites\n"
            "description: Test release.\n"
            "---\n\n# Skill\n",
            encoding="utf-8",
        )

    def test_clean_tree_and_private_artifact_detection(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.make_release(root)
            self.assertEqual(audit_release.audit(root), [])
            (root / "cookies.json").write_text("{}", encoding="utf-8")
            self.assertTrue(any("private runtime file" in item for item in audit_release.audit(root)))

    def test_quoted_cookie_value_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.make_release(root)
            key = "session" + "id"
            value = "not-a-real-value-1234567890"
            (root / "sample.txt").write_text(f'"{key}": "{value}"', encoding="utf-8")
            self.assertTrue(any("possible secret" in item for item in audit_release.audit(root)))


if __name__ == "__main__":
    unittest.main()
