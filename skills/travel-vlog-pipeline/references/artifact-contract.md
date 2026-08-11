# Artifact Contract

## `clip_analysis.json`

The reader accepts either a top-level array compatible with `vlog-auto-edit` or this normalized object:

```json
{
  "schema_version": "travel-vlog-analysis/1",
  "project": {"title": "Example", "profile": "food", "target_duration_s": 120},
  "clips": [
    {
      "file": "C:/edit/origin/raw/clip001.mp4",
      "duration": 12.4,
      "width": 1920,
      "height": 1080,
      "fps": 30,
      "visual": [{"time": 3.0, "description": "店铺门头和排队人群", "shot_type": "全景", "camera": "手持", "mood": "热闹", "tags": ["storefront", "queue"]}],
      "audio": {"has_speech": true, "mean_volume_db": -22.5, "transcript": [{"start": 1.2, "end": 3.8, "text": "我们到了"}]},
      "preprocessing": {"mode": "normal", "recommended_range": [0.5, 11.8], "skip_zones": []},
      "labels": {"story_role": "exterior", "content_class": "scenery", "quality": 0.82, "keep": true, "human_override": false, "needs_transcript": true}
    }
  ]
}
```

`classify` never overwrites a `human_override: true` role. Visual descriptions and quality decisions should be based on inspected frames, not filenames alone.

`prepare` initializes new clips without selecting them for ASR. After frame review, set `labels.needs_transcript: true` only on clips whose speech affects story, subtitle, or cut decisions. A normal `transcribe` run processes those marked clips, plus clips already known to contain speech. Use `transcribe --all` only as an explicit all-audio override.

## `story_plan.json`

The plan remains compatible with the upstream storyboard generators and adds structured metadata:

```json
{
  "schema_version": "travel-vlog-story/1",
  "title": "Example",
  "profile": "food",
  "structure": [
    {
      "id": "s01",
      "act": 1,
      "role": "opening",
      "section": "抵达 — 走进这家店",
      "description": "建立地点和到店过程",
      "clips": [{"file": "C:/edit/origin/raw/clip001.mp4", "start": 0.5, "end": 4.2, "note": "店铺门头和排队人群", "subtitle": "我们到了", "story_role": "exterior", "content_class": "scenery", "motion_hint": null}]
    }
  ],
  "coverage": {"missing": [], "present": ["exterior"]},
  "warnings": []
}
```

The order of `structure[].clips[]` is authoritative after user review.

## `story_review_manifest.json`

A successful `review` writes `work/story_review_manifest.json` with schema `travel-vlog-story-review/1`. It hashes the current `clip_analysis.json`, `story_plan.json`, compatibility analysis, generated dashboard, generated storyboard, and the complete review tree (HTML, thumbnails, and storyboard frames), and records the selected candidate IDs in plan order. Integrity checks block if the manifest is missing, a review artifact moved outside the project `verify/` directory or changed, the analysis or plan hash changed, or the selected IDs no longer match. Rerun `review` after any such change.

## Compiled Artifacts

`compile` writes:

- `work/vlog_timeline.json`: source and program time mapping with section and classification metadata.
- `work/compiled_transcript.json`: synthetic MaxAzure transcript segments. Each segment preserves one selected source interval and subtitle text.
- `work/render_config.json`: the only executable render configuration.
- `work/compile_report.json`: boundary repairs, coverage warnings, source/proxy mapping, and duration totals.

Do not edit both story plan and render config after compile. Change the story plan, rerun compile, review the diff, and rerun preflight.

## Integrity Bundle and Approval

Treat approval as a digest-bound decision over one executable bundle, not as approval of the story-plan filename alone. The reviewed bundle includes:

- `work/source_inventory.json`
- `work/clip_analysis.json`
- `work/story_review_manifest.json` and its dashboard/storyboard hashes
- `work/story_plan.json`
- selected source identities and hashes from the source inventory
- `work/proxy_map.json` and the identities and hashes of selected proxies
- `work/vlog_timeline.json`
- `work/compiled_transcript.json`, including subtitle text and timing
- `work/render_config.json`
- `work/compile_report.json`
- the selected BGM identity and hash from `origin/bgm`, or the absence of BGM in the hashed render config
- the runtime manifest, installed distribution inventory, upstream lock, complete vendor-tree records, food and travel profiles, and bound secure launcher/pipeline/core/render-bridge/runtime-integrity code

Preflight verifies the base bundle without requiring a preview. It also verifies that the current process uses the Python, FFmpeg, and FFprobe recorded by runtime schema `travel-vlog-runtime/2`, and that the package lock and upstream script snapshot still match.

The technical preview adds these hash-bound artifacts to the approval bundle:

- `work/technical_preview.json`, schema `travel-vlog-render/2`
- `work/render_config_preview.json`
- `work/compiled_transcript_preview.json`
- the exact preview MP4 under `output/`

The preview receipt must match the current base-bundle hash and source `render_config.json` hash, and its recorded preview config, preview transcript, and output hashes must match their current bytes. Its status and full decode must be `pass`; the 5-8 second MP4 must satisfy the H.264, yuv420p, AAC, 48 kHz, and stereo media contract.

Run story review before normalization and compilation. Run preflight and a 5-8 second technical preview after compilation. Review the compiled artifacts and preview together, then approve that exact integrity bundle before full rendering.

Approval writes schema `travel-vlog-story-approval/2` for the canonical `work/story_plan.json`. It records the plan hash, preview-inclusive bundle hash, base-bundle hash, approved artifact hashes, accepted compile warnings, and exact accepted coverage gaps. Validation recomputes the current gap set and bundle; a mismatch blocks full render and QA.

Any change after approval to a bound review artifact, selected source, proxy, subtitle/transcript, timeline, BGM choice or bytes, render config, compile report, preview receipt/config/transcript/MP4, runtime manifest, upstream lock, profile, or bound code invalidates the approval receipt. A story-plan change also invalidates the compiled bundle. Re-run the affected upstream steps, strict preflight and technical preview, review the new bundle, and obtain a new approval.

## Render and QA Receipts

A technical preview writes `work/technical_preview.json`. Each render is serialized by `work/.render.lock` and receives a unique nonce receipt under `work/render-results/`; the orchestrator verifies its schema, nonce, requested output, newly created actual output, version family, return code, and empty failure field. A full render writes `work/last_render.json`, also with schema `travel-vlog-render/2`, and records the exact output path and SHA-256, source config and plan hashes, approved bundle hash, approval-receipt hash, renderer-bridge result hash, media probe, and full-decode result.

`qa` accepts only an MP4 inside the project `output/` directory whose path and SHA-256 match the current full-render receipt. It rebuilds the preview-inclusive integrity bundle, revalidates approval v2, checks that the full render used that same bundle, and requires the current approval-receipt bytes to match the approval SHA-256 captured during full render. The report is written to `verify/qa/<video-sha-prefix>/final_qa.json` with schema `travel-vlog-final-qa/2` and hashes for the video, current bundle, full-render receipt, and upstream QA report. Only strict full decode plus upstream status `pass` succeeds; `warn` returns a non-passing result. Human review is always still required.

## Time Rules

- `0 <= start < end <= source_duration`
- Plan times are rounded to 0.1 seconds.
- Timeline times are derived from selected source duration; do not hand-enter them.
- Proxy normalization must preserve source duration and timestamps closely enough that existing cuts remain valid.
- Any changed bound artifact, media file, runtime/lock/profile input, or bound code invalidates downstream approval and QA evidence.
