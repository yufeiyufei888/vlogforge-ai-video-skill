---
name: travel-vlog-pipeline
description: "Batch travel, city-walk, restaurant-review, and food Vlog editing for folders of raw video. Use when Codex must inventory many clips, inspect frames and speech, classify travel/food story roles, build an arrival-to-exit narrative, create a reviewable storyboard, compile a MaxAzure render_config, render versioned MP4 files, or run FFmpeg QA on Windows."
---

# Travel Vlog Pipeline

## Overview

Turn a folder of raw travel or restaurant footage into a reviewable story plan and a versioned MP4. Use the pinned MaxAzure source for project bootstrap, rendering, preflight, and QA. Use the Vlog rules layer only for visual taxonomy, pacing, and narrative order.

## Architecture Rules

- Keep this skill as the only discoverable entry point. Treat both repositories under `.vendor/` as implementation dependencies, not independently invoked skills.
- Invoke every pipeline command through `scripts/run_pipeline.ps1`; direct `pipeline.py` execution is unsupported. Before Python starts, the launcher rejects local bytecode and reparse points, clears inherited Python path/home hooks, and uses isolated `-I -S -B` source bootstrapping.
- Verify each complete pinned vendor tree by path, size, file count, and content hash before setup and every vendor execution. Vendor `__pycache__`, `.pyc`, and `.pyo` files are forbidden so unbound bytecode can never be imported.
- Bind the integrity verifier and exact installed Python distribution/version set into the runtime and approval bundle; a post-setup distribution/version-set change is a hard failure.
- Let MaxAzure own source inventory, transcript-shaped render inputs, single-pass rendering, versioned outputs, preflight, and post-render QA.
- Let this skill own travel/food classification, story coverage, speech-boundary repair, proxy normalization, and compilation to MaxAzure artifacts.
- Never run the rendering snippets from `vlog-auto-edit`; they are reference material, not the active renderer.
- Never modify the user's originals. Use `copy` as the default import mode and write only inside the edit project. Use hardlinks only when the user explicitly requests them and understands the shared-inode risk.
- Do not upload footage or extracted frames to a third-party visual API without explicit consent. Local FFmpeg extraction and local faster-whisper are the default.
- Do not approve or render the full master after story review alone. Normalize, compile, preflight, render a 5-8 second technical preview, and review the compiled artifacts plus preview before approval.
- Bind approval to the exact integrity bundle computed by the pipeline. It covers story-review evidence, inventory and analysis, selected sources and proxies, compiled subtitle/transcript, timeline, BGM, render config, compile report, locked runtime/code/profile inputs, and the hashed technical-preview artifacts. Never hand-author or edit an approval receipt.
- Never overwrite a prior master. Keep `versioned_output` enabled.
- Reject project paths or project-tree entries that are symlinks, junctions, or other reparse points. All origin, work, verify, and output artifacts must remain physically inside the project.
- Bind the complete generated story-review tree, including thumbnails and storyboard frames, not only its HTML entry points.
- Serialize renders with the project render lock and accept only the unique nonce receipt for that invocation, a newly created output in the requested version family, and an empty bridge failure field.

## Workflow

### 1. Check the Runtime

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<skill-dir>\scripts\run_pipeline.ps1" doctor --json
```

Required: Python 3.12+, FFmpeg, FFprobe, pinned MaxAzure source, and pinned Vlog rules source. Read [windows-runtime.md](references/windows-runtime.md) if a requirement is missing.

### 2. Bootstrap the Project

Choose `food` for restaurant/food-review footage and `travel` for trip/city-walk footage. Use a new edit-project directory, separate from the source folder.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<skill-dir>\scripts\run_pipeline.ps1" prepare `
  --source <footage-folder> `
  --project <edit-project> `
  --profile food `
  --title <title> `
  --target-duration 120 `
  --mode copy
```

This creates the MaxAzure project structure, a copied and hashed source inventory, `work/clip_analysis.json`, and a frame-review manifest. Keep `copy` as the default. Originals remain untouched.

### 3. Analyze Only What Is Needed

Run frame extraction first:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<skill-dir>\scripts\run_pipeline.ps1" frames `
  --analysis <edit-project>\work\clip_analysis.json `
  --out <edit-project>\work\review_frames
```

