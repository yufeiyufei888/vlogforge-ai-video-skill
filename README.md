# VlogForge AI

**A production-grade AI video editing skill for travel, city-walk, restaurant, and food Vlogs.**

[![CI](https://github.com/yufeiyufei888/vlogforge-ai-video-skill/actions/workflows/ci.yml/badge.svg)](https://github.com/yufeiyufei888/vlogforge-ai-video-skill/actions/workflows/ci.yml)
![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![Windows](https://img.shields.io/badge/Windows-supported-0078D4?logo=windows)
![FFmpeg](https://img.shields.io/badge/FFmpeg-local-007808?logo=ffmpeg&logoColor=white)
[![GitHub stars](https://img.shields.io/github/stars/yufeiyufei888/vlogforge-ai-video-skill?style=social)](https://github.com/yufeiyufei888/vlogforge-ai-video-skill/stargazers)

[中文说明](README.zh-CN.md) · [Skill entry](skills/travel-vlog-pipeline/SKILL.md) · [Architecture](#how-it-works) · [Contributing](CONTRIBUTING.md)

VlogForge AI turns a folder of raw footage into a reviewable story plan and a versioned final video. It combines narrative-aware clip classification, selective local transcription, storyboard review, media normalization, deterministic rendering, integrity-bound approval, and automated FFmpeg QA in one Codex-compatible skill.

It is built for creators and engineers who want AI-assisted editing without surrendering editorial control or silently uploading private footage.

## Why VlogForge AI?

Most “one-click” editors hide how clips were selected, where speech was cut, or whether the final file was actually decoded. VlogForge AI treats editing as an auditable pipeline:

- **Story before render** — build and review the arrival-to-exit narrative before producing the master.
- **Local-first media handling** — frame extraction, FFmpeg processing, and optional faster-whisper ASR run locally.
- **Human approval gates** — a storyboard review is not treated as permission to render the final video.
- **Reproducible outputs** — sources, proxies, subtitles, timeline, BGM state, preview, and runtime are bound by hashes.
- **Versioned delivery** — prior masters are preserved instead of overwritten.
- **Evidence-based QA** — metadata checks, strict full-file decode, cut review, audio review, and upstream QA are separate acceptance layers.

## Features

| Stage | What it does |
|---|---|
| Ingest | Copies and hashes raw media without changing the originals |
| Analyze | Extracts representative frames and selectively transcribes speech-bearing clips |
| Structure | Classifies travel/food roles and builds a reviewable story plan |
| Review | Generates storyboard and dashboard artifacts for human inspection |
| Normalize | Converts selected phone footage to consistent resolution, FPS, pixel format, and audio layout |
| Compile | Produces one canonical timeline, transcript, render config, and compile report |
| Preview | Renders a 5–8 second technical smoke test before final approval |
| Approve | Binds reviewed inputs and generated artifacts into an integrity receipt |
| Render | Creates a new versioned MP4 through the pinned rendering backbone |
| Verify | Runs FFprobe, strict FFmpeg decode, artifact attribution, and release QA |

## Supported stories

- Travel Vlogs and trip recaps
- City walks and destination diaries
- Restaurant reviews and food Vlogs
- Arrival-to-exit visit narratives
- Mixed phone footage with inconsistent rotation, frame rate, resolution, or audio

The current release is Windows-first and targets local H.264/AAC workflows. WSL is not required.

## Quick start

### Requirements

- Windows 10/11
- PowerShell 5.1+
- Python 3.12+
- `curl.exe` and Windows `tar.exe`
- Enough local storage for FFmpeg, optional ASR models, proxies, and rendered media

### 1. Clone

```powershell
git clone https://github.com/yufeiyufei888/vlogforge-ai-video-skill.git
Set-Location .\vlogforge-ai-video-skill
```

### 2. Bootstrap the pinned local workspace

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap-workspace.ps1
```

Add `-WithAsr` to install the pinned faster-whisper stack:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap-workspace.ps1 -WithAsr
```

The bootstrap downloads the two pinned upstream source snapshots directly from their owners, verifies the complete extracted trees, creates a project-local Python environment, and installs a pinned FFmpeg build. Upstream source is kept under the ignored `.vendor/` directory and is never redistributed by this repository.

### 3. Use the skill

Open the cloned repository in Codex and invoke the skill at:

```text
skills/travel-vlog-pipeline/SKILL.md
```

Example request:

```text
Use $travel-vlog-pipeline to turn D:\Footage\Qingdao-Food-Trip into a
reviewable two-minute food Vlog. Keep the full arrival-to-exit story,
preserve the originals, and stop for review before the full render.
```

The skill is intentionally workspace-local: keep the skill, `.vendor`, `.venv`, and `.tools` under the same cloned repository so the secure launcher can verify the full runtime boundary.

## How it works

```mermaid
flowchart LR
    A["Raw footage"] --> B["Inventory and hash"]
    B --> C["Frames and selective ASR"]
    C --> D["Classify and plan story"]
    D --> E["Storyboard review"]
    E --> F["Normalize and compile"]
    F --> G["Technical preview"]
    G --> H["Integrity approval"]
    H --> I["Versioned render"]
    I --> J["Decode and QA"]
```

The skill uses one discoverable entry point and keeps detailed contracts in `references/`, deterministic behavior in `scripts/`, and reusable profiles or locks in `assets/`.

## Repository layout

```text
vlogforge-ai-video-skill/
├── skills/travel-vlog-pipeline/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── assets/
│   ├── references/
│   ├── scripts/
│   └── tests/
├── scripts/bootstrap-workspace.ps1
├── .github/
├── README.md
└── README.zh-CN.md
```

## Privacy and safety

- Original footage is preserved; `copy` is the default import mode.
- Footage and extracted frames are not sent to a third-party visual API without explicit consent.
- Local bytecode caches, symlinks, junctions, and unpinned vendor changes fail closed.
- The full render is blocked until the exact compiled bundle and technical preview are reviewed and approved.
- Automated checks are evidence, not a replacement for watching and listening to the final cut.

## Upstream boundary

VlogForge AI integrates two pinned upstream projects at runtime:

- [`maxazure/video-editing-skill`](https://github.com/maxazure/video-editing-skill) — rendering and QA backbone. The inspected snapshot did not include a root license, so its code is downloaded locally and is **not** redistributed here.
- [`znyupup/ai-video-editing-skill`](https://github.com/znyupup/ai-video-editing-skill) — Vlog narrative reference, available under MIT in the inspected snapshot.

Exact commits, tree hashes, file counts, and responsibility boundaries are recorded in [`upstream-lock.json`](skills/travel-vlog-pipeline/assets/upstream-lock.json) and [`upstream.md`](skills/travel-vlog-pipeline/references/upstream.md).

## Validation

Run the local unit suite:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
py -3 -m unittest discover -s .\skills\travel-vlog-pipeline\tests -v
```

The repository CI runs the same suite on Python 3.12. Real release acceptance additionally requires the pinned runtime, a technical preview, representative visual/audio review, and a full-file decode.

## Roadmap

- Linux/macOS runtime support
- More story profiles beyond travel and food
- A small public demo dataset with reproducible expected artifacts
- Optional vertical-video and short-form delivery profiles
- Easier project-local skill discovery and installation

## Contributing

Issues and focused pull requests are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before changing the artifact contracts, approval boundary, or runtime integrity model.

If VlogForge AI helps your workflow, consider starring the repository so more creators and agent builders can find it.
