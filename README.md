# 抖音收藏知识提取 Skill

[![CI](https://github.com/qiandewucimi-cpu/douyin-favorites-knowledge-skill/actions/workflows/ci.yml/badge.svg)](https://github.com/qiandewucimi-cpu/douyin-favorites-knowledge-skill/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

把已登录抖音账号的收藏视频转换为本地 Markdown 知识笔记：保留完整时间戳转写、最多 5 张关键帧、中文 OCR 和可追溯的视觉证据；成功归档后删除临时原视频。

## 能做什么

- 从抖音收藏夹发现尚未处理的视频
- 使用可恢复的 SQLite 队列逐条处理，避免重复
- 本地 faster-whisper 转写
- 使用文字区域感知的关键帧筛选
- 对最终关键帧运行中文 PaddleOCR
- 输出 `note.md`、`transcript.md`、`visual-evidence.json` 和最多 5 张图片
- 处理成功后清理该条视频的临时媒体

## 目录约定

发布包根目录直接包含 `SKILL.md`，可以整体上传到 GitHub。使用 Codex 的 Skill 安装器时，选择这个仓库根目录即可；也可以把整个文件夹复制到目标工作区的 `.agents/skills/ingest-douyin-favorites/`。默认还需要一个同级的 `douyin-downloader/` 目录作为收藏发现和媒体获取后端。

个人登录信息、下载缓存、模型缓存和知识库内容均属于本地数据，不应提交到公开仓库。

直接安装为项目专用 Skill：

```powershell
git clone https://github.com/qiandewucimi-cpu/douyin-favorites-knowledge-skill.git `
  .agents/skills/ingest-douyin-favorites
```

也可以让 Codex 的 Skill 安装器从仓库根目录安装；仓库根目录就是 Skill 根目录，不需要再选择子文件夹。

## 环境要求

- Python 3.9 或更高版本
- 可用的 FFmpeg，或 Python 包 `imageio-ffmpeg`
- `faster-whisper`
- `paddleocr` 与对应的 PaddlePaddle 运行时
- 已配置并登录的 `douyin-downloader`
- 至少 5 GB 可用磁盘空间（模型首次下载还需要额外空间）

## 一键安装

在这个文件夹所在目录打开 PowerShell，运行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

脚本会创建工作区虚拟环境、安装依赖、下载独立的 `douyin-downloader`，并从示例配置生成本地 `config.yml`。登录抖音和处理收藏属于用户自己的本地步骤，脚本不会代替用户输入账号信息。

首次安装会下载 Whisper、PaddleOCR/PaddlePaddle 和 Chromium 运行依赖，耗时取决于网络，并可能占用数 GB 磁盘；模型文件随后复用。知识笔记完成后原视频会自动删除，但模型缓存和虚拟环境会保留，以避免每次重复下载。

安装完成后，在本发布包目录运行诊断：

```powershell
& .\.venv\Scripts\python.exe .\scripts\doctor.py --workspace .
```

如果你想把运行数据放到另一个工作区，或已经自己准备好了下载器：

```powershell
.\install.ps1 -Workspace "C:\你的工作区" -SkipDownloaderClone
```

macOS 或 Linux：

```bash
chmod +x ./install.sh
./install.sh
```

指定工作区或跳过下载器克隆：

```bash
./install.sh --workspace /path/to/workspace --skip-downloader-clone
```

手动安装 Python 依赖时：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r .\requirements.txt
```

如果 PaddlePaddle 在你的平台没有匹配的预编译包，请先按照 [PaddlePaddle 官方安装说明](https://www.paddlepaddle.org.cn/install/quick) 安装对应版本，再重新安装其余依赖。

如果把本目录复制到 `.agents/skills/ingest-douyin-favorites/`，则在工作区根目录运行只读诊断：

```powershell
python .agents/skills/ingest-douyin-favorites/scripts/doctor.py --workspace .
```

## 使用方式

以下命令假设当前目录就是这个发布包目录，并且 `install.ps1` 已经执行完成：

```powershell
& .\.venv\Scripts\python.exe .\scripts\pipeline.py --workspace . init
& .\.venv\Scripts\python.exe .\scripts\discover.py `
  --downloader-root ./douyin-downloader `
  --config ./douyin-downloader/config.yml `
  --limit 1 `
  --output ./.douyin-kb/discovery.jsonl
& .\.venv\Scripts\python.exe .\scripts\pipeline.py --workspace . enqueue --jsonl ./.douyin-kb/discovery.jsonl
& .\.venv\Scripts\python.exe .\scripts\run_next.py `
  --workspace . `
  --downloader-root ./douyin-downloader `
  --config ./douyin-downloader/config.yml `
  --profile fast
```

常用模式：

- `fast`：最低可用画质、快速转写、文字感知选帧、移动版 OCR，适合批量处理。
- `balanced`：更适合合同、课件等文字密集视频。
- `full`：使用较大 OCR 模型，优先准确度，速度较慢。

## 输出

默认输出到 `knowledge/douyin/<年份>/<标题>_<aweme_id>/`：

- `note.md`：结构化摘要、核心观点、行动清单和时间轴
- `transcript.md`：完整时间戳转写，不改写原始识别文本
- `visual-evidence.json`：关键帧、OCR、选择分数和诊断信息
- `frames/`：最多 5 张保留的关键帧

Agent 整理笔记时可先运行 `scripts/evidence_brief.py`，读取去重后的紧凑 OCR 文本；完整 JSON 仍保留在本地供追溯和诊断。

## 性能参考

在一条 7 分 26 秒视频上，画面分析阶段由约 122–136 秒降至约 57 秒。移动版 OCR 的文字量基本持平，但置信度可能略低；需要更高准确度时切换到 `full`。

网络下载和本地 CPU/GPU 会显著影响总耗时。脚本不会长期保存原视频，单条处理完成后会清理对应的临时目录。

脚本本身只负责发现、下载、转写、OCR、选帧和输出校验，不调用额外的总结 API。最终 Markdown 由正在运行该 Skill 的 Agent 根据紧凑证据生成，因此 Token 消耗主要取决于转写长度；OCR 坐标和逐字置信度不会默认塞入上下文。

## 开发与验证

提交前运行：

```powershell
python scripts/audit_release.py --root .
python -m ruff check scripts tests
python -m unittest discover -s tests -v
```

测试覆盖发布隐私审计、队列迁移、URL 去敏、分页发现、浏览器回退、OCR 证据、笔记校验，以及由合成视频驱动的无音轨端到端烟雾流程。GitHub Actions 会在 Python 3.9 和 3.12 上重复这些检查；当前 Windows 隔离安装也已在 Python 3.13 上验证。

## 隐私、版权与账号安全

- 仅处理用户本人有权访问和整理的收藏内容。
- Cookie、`config.yml`、数据库、模型缓存、原视频和个人知识库都不应公开上传。
- 不要把 Cookie、API Token 或原始下载日志复制到 Issue、日志或笔记中。
- 生成的 Markdown 是内容整理工具的结果，不构成法律、医疗或财务建议。
- 使用抖音及相关依赖项目时，应遵守其服务条款、版权规则和当地法律。

## 开源边界

本 Skill 的脚本和说明按本目录许可证发布。`douyin-downloader` 是独立依赖，保留其原作者版权和许可证；不要把它的许可证、Cookie 或本地运行数据混入本 Skill 的版权声明。

发布时建议只提交本 Skill 目录及必要的项目说明；不要直接提交当前工作区中的 `.douyin-kb/`、`knowledge/`、Cookie、下载数据库或模型缓存。
