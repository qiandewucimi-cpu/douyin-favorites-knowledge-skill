#!/usr/bin/env python3
"""Select informative video frames and optionally run local Chinese OCR."""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def timestamp(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02}-{minutes:02}-{secs:02}"


def ffmpeg_backend() -> tuple[str, Any]:
    executable = shutil.which("ffmpeg")
    if executable:
        import imageio_ffmpeg  # type: ignore

        return executable, imageio_ffmpeg
    import imageio_ffmpeg  # type: ignore

    return imageio_ffmpeg.get_ffmpeg_exe(), imageio_ffmpeg


def image_features(path: Path) -> tuple[Any, Any, float, float]:
    from PIL import Image, ImageFilter, ImageStat

    with Image.open(path) as source:
        rgb = source.convert("RGB")
        vector = rgb.resize((64, 64))
        gray = vector.convert("L")
        detail = rgb.resize((160, 90)).convert("L")
        # Most subtitles, slides, chat messages, and UI labels occupy the
        # middle/lower area. Comparing their edge maps catches text changes
        # that look like duplicates in a coarse whole-frame thumbnail.
        text_region = detail.crop((0, 16, 160, 90)).filter(ImageFilter.FIND_EDGES)
        contrast = ImageStat.Stat(gray).stddev[0] / 128.0
        edge = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).mean[0] / 255.0
        return vector, text_region, min(1.0, contrast), min(1.0, edge)


def visual_difference(left: Any, right: Any) -> float:
    from PIL import ImageChops, ImageStat

    means = ImageStat.Stat(ImageChops.difference(left, right)).mean
    return sum(means) / (len(means) * 255.0)


def choose_frames(
    candidates: list[Path],
    duration: float,
    limit: int,
    minimum_gap: float,
    selection_mode: str,
) -> list[tuple[Path, float, dict[str, float]]]:
    if not candidates:
        raise RuntimeError("ffmpeg produced no frame candidates")
    interval = duration / max(1, len(candidates))
    vectors: list[Any] = []
    text_vectors: list[Any] = []
    scored: list[tuple[float, int, float, float, float]] = []
    previous = None
    previous_text = None
    for index, candidate in enumerate(candidates):
        vector, text_vector, contrast, edge = image_features(candidate)
        difference = visual_difference(previous, vector) if previous is not None else 0.0
        text_difference = visual_difference(previous_text, text_vector) if previous_text is not None else 0.0
        seconds = min(duration, (index + 0.5) * interval)
        if selection_mode == "legacy":
            score = 0.68 * difference + 0.20 * contrast + 0.12 * edge
        else:
            score = 0.50 * difference + 0.28 * text_difference + 0.14 * contrast + 0.08 * edge
        vectors.append(vector)
        text_vectors.append(text_vector)
        scored.append((score, index, seconds, difference, text_difference))
        previous = vector
        previous_text = text_vector

    selected: list[tuple[int, float, float, float, float]] = []
    effective_gap = max(minimum_gap, duration / max(1, limit * 3))
    for score, index, seconds, difference, text_difference in sorted(scored, reverse=True):
        if any(abs(seconds - kept_seconds) < effective_gap for _, kept_seconds, *_ in selected):
            continue
        duplicate = any(
            visual_difference(vectors[index], vectors[kept_index]) < 0.045
            and (
                selection_mode == "legacy"
                or visual_difference(text_vectors[index], text_vectors[kept_index]) < 0.035
            )
            for kept_index, *_ in selected
        )
        if duplicate:
            continue
        selected.append((index, seconds, score, difference, text_difference))
        if len(selected) == limit:
            break

    if len(selected) < limit:
        for fraction in ((i + 1) / (limit + 1) for i in range(limit)):
            index = min(len(candidates) - 1, int(fraction * len(candidates)))
            seconds = min(duration, (index + 0.5) * interval)
            if any(index == kept_index for kept_index, *_ in selected):
                continue
            if any(abs(seconds - kept_seconds) < effective_gap / 2 for _, kept_seconds, *_ in selected):
                continue
            duplicate = any(
                visual_difference(vectors[index], vectors[kept_index]) < 0.045
                and (
                    selection_mode == "legacy"
                    or visual_difference(text_vectors[index], text_vectors[kept_index]) < 0.035
                )
                for kept_index, *_ in selected
            )
            if duplicate:
                continue
            score, _, _, difference, text_difference = scored[index]
            selected.append((index, seconds, score, difference, text_difference))
            if len(selected) == limit:
                break
    return [
        (
            candidates[index],
            seconds,
            {
                "selection_score": round(score, 6),
                "visual_change": round(difference, 6),
                "text_region_change": round(text_difference, 6),
            },
        )
        for index, seconds, score, difference, text_difference in sorted(selected, key=lambda item: item[1])
    ]


