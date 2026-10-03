---
name: travel-vlog-pipeline
description: "Batch travel, city-walk, restaurant-review, and food Vlog editing for raw-footage folders. Use to inspect every clip's frames and speech, preserve an arrival-to-exit story, plan reviewed ranges, create editable Jianying original-reference drafts through MCP/CLI, or use the existing locked MaxAzure versioned MP4 rendering and QA workflow."
---

# Travel Vlog Pipeline

Turn complete originals into an evidence-backed, reviewable story. This skill owns material review, narrative, pacing and shot selection; mechanical Jianying operations belong to the separate [jianying-local tool and calling skill](https://github.com/yufeiyufei888/jianying-MCP).

## Choose the delivery branch first

- **Editable Jianying draft**: read [jianying-native-draft.md](references/jianying-native-draft.md) and [jianying-local-adapter.md](references/jianying-local-adapter.md). Reference full originals in place; no render bootstrap, copying, normalization or ASR model installation is required. Final native export is manual unless requested otherwise.
- **Versioned MP4 render**: read [render-workflow.md](references/render-workflow.md) completely before acting. The existing pinned MaxAzure/Vlog sources, secure launcher, dependency lock, compilation, preview, integrity approval and QA remain unchanged. Do not invoke native-draft commands as though they were renderer flags.
- If delivery is unclear, ask before creating large media or choosing a different workflow. A draft plan is not final render/export authorization.

## Review and editorial defaults

Read [editing-preferences.md](references/editing-preferences.md) before selecting ranges, and [narrative-rules.md](references/narrative-rules.md) for travel/food roles.

1. Inventory every original: measured duration, codec, bitrate, dimensions, fps, rotation and audio streams. Do not modify or delete originals.
2. Inspect each clip using distributed frames, with denser sampling around action, changes, obstructions and intended cuts. State review coverage honestly; metadata, a contact sheet or filenames are not continuous viewing.
3. Check meaningful original speech before selecting cuts. Existing full-original SRT can help; clipped-only transcripts cannot prove the rest of the original is silent. No ASR installation or cloud transcription without explicit authorization. If listening/transcription is unavailable, mark it unverified, do not invent words.
4. Build chronology and location/activity context, keep representative scenery, food details, interactions and complete spoken ideas. Do not force a long-form request into two minutes or delete every imperfect shot; a small crop or brief usable range may rescue it.
5. Present reviewed source in/out ranges, roles, quality caveats and gaps. User story review permits the next specified step, not automatic full render.
6. Preserve existing manual edits; fix only missing/incorrect clips with explicit local changes, never relayout the main track unnecessarily. Subtitles stay bottom-centered; transitions restrained; local music and speech-ducking windows explicit.

## Execution and evidence

Prefer a locally verified `jianying-local` MCP for native operations; otherwise use the same shared CLI. Doctor → latest-state inspect → exact plan preview/hash → independent copy → verify → native play/save/reopen. Fresh installs remain unaccepted; unknown formats/resources/dependencies stop. Never load a high-level project API that reconstructs the original, fabricate acceptance, modify another draft, or seize the mouse without authorization.

For the renderer, keep every command behind `scripts/run_pipeline.ps1`, preserve upstream locks and approval receipts, and follow the full reference's stop conditions. Raw copying is the **legacy render branch** default, not the native-draft import rule.

Report file checks, GUI acceptance, actual listening and music publishing rights separately. Before any final export, measure each source's bitrate, test representative moving scenes, and report actual output bitrate/codec/duration/size; see [editing-preferences.md](references/editing-preferences.md). A successful decode does not prove creative or audio acceptance.

## References

- [editing-preferences.md](references/editing-preferences.md): dense review, longer cuts, speech, local repair, bottom subtitles and export bitrate.
- [jianying-native-draft.md](references/jianying-native-draft.md): full-original native branch, planning and acceptance.
- [jianying-local-adapter.md](references/jianying-local-adapter.md): six MCP/CLI operations and startup configuration.
- [render-workflow.md](references/render-workflow.md): preserved secure render commands and full approval/QA gates.
- [artifact-contract.md](references/artifact-contract.md): existing normalized render artifacts.
- [narrative-rules.md](references/narrative-rules.md): travel/food taxonomy and advisory pacing.
- [windows-runtime.md](references/windows-runtime.md): existing renderer runtime and optional ASR.
- [acceptance-checklist.md](references/acceptance-checklist.md): existing renderer delivery checks.
- [upstream.md](references/upstream.md): responsibilities, pinned sources and license boundary.
