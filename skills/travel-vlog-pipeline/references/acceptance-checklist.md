# Acceptance Checklist

This checklist governs the existing MP4 renderer. Native-draft delivery follows [jianying-native-draft.md](jianying-native-draft.md) instead and does not require proxy normalization or renderer approval receipts. General review, speech preservation and measured-source export-bitrate requirements apply to both branches; see [editing-preferences.md](editing-preferences.md).

## Before Integrity Approval

- Source inventory exists and reviewed source files still exist.
- Visual labels were checked against frames, not inferred only from filenames.
- Story order was reviewed by the user before normalization and compilation.
- `work/story_review_manifest.json` is ready and still matches the current analysis, plan, selected candidate IDs, dashboard, and storyboard hashes.
- The complete story-review tree hash and file count still match; no thumbnail or storyboard frame was added, removed, or changed.
- The project path and complete project tree contain no symlink, junction, linked file, or other reparse point.
- Complete vendor-tree records, the integrity verifier, and the installed Python distribution/version inventory still match runtime setup; no vendor bytecode cache or reparse point exists.
- The secure launcher hash matches runtime setup, and the local skill contains no `__pycache__`, `.pyc`, or `.pyo` entry before launch.
- Every selected clip has `visual_reviewed: true` and no selected clip still has `needs_role_review: true`.
- Missing food/travel coverage is either resolved or explicitly accepted.
- Every selected interval is inside source duration.
- Speech-boundary repair reports zero remaining cut-through issues.
- Selected sources were normalized to one resolution, fps, pixel format, audio sample rate, and channel layout.
- MaxAzure edit preflight passes.
- A 5-8 second preview renders, decodes, and has expected audio.
- Preview status and full-decode status are `pass`, with H.264/yuv420p video and AAC 48 kHz stereo audio.
- `technical_preview.json`, `render_config_preview.json`, `compiled_transcript_preview.json`, and the preview MP4 still match their recorded hashes and the current base bundle.
- The user reviewed `story_plan.json`, `story_review_manifest.json`, `proxy_map.json`, selected proxies, `vlog_timeline.json`, `compiled_transcript.json`, `render_config.json`, `compile_report.json`, the BGM state, and the exact preview artifacts as one bundle.
- The approval receipt uses schema `travel-vlog-story-approval/2` and binds the reviewed artifacts, media, runtime/lock/profile/code inputs, preview artifacts, accepted compile warnings, and exact accepted coverage gaps.

## Before Full Render

- The exact compiled integrity bundle has explicit user approval.
- Any accepted coverage gaps are recorded in that approval.
- Recompute and verify the approval bundle immediately before rendering.
- Stop if any bound review artifact, selected source, proxy, subtitle/transcript, timeline, BGM, render config, compile report, preview artifact, runtime/lock/profile, or pipeline-code identity or hash differs from the approved receipt.

## Approval Invalidation

Any post-approval change to a bound review artifact, selected source, proxy, subtitle/transcript, timeline, BGM state, render config, compile report, preview receipt/config/transcript/MP4, runtime manifest, upstream lock, profile, or bound pipeline code invalidates approval. A story-plan edit also invalidates all artifacts compiled from it. Repeat the affected upstream steps, strict preflight and technical preview, review the new bundle, and obtain a new approval before full rendering.

## Before QA

- `work/last_render.json` exists with schema `travel-vlog-render/2`, identifies a non-preview render, and matches the target MP4 path and SHA-256.
- The target MP4 is inside the project `output/` directory.
- The unique render-bridge nonce receipt identifies a newly created output in the requested version family and contains no failure.
- The current preview-inclusive integrity bundle still matches approval v2 and the bundle recorded by the full-render receipt.
- The current `story_approval.json` byte hash exactly matches the approval-receipt hash captured by the full render.
- Run QA before changing any approved artifact or media; otherwise rerender from a newly approved bundle.

## After Full Render

- FFprobe confirms expected container, codecs, dimensions, fps, duration, and audio.
- FFmpeg completes a full-file decode with no fatal error.
- MaxAzure QA reports `pass`; `warn` is a non-passing release result.
- No unintended black frames, frozen sections, long silence, clipped dialogue, or missing tail audio.
- Watch representative frame sequences at every cut.
- Listen at normal speed, including the second half and ending.
- Food detail remains readable; environment and people still establish the visit.
- BGM ducks under speech and does not hide reactions or room tone.
- The final MP4 uses a new versioned filename and the prior master remains intact.
- `verify/qa/<video-sha-prefix>/final_qa.json` uses schema `travel-vlog-final-qa/2` and binds the video, integrity bundle, full-render receipt, and upstream QA report by hash.

Automated QA is evidence, not final visual or editorial acceptance.