def nested_values(value: Any, wanted: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == wanted and isinstance(child, list):
                found.extend(child)
            else:
                found.extend(nested_values(child, wanted))
    elif isinstance(value, list):
        for child in value:
            found.extend(nested_values(child, wanted))
    return found


def result_payload(result: Any) -> Any:
    value = getattr(result, "json", result)
    if callable(value):
        value = value()
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value


def run_ocr(
    frames: list[dict[str, Any]], cache_dir: Path, model_profile: str = "fast"
) -> tuple[str, str | None]:
    # Paddle's Windows inference layer can fail on absolute paths containing
    # non-ASCII characters. A workspace-relative cache path avoids that issue.
    os.environ["PADDLE_PDX_CACHE_HOME"] = os.path.relpath(cache_dir.resolve(), Path.cwd())
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    try:
        from paddleocr import PaddleOCR  # type: ignore

        engine_options: dict[str, Any] = {}
        if model_profile == "fast":
            engine_options.update(
                text_detection_model_name="PP-OCRv5_mobile_det",
                text_recognition_model_name="PP-OCRv5_mobile_rec",
            )
        else:
            engine_options["lang"] = "ch"
        engine = PaddleOCR(
            enable_mkldnn=False,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            **engine_options,
        )
        for frame in frames:
            texts: list[str] = []
            scores: list[float] = []
            for result in engine.predict(frame["absolute_path"]):
                payload = result_payload(result)
                texts.extend(str(text).strip() for text in nested_values(payload, "rec_texts") if str(text).strip())
                for score in nested_values(payload, "rec_scores"):
                    try:
                        scores.append(float(score))
                    except (TypeError, ValueError):
                        pass
            frame["ocr_text"] = texts
            frame["ocr_scores"] = scores
        return "paddleocr", None
    except Exception as exc:  # OCR is allowed to degrade to visual inspection.
        for frame in frames:
            frame["ocr_text"] = []
            frame["ocr_scores"] = []
        return "unavailable", f"{type(exc).__name__}: {exc}"[:500]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--frames-dir", required=True, type=Path)
    parser.add_argument("--ocr-output", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--max-frames", type=int, default=5)
    parser.add_argument("--profile", choices=("fast", "balanced", "full"), default="fast")
    parser.add_argument("--sample-count", type=int)
    parser.add_argument("--min-gap", type=float, default=3.0)
    parser.add_argument("--selection-mode", choices=("text-aware", "legacy"), default="text-aware")
    parser.add_argument("--ocr-model", choices=("fast", "accurate"), default="fast")
    parser.add_argument("--skip-ocr", action="store_true")
    args = parser.parse_args()

    video = args.input.resolve()
    workspace = args.workspace.resolve()
    frames_dir = args.frames_dir.resolve()
    ocr_output = args.ocr_output.resolve()
    if not video.is_file():
        raise SystemExit(f"input not found: {video}")
    if not 1 <= args.max_frames <= 5:
        raise SystemExit("--max-frames must be between 1 and 5")
    existing = [path for path in frames_dir.glob("*") if path.suffix.lower() in IMAGE_SUFFIXES] if frames_dir.exists() else []
    if existing:
        raise SystemExit(f"frames directory already contains {len(existing)} image(s): {frames_dir}")

    ffmpeg, imageio_ffmpeg = ffmpeg_backend()
    _, duration = imageio_ffmpeg.count_frames_and_secs(str(video))
    if not duration or duration <= 0:
        raise RuntimeError("could not determine video duration")
    requested_samples = args.sample_count or {"fast": 24, "balanced": 36, "full": 48}[args.profile]
    sample_count = max(
        args.max_frames * 3,
        min(requested_samples, max(args.max_frames * 3, math.ceil(duration / 2))),
    )
    sample_interval = max(0.25, duration / sample_count)
    runtime_dir = workspace / ".douyin-kb"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    frames_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="frame-analysis-", dir=runtime_dir) as temp_name:
        candidate_pattern = Path(temp_name) / "candidate-%04d.jpg"
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-vf",
            f"fps=1/{sample_interval:.6f},scale='min(720,iw)':-2",
            "-q:v",
            "3",
            str(candidate_pattern),
        ]
        subprocess.run(command, check=True)
        candidates = sorted(Path(temp_name).glob("candidate-*.jpg"))
        selected = choose_frames(candidates, duration, args.max_frames, args.min_gap, args.selection_mode)
        manifest: list[dict[str, Any]] = []
        used_names: set[str] = set()
        for candidate, seconds, diagnostics in selected:
            base_name = f"{timestamp(seconds)}.jpg"
            name = base_name
            counter = 2
            while name in used_names:
                name = f"{Path(base_name).stem}-{counter}.jpg"
                counter += 1
            used_names.add(name)
            destination = frames_dir / name
            shutil.copy2(candidate, destination)
            manifest.append(
                {
                    "file": name,
                    "timestamp_seconds": round(seconds, 3),
                    "absolute_path": str(destination),
                    **diagnostics,
                }
            )

    backend = "skipped"
    error = None
    if not args.skip_ocr:
        backend, error = run_ocr(manifest, runtime_dir / "models" / "paddlex", args.ocr_model)
    for frame in manifest:
        frame.pop("absolute_path", None)
    payload = {
        "duration_seconds": round(duration, 3),
        "profile": args.profile,
        "selection_mode": args.selection_mode,
        "candidate_count": len(candidates),
        "selection": "sampled scene-change, text-region change, contrast, edge density, temporal spacing, duplicate rejection",
        "ocr_backend": backend,
        "ocr_model": args.ocr_model if not args.skip_ocr else "skipped",
        "ocr_error": error,
        "frames": manifest,
    }
    ocr_output.parent.mkdir(parents=True, exist_ok=True)
    temporary = ocr_output.with_suffix(ocr_output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(ocr_output)
    print(json.dumps({"frames": len(manifest), "ocr_backend": backend, "output": str(ocr_output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
