from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import analyze_frames  # noqa: E402
import pipeline  # noqa: E402
from helpers import write_valid_bundle  # noqa: E402


class SmokePipelineTests(unittest.TestCase):
    def test_synthetic_video_to_valid_completed_bundle(self) -> None:
        try:
            ffmpeg, _ = analyze_frames.ffmpeg_backend()
        except Exception as exc:
            self.skipTest(f"ffmpeg is unavailable: {exc}")
        with tempfile.TemporaryDirectory() as name:
            workspace = Path(name)
            video = workspace / "synthetic.mp4"
            generated = subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=320x240:rate=10",
                    "-t",
                    "2",
                    "-pix_fmt",
                    "yuv420p",
                    str(video),
                ],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
            )
            if generated.returncode:
                self.skipTest(f"synthetic ffmpeg source is unavailable: {generated.stderr}")

            resolved = pipeline.paths(workspace)
            pipeline.initialize(workspace)
            item_id = "7653821390349722021"
            source = f"https://www.douyin.com/video/{item_id}"
            with pipeline.db_session(resolved["db"]) as connection:
                pipeline.enqueue_one(connection, {"source_url": source, "title": "合成测试"})
                connection.commit()
                pipeline.claim_next(connection)

            note_dir = resolved["knowledge"] / "2026" / f"synthetic_{item_id}"
            note = write_valid_bundle(note_dir, item_id, source)
            transcript = note_dir / "transcript.md"
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "transcribe.py"),
                    "--input",
                    str(video),
                    "--output",
                    str(transcript),
                    "--model-dir",
                    str(workspace / ".douyin-kb" / "models" / "whisper"),
                    "--preset",
                    "fast",
                ],
                check=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
            )
            transcript_text = transcript.read_text(encoding="utf-8")
            transcript.write_text(
                transcript_text.replace(
                    "# 完整转写\n",
                    f"# 完整转写\n\n- 来源：{source}\n- 作品 ID：{item_id}\n",
                    1,
                ),
                encoding="utf-8",
            )
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "analyze_frames.py"),
                    "--input",
                    str(video),
                    "--frames-dir",
                    str(note_dir / "frames"),
                    "--ocr-output",
                    str(note_dir / "visual-evidence.json"),
                    "--workspace",
                    str(workspace),
                    "--max-frames",
                    "3",
                    "--sample-count",
                    "9",
                    "--skip-ocr",
                ],
                check=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "pipeline.py"),
                    "--workspace",
                    str(workspace),
                    "complete",
                    item_id,
                    "--output",
                    str(note),
                ],
                check=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertIn('"completed"', completed.stdout)
            self.assertTrue((resolved["knowledge"] / "index.md").is_file())


if __name__ == "__main__":
    unittest.main()
