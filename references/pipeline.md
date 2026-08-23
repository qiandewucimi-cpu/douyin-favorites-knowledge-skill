# Pipeline contract

## Architecture

Keep acquisition, media analysis, knowledge synthesis, and storage separate:

1. **Discovery** reads authenticated Douyin favorites and emits metadata without retaining media.
2. **Queue** deduplicates by `aweme_id` and checkpoints each state transition in SQLite.
3. **Acquisition** places one source video in the managed per-item temporary directory.
4. **Analysis** creates a timestamped transcript, scene-change frames, OCR, and a merged timeline.
5. **Synthesis** writes grounded Markdown using the note schema.
6. **Cleanup** removes only managed temporary media after outputs are durable.

## Backend choices

- Reuse the local `douyin-downloader` checkout for authentication, favorite discovery, signatures, and metadata parsing. Do not invoke its bulk archival workflow.
- Use `scripts/analyze_frames.py` for local whole-frame and text-region change scoring, temporal spacing, near-duplicate rejection, and a hard five-frame limit. Screen candidates with image heuristics; do not run full OCR on every candidate. Feed the Agent `scripts/evidence_brief.py` output by default and load the full evidence JSON only for confidence or OCR diagnostics.
- Default to the `fast` profile: request the lowest available video rendition, use faster-whisper beam size 1, screen 24 frame candidates, run PP-OCRv5 mobile OCR on every retained frame, and retain Agent visual inspection.
- If the lowest rendition has no audio track, retry that item at 720p. If 720p is also silent, skip Whisper inference and automatically use balanced frame sampling plus OCR; visual text is then the primary evidence.
- Use local PaddleOCR in every standard profile. Use PP-OCRv5 mobile models in fast and balanced profiles, and the larger default model in full mode. OCR is supporting evidence; if it fails, continue with Agent visual inspection and record the failure.
- Prefer local faster-whisper for speech recognition. Allow a cloud transcription backend only as an explicit future option.
- Let the active Agent synthesize notes from the transcript, OCR, and selected frames; do not hard-code a separate summarization API.

## State transitions

```text
pending -> processing -> completed
                    \-> failed -> pending
```

- Increment `attempts` when claiming an item.
- Preserve `completed` items during rediscovery.
- Reset stale `processing` rows only through an explicit recovery operation.
- Store concise errors without cookies, signed URLs, headers, or tokens.

## Processing order

Process sequentially by default. Unlimited means "continue until the queue is empty," not "load every item into one model context" and not "download all media concurrently."

For every item:

1. Run `run_next.py` so one permission-scoped command discovers when the queue is empty, falls back to a headless cookie-backed browser when the direct API is blocked or empty, claims the row atomically, and executes steps 2-5. Use `prepare_next.py` only when discovery is already complete.
2. Create `tmp/<item-id>/` under the marked managed temp root.
3. Acquire the lowest available rendition in fast mode and allow downloader candidate rotation within its item deadline.
4. Transcribe with timestamps using the selected speed preset.
5. Extract and rank visual candidates; run Chinese OCR on every retained frame.
6. Keep at most five final frames.
7. Read the compact `evidence_brief.py` output and visually inspect every retained frame. Open `visual-evidence.json` only when detailed OCR confidence or geometry is needed.
8. Write outputs to a staging name in the final directory.
9. Rename staging outputs into place and validate the complete note bundle.
10. Mark the row complete and rebuild `knowledge/douyin/index.md`.
11. Remove the item's managed temp directory.

## Output layout

```text
knowledge/douyin/
├── index.md
└── YYYY/
    └── <safe-title>_<aweme-id>/
        ├── note.md
        ├── transcript.md
        ├── visual-evidence.json
        └── frames/
            └── HH-MM-SS.jpg
```

Do not retain `video.mp4`, extracted audio, model caches, or raw signed download URLs inside the final note directory.

## Failure policy

- Authentication or CAPTCHA: stop the run and request user action.
- Deleted/private item: mark failed or skipped and continue.
- Transcription failure: mark failed; do not produce a confident summary from visuals alone unless the source is intentionally silent.
- OCR failure: continue with frame inspection and note the missing OCR evidence.
- Cleanup failure: keep the item completed, report the exact managed temp path, and retry cleanup later.
- Repeated infrastructure failure: stop after three consecutive items fail for the same reason.
- A quiet or temporarily unchanged `.tmp` file is not itself a failure. Trust the tracked terminal status; do not terminate before the downloader's candidate rotation and item deadline finish.

## Security

- Keep cookies in an ignored local configuration or browser profile.
- Redact query strings from signed media URLs in logs.
- Never place secrets in SQLite error fields or Markdown frontmatter.
- Restrict deletion to children of a temp root containing the marker created by `pipeline.py init`.
