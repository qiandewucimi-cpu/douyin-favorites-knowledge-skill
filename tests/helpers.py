from __future__ import annotations

import json
from pathlib import Path

HEADINGS = (
    "# 一句话摘要",
    "## 核心观点",
    "## 方法与步骤",
    "## 画面中的重要信息",
    "## 案例、数据与原话",
    "## 可执行行动",
    "## 待验证与不确定内容",
    "## 时间轴证据",
    "## 来源",
)


def write_valid_bundle(note_dir: Path, aweme_id: str, source_url: str) -> Path:
    note_dir.mkdir(parents=True, exist_ok=True)
    body = "\n\n".join(f"{heading}\n\n测试内容" for heading in HEADINGS)
    (note_dir / "note.md").write_text(
        "\n".join(
            (
                "---",
                'title: "测试笔记"',
                'source: "douyin"',
                f'source_url: "{source_url}"',
                f'aweme_id: "{aweme_id}"',
                'author: "测试作者"',
                'favorite_folder: ""',
                'published_at: "2026-01-01"',
                'processed_at: "2026-01-02"',
                "tags: []",
                'confidence: "medium"',
                "---",
                "",
                body,
                "",
            )
        ),
        encoding="utf-8",
    )
    (note_dir / "transcript.md").write_text(
        f"# 完整转写\n\n- 来源：{source_url}\n- 作品 ID：{aweme_id}\n\n## 转写正文\n\n（无音轨）\n",
        encoding="utf-8",
    )
    (note_dir / "visual-evidence.json").write_text(
        json.dumps({"frames": []}, ensure_ascii=False), encoding="utf-8"
    )
    return note_dir / "note.md"
