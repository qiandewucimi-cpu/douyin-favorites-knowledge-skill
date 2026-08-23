---
name: ingest-douyin-favorites
description: Ingest unprocessed videos from an authenticated Douyin favorites collection into local Markdown knowledge notes with full timestamped transcripts, up to five keyframes, Chinese OCR, visual evidence, resumable SQLite state, and temporary-media cleanup. Use when the user asks to整理、拆解、继续处理、重试或归档抖音收藏内容。Do not use for generic bulk video archiving, reposting, or downloading media for redistribution.
---

# Ingest Douyin Favorites

Turn Douyin favorites into durable local knowledge while keeping original videos only as short-lived processing inputs.

## Non-negotiable rules

- Process one item at a time and checkpoint after every item.
- Never retain an original video or extracted audio after a successful note is finalized.
- Keep the full timestamped transcript and no more than five useful keyframes.
- Keep source URLs, author metadata, timestamps, and uncertainty notes for traceability.
- Never print, commit, or copy Douyin cookies or API tokens into notes or logs.
- Stop and ask the user to refresh login when authentication or CAPTCHA blocks discovery.
- Do not mark an item `completed` until the final Markdown and transcript exist.

## Resolve paths

Treat the current project directory as `WORKSPACE` unless the user supplies another directory.

- Runtime state: `WORKSPACE/.douyin-kb/state.sqlite3`
- Managed temporary files: `WORKSPACE/.douyin-kb/tmp/<item-id>/`
- Final notes: `WORKSPACE/knowledge/douyin/`

Resolve this skill directory from the loaded `SKILL.md`; do not assume a user-level installation path.

## Workflow

1. Read [references/pipeline.md](references/pipeline.md) before changing backends, discovery behavior, state transitions, or cleanup logic.
2. Read [references/note-schema.md](references/note-schema.md) before writing final notes.
3. Run `scripts/doctor.py --workspace WORKSPACE`. Report missing dependencies; do not silently install large models or external services.
4. Initialize runtime state with `scripts/pipeline.py --workspace WORKSPACE init`.
5. Discover favorites through `scripts/discover.py`. If its authenticated API returns 403, use `scripts/discover_browser.py`, which accepts only a successful `listcollection` or `collects/video/list` response. Never enqueue bare page links, recommendations, search results, or any entry without collection API evidence. Start with `--limit 1` for a live test.
6. Prefer one `scripts/run_next.py` call to discover if needed, claim, acquire, transcribe, and extract frames. It automatically falls back to a headless cookie-backed favorites page when the direct collection API is blocked or empty. Use `--profile fast` by default: request the lowest available video rendition, use fast transcription, screen 24 candidates with text-region change heuristics, retain at most five, and run PP-OCRv5 mobile OCR on each retained frame. If the lowest rendition has no audio track, retry that item at 720p; when 720p is also silent, skip Whisper and use balanced frame sampling plus OCR. A narrow persistent permission for this exact script is preferable to repeated broad approvals. Use `prepare_next.py` when discovery has already been handled.
   Use `balanced` only when embedded text is important. Use `full` only when the user explicitly prioritizes fidelity over speed; it uses the larger OCR model. Use `launch_acquire.py` and `check_acquire.py` separately only for diagnosis or recovery. Never invoke the downloader's full configured link list or read raw acquisition logs unless diagnosing a sanitized local error.
7. Keep the complete timestamped transcript and model cache under `WORKSPACE/.douyin-kb/models/`.
8. Use whole-frame and text-region changes to retain at most five ranked, near-duplicate-free frames. Run Chinese OCR on every retained frame and create `visual-evidence.json`. Before synthesis, run `scripts/evidence_brief.py` and use its compact output; open the full evidence JSON only when OCR confidence or diagnostics are needed. This avoids spending model context on OCR coordinates and per-character scores. If OCR degrades, inspect the retained frames directly and record the OCR failure.
   If the failure is temporary or model-related, fix the environment and run `scripts/retry_ocr.py` on the retained frames without reacquiring media.
9. Inspect every retained frame. Combine speech, OCR, and visual evidence into the note template; never treat unconfirmed OCR text as fact.
10. Write `transcript.md` and `note.md` atomically. Run `scripts/validate_note.py` against the final directory, then mark the item complete. Completion validates metadata, required sections, transcript identity, visual evidence, and the five-frame limit, and refreshes `knowledge/douyin/index.md`.
11. Delete only that item's managed temporary directory. Continue until the queue is empty or a stop condition is reached.