Inspect representative frames and update each clip's `visual`, `labels`, and quality fields. `prepare` does not select new clips for ASR by default. For each clip whose speech matters, set `labels.needs_transcript` to `true`, then run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<skill-dir>\scripts\run_pipeline.ps1" transcribe `
  --analysis <edit-project>\work\clip_analysis.json `
  --project <edit-project> `
  --language zh `
  --model small `
  --device cpu --compute-type int8
```

Use `--all` only when the user explicitly wants every audio-bearing clip transcribed. Do not transcribe silent B-roll merely because an audio track exists. Read [artifact-contract.md](references/artifact-contract.md) before hand-editing analysis JSON.

### 4. Classify and Build the Story

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<skill-dir>\scripts\run_pipeline.ps1" classify `
  --analysis <edit-project>\work\clip_analysis.json `
  --profile food

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<skill-dir>\scripts\run_pipeline.ps1" plan `
  --analysis <edit-project>\work\clip_analysis.json `
  --profile food `
  --target-duration 120 `
  --output <edit-project>\work\story_plan.json
```

Treat rule classification as a first pass. Correct important roles after visual review. For food Vlogs, preserve arrival to exit, retain environment and people, show dishes in greater detail, and use restrained motion only on suitable food shots. Never invent a missing visit stage. See [narrative-rules.md](references/narrative-rules.md).

### 5. Review the Story

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<skill-dir>\scripts\run_pipeline.ps1" review `
  --analysis <edit-project>\work\clip_analysis.json `
  --plan <edit-project>\work\story_plan.json `
  --footage <edit-project>\origin\raw `
  --out <edit-project>\verify\story_review
```

Open `storyboard/index.html` and `dashboard.html`. Resolve coverage gaps, bad selections, repeated moments, speech cuts, and ordering issues. A successful review also writes `work/story_review_manifest.json`, binding the current analysis, story plan, selected candidate IDs, and the complete dashboard/storyboard review tree by hash and file count. If any of them changes, rerun `review`. Story review authorizes the next compile cycle; it is not final render approval.

### 6. Normalize Selected Sources and Compile

Normalize only selected sources so mixed phone resolutions, rotation metadata, frame rates, and missing audio do not break FFmpeg concat:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<skill-dir>\scripts\run_pipeline.ps1" normalize `
  --plan <edit-project>\work\story_plan.json `
  --project <edit-project> `
  --width 1920 --height 1080 --fps 30 --fit contain
```

Then compile one source of truth:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<skill-dir>\scripts\run_pipeline.ps1" compile `
  --analysis <edit-project>\work\clip_analysis.json `
  --plan <edit-project>\work\story_plan.json `
  --project <edit-project> `
  --proxy-map <edit-project>\work\proxy_map.json
```

The compiler writes `vlog_timeline.json`, `compiled_transcript.json`, `render_config.json`, and `compile_report.json`. Do not hand-maintain a second timeline. See [artifact-contract.md](references/artifact-contract.md).

### 7. Preflight and Render a Technical Preview

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<skill-dir>\scripts\run_pipeline.ps1" preflight --project <edit-project>

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<skill-dir>\scripts\run_pipeline.ps1" render `
  --project <edit-project> --preview-seconds 8
```

Treat the preview as a technical smoke test, not creative approval. If preflight or preview fails, correct the story plan or inputs, then normalize and compile again as needed.

The preview command runs strict preflight again and writes `work/render_config_preview.json`, `work/compiled_transcript_preview.json`, `work/technical_preview.json`, and a versioned preview MP4 under `output/`. The receipt binds the preview config, preview transcript, output MP4, source render config, and pre-preview integrity bundle by hash. It is valid only when status and full decode are `pass` and the MP4 is H.264/yuv420p with AAC 48 kHz stereo for the requested 5-8 seconds. Do not edit these artifacts.

### 8. Review the Compiled Bundle and Preview

Review all of the following together:

- `work/story_plan.json`
- `work/story_review_manifest.json` and its exact dashboard/storyboard outputs
- `work/proxy_map.json` and every selected proxy
- `work/vlog_timeline.json`
- `work/compiled_transcript.json`
- `work/render_config.json`
- `work/compile_report.json`
- the exact BGM file, or verified absence of BGM in `render_config.json`
- `work/render_config_preview.json`
- `work/compiled_transcript_preview.json`
- `work/technical_preview.json` and its exact preview MP4

Confirm ordering, selected intervals, subtitle text, proxy/source identity, motion events, audio intent, and coverage gaps. Do not approve while any executable or preview artifact remains unreviewed.

### 9. Approve the Exact Integrity Bundle

Only after the compiled artifacts and preview have been reviewed, record approval:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<skill-dir>\scripts\run_pipeline.ps1" approve `
  --project <edit-project> `
  --plan <edit-project>\work\story_plan.json `
  --reviewer user
