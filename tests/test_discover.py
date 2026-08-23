from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import discover  # noqa: E402


class FakeConfigLoader:
    def __init__(self, _path: str):
        pass

    def get_cookies(self):
        return {"sessionid": "[TEST_VALUE]"}

    def get(self, _name: str):
        return None


class FakeLoginRequiredError(Exception):
    status_msg = "login required"


class FakeClient:
    calls: list[int] = []

    def __init__(self, *_args, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get_user_collection(self, _uid: str, max_cursor: int, count: int):
        self.calls.append(max_cursor)
        if max_cursor == 0:
            return {
                "items": [{"aweme_id": "7653821390349722021", "desc": "known"}],
                "has_more": True,
                "max_cursor": 20,
            }
        return {
            "items": [{"aweme_id": "7653821390349722022", "desc": "new"}],
            "has_more": False,
            "max_cursor": 0,
        }


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_paginates_past_known_items(self) -> None:
        config_module = types.ModuleType("config")
        config_module.ConfigLoader = FakeConfigLoader
        core_module = types.ModuleType("core")
        core_module.DouyinAPIClient = FakeClient
        core_module.LoginRequiredError = FakeLoginRequiredError
        FakeClient.calls = []
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            config = root / "config.yml"
            config.write_text("test: true", encoding="utf-8")
            args = SimpleNamespace(
                downloader_root=root,
                config=config,
                limit=1,
                include_folders=False,
                exclude_ids={"7653821390349722021"},
            )
            with patch.dict(sys.modules, {"config": config_module, "core": core_module}):
                items = await discover.discover(args)
        self.assertEqual([item["aweme_id"] for item in items], ["7653821390349722022"])
        self.assertEqual(FakeClient.calls, [0, 20])


if __name__ == "__main__":
    unittest.main()