## Queue commands

Use the Python available to the current environment:

```powershell
python scripts/doctor.py --workspace "WORKSPACE"
python scripts/pipeline.py --workspace "WORKSPACE" init
python scripts/discover.py --downloader-root "WORKSPACE/douyin-downloader" --config "WORKSPACE/douyin-downloader/config.yml" --limit 1 --output "WORKSPACE/.douyin-kb/discovery.jsonl"
python scripts/discover_browser.py --downloader-root "WORKSPACE/douyin-downloader" --config "WORKSPACE/douyin-downloader/config.yml" --limit 1 --output "WORKSPACE/.douyin-kb/discovery.jsonl"
python scripts/pipeline.py --workspace "WORKSPACE" enqueue --jsonl "WORKSPACE/.douyin-kb/discovery.jsonl"
python scripts/pipeline.py --workspace "WORKSPACE" enqueue --url "DOUYIN_URL"
python scripts/pipeline.py --workspace "WORKSPACE" status
python scripts/pipeline.py --workspace "WORKSPACE" claim
python scripts/run_next.py --workspace "WORKSPACE" --downloader-root "WORKSPACE/douyin-downloader" --config "WORKSPACE/douyin-downloader/config.yml" --profile fast
python scripts/prepare_next.py --workspace "WORKSPACE" --downloader-root "WORKSPACE/douyin-downloader" --config "WORKSPACE/douyin-downloader/config.yml" --profile fast
python scripts/launch_acquire.py --workspace "WORKSPACE" --item-id "ITEM_ID" --downloader-root "WORKSPACE/douyin-downloader" --config "WORKSPACE/douyin-downloader/config.yml" --url "DOUYIN_URL"
python scripts/check_acquire.py --workspace "WORKSPACE" --item-id "ITEM_ID" --wait-seconds 30
python scripts/transcribe.py --input "TEMP_VIDEO" --output "FINAL_NOTE_DIR/transcript.md" --model-dir "WORKSPACE/.douyin-kb/models/whisper" --preset fast
python scripts/analyze_frames.py --input "TEMP_VIDEO" --frames-dir "FINAL_NOTE_DIR/frames" --ocr-output "FINAL_NOTE_DIR/visual-evidence.json" --workspace "WORKSPACE" --max-frames 5 --profile fast --selection-mode text-aware --ocr-model fast
python scripts/retry_ocr.py --frames-dir "FINAL_NOTE_DIR/frames" --evidence "FINAL_NOTE_DIR/visual-evidence.json" --workspace "WORKSPACE" --ocr-model fast
python scripts/evidence_brief.py --evidence "FINAL_NOTE_DIR/visual-evidence.json"
python scripts/validate_note.py --note-dir "FINAL_NOTE_DIR" --aweme-id "ITEM_ID" --source-url "DOUYIN_URL"
python scripts/pipeline.py --workspace "WORKSPACE" complete ITEM_ID --output "NOTE_PATH"
python scripts/pipeline.py --workspace "WORKSPACE" fail ITEM_ID --error "ERROR"
python scripts/pipeline.py --workspace "WORKSPACE" skip ITEM_ID --reason "REASON"
python scripts/pipeline.py --workspace "WORKSPACE" retry --all
python scripts/pipeline.py --workspace "WORKSPACE" cleanup ITEM_ID
```

Use `enqueue --jsonl FILE` for discovery output. Each line may include `aweme_id`, `source_url`, `title`, `author`, and `favorite_folder`.

## Stop conditions

Stop the run without losing completed work when:

- login expires or CAPTCHA requires user action;
- free disk space is below the configured safety threshold;
- the same infrastructure error repeats three times consecutively;
- final output cannot be written safely;
- the user asks to stop.

For a single unavailable or deleted item, record a failure and continue.

## Current implementation boundary

The bundled scripts implement authenticated discovery, environment diagnostics, a resumable SQLite queue, one-command single-item preparation, low-bandwidth acquisition, local timestamped transcription, ranked keyframe extraction, Chinese OCR, retries, and cleanup. Treat OCR as supporting evidence and keep Agent frame inspection in the loop.
