# Native Jianying original-reference branch

This is an alternative to rendering MP4s, not a new flag on the legacy pipeline. The creator can refine the native timeline and export manually. No copying raw video, normalization/proxy render, WSL or ASR model installation is required simply to deliver a draft.

## Review first

Inventory complete originals in place, inspect all clips carefully, check meaningful speech and select narrative roles plus source in/out points. Follow [editing-preferences.md](editing-preferences.md) and [narrative-rules.md](narrative-rules.md). Keep longer continuous speech and scenic beats where justified. Reopening a previous selection list is not a fresh source review.

Create a reviewed clip list with actual local paths, integer microsecond in/out ranges, intended order, source duration and optional rectangular crop/transform. Keep this task-specific list and review frames out of public repositories. The executor does not make editorial selections.

## Execute without disturbing originals

Use the separate [jianying-MCP](https://github.com/yufeiyufei888/jianying-MCP) tool and its self-authored calling skill. Read [jianying-local-adapter.md](jianying-local-adapter.md), then:

1. Check runtime/native acceptance with `doctor`. A newly installed tool has no native acceptance; stop production writes until its local tests pass.
2. Create a new draft from reviewed full originals, never overwrite a target. Fully exit Jianying for writing; no automatic window operation.
3. For a manually refined source, inspect **latest saved state**, not a stale root `draft_info.json`. Unsupported nested/multiple timelines or opaque dependencies stop.
4. Preview explicit local operations and companion-track follow/fixed policies; missing shots should be inserted at a precise anchor rather than relaying the main track. Preserve unrelated IDs, timing, crops, volume, effects and unknown fields.
5. Apply only the bound plan hash into an independent copy; verify full-original media references, ranges, unknown-field preservation, original fingerprints and additive index registration.
6. User plays, saves, closes, reopens and confirms native behavior. Re-read saved semantics after exit. File validation is not native acceptance or listening.

Music comes from confirmed local files; ducking needs explicit speech windows. SRT can use timeline or full-original time and repeated usage is mapped per segment. Unknown text, long/overlapping cues and partial sentences require review. Native subtitles are editable and bottom-positioned.

No automatic ASR, cloud music, auto-export or arbitrary decryption. Small required resources are capped at 20 MiB per copy. The tool supports only its locally verified format/version and simple operations; no implication of arbitrary Jianying compatibility. Registration is an explicit installation choice, not an editing side effect.

## Delivery

Report new draft identity/path, sources retained in place, plan/file verification, unsupported items and what needs manual play/listen/save/reopen. Leave final export to the user unless a separately authorized workflow is available. Before export, follow the measured-source bitrate and representative trial guidance in [editing-preferences.md](editing-preferences.md).
