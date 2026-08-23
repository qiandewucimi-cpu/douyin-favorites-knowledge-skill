#!/usr/bin/env python3
"""Create a timestamped Markdown transcript using local faster-whisper."""
from __future__ import annotations

import argparse
from pathlib import Path


def stamp(seconds: float) -> str:
    whole, ms = divmod(max(0, int(round(seconds * 1000))), 1000)
    h, rem = divmod(whole, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02}:{m:02}:{s:02}.{ms:03}"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--model-dir", required=True, type=Path)
    p.add_argument("--model", default="base")
    p.add_argument("--preset", choices=("fast", "balanced", "accurate"), default="fast")
    a = p.parse_args()
    if not a.input.is_file():
        raise SystemExit(f"input not found: {a.input}")
    import av

    with av.open(str(a.input)) as container:
        has_audio = bool(container.streams.audio)
    if not has_audio:
        lines = [
            "# 完整转写",
            "",
            "- 语言：无",
            f"- 转写预设：{a.preset}",
            "- 说明：源视频未检测到音轨，完整转写为空；请以关键帧和 OCR 为主要证据。",
            "",
            "## 转写正文",
            "",
            "（无音轨）",
        ]
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print({"segments": 0, "no_audio": True, "output": str(a.output.resolve())})
        return 0
    from faster_whisper import WhisperModel
    a.model_dir.mkdir(parents=True, exist_ok=True)
    model = WhisperModel(a.model, device="cpu", compute_type="int8", download_root=str(a.model_dir))
    beam_size = {"fast": 1, "balanced": 3, "accurate": 5}[a.preset]
    segments, info = model.transcribe(
        str(a.input),
        language="zh",
        vad_filter=True,
        beam_size=beam_size,
        condition_on_previous_text=a.preset != "fast",
    )
    lines = [
        "# 完整转写",
        "",
        f"- 语言：{info.language}",
        f"- 转写预设：{a.preset}",
        "",
        "## 转写正文",
        "",
    ]
    count = 0
    for seg in segments:
        text = (seg.text or "").strip()
        if text:
            lines.append(f"[{stamp(seg.start)} --> {stamp(seg.end)}] {text}")
            count += 1
    if not count:
        lines.append("（检测到音轨，但未识别出可转写语音）")
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print({"segments": count, "output": str(a.output.resolve())})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
