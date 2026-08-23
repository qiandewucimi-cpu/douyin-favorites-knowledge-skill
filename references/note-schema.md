# Markdown knowledge-note schema

## Required files

Each completed item contains:

- `note.md`: structured knowledge and evidence.
- `transcript.md`: complete timestamped transcript.
- `visual-evidence.json`: selected-frame timestamps, OCR output, and OCR failure details.
- `frames/`: zero to five selected evidence images.

## Required frontmatter

```yaml
---
title: ""
source: "douyin"
source_url: ""
aweme_id: ""
author: ""
favorite_folder: ""
published_at: ""
processed_at: ""
tags: []
confidence: "medium"
---
```

Use `high`, `medium`, or `low` for confidence. Leave unknown source metadata empty instead of inventing it.

## Required sections

1. `# 一句话摘要`
2. `## 核心观点`
3. `## 方法与步骤`
4. `## 画面中的重要信息`
5. `## 案例、数据与原话`
6. `## 可执行行动`
7. `## 待验证与不确定内容`
8. `## 时间轴证据`
9. `## 来源`

Omit empty bullets, but keep the section heading and state `无` when absence matters.

## Evidence rules

- Attach a timestamp to factual claims derived from the video whenever possible.
- Distinguish the creator's claim from verified fact.
- Do not promote OCR guesses into facts without visual confirmation.
- Link retained frames with relative Markdown paths such as `frames/00-37.jpg`.
- Quote sparingly; preserve meaning and identify paraphrases.
- Record contradictions between speech and visuals.
- Do not infer products, people, places, or numbers when the frame is unclear.

## Transcript rules

`transcript.md` must contain source metadata followed by every recognized segment:

```markdown
# 完整转写

- 来源：<URL>
- 作品 ID：<ID>

## 转写正文

[00:00:00.000 --> 00:00:04.200] 文本
```

Do not silently rewrite the transcript into polished prose. Put corrections or uncertain words in brackets.