```

Approval writes a `travel-vlog-story-approval/2` receipt for the canonical `work/story_plan.json`. It blocks when a selected clip is not visually reviewed, a role remains ambiguous, the story-review manifest is stale, a compiled/runtime integrity check fails, or the technical preview and its receipt no longer match. The receipt records the current plan hash, base and preview-inclusive bundle hashes, approved artifact hashes, accepted compile warnings, and the exact accepted coverage-gap set.

If the reviewed plan intentionally lacks a reported visit stage, add `--accept-gaps`. Never add that flag without the user's explicit acceptance of those gaps. Do not edit `story_approval.json`; rerun `approve` after a fresh review cycle.

After approval, any reviewed analysis/plan/dashboard/storyboard, source, proxy, subtitle/transcript, timeline, BGM, render config, compile report, preview receipt/config/transcript/MP4, runtime manifest, upstream lock, profile, or bound pipeline-code change makes the receipt stale. Repeat the affected upstream steps, strict preflight, technical preview, compiled-bundle review, and approval.

### 10. Render the Full Master and Run QA

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<skill-dir>\scripts\run_pipeline.ps1" render `
  --project <edit-project>

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<skill-dir>\scripts\run_pipeline.ps1" qa `
  --project <edit-project> `
  --video <rendered-master> `
  --platform bilibili
```

The full render writes `work/last_render.json` with the exact output path and hash, approval receipt hash, and approved bundle hash. QA accepts only that attributed MP4 inside the project `output/` directory while the approval bundle is still current. It writes `verify/qa/<video-sha-prefix>/final_qa.json`; only upstream QA status `pass` plus a successful strict full decode returns success. `warn` is not a passing release result, and human review remains required.

For final acceptance, inspect representative shots and every cut, listen at normal speed, check the second half for sync drift, verify no unintended black frames, and complete a full-file decode. Use [acceptance-checklist.md](references/acceptance-checklist.md).

## Stop Conditions

Stop before full render when any of these holds:

- The user has not reviewed the story order and then approved the exact compiled integrity bundle.
- `story_review_manifest.json`, its selected IDs, dashboard, or storyboard does not match the current analysis and plan.
- Required source files are missing, or source/proxy hashes changed after bundle review.
- A vendor file changed, a forbidden vendor bytecode cache exists, the integrity verifier changed, or the installed Python distribution/version set differs from runtime setup.
- The project path or any entry in its tree is a symlink, junction, or other reparse point.
- A cut is outside source duration or still bisects speech.
- Food Vlog arrival-to-exit gaps exist and the user has not accepted the missing coverage.
- Proxy normalization, MaxAzure preflight, or the 5-8 second preview fails.
- The preview receipt, preview config, preview transcript, or preview MP4 is missing or stale.
- Any bound review artifact, source, proxy, subtitle/transcript, timeline, BGM, render config, compile report, runtime/toolchain lock, profile, or pipeline-code byte changed after approval.
- The QA target does not match the current full-render receipt by path and SHA-256, or the approval bundle changed after rendering.
- The current approval receipt bytes do not match the approval-receipt SHA-256 recorded by the full render.
- Adding BGM or AI narration would fill no demonstrated narrative gap.

## References

- [artifact-contract.md](references/artifact-contract.md): normalized analysis, story-plan, timeline, and render artifacts.
- [narrative-rules.md](references/narrative-rules.md): travel/food taxonomy, pacing, coverage, and review rules.
- [windows-runtime.md](references/windows-runtime.md): project-local Python, FFmpeg, and optional ASR setup.
- [acceptance-checklist.md](references/acceptance-checklist.md): review and delivery gates.
- [upstream.md](references/upstream.md): pinned source provenance, responsibilities, and licensing notes.
