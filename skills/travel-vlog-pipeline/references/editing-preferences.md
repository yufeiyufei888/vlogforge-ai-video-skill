# Review, pacing and creator preferences

These are integration defaults, not claims about upstream features. Apply the user's current brief first and keep source review separate from execution.

## Detailed material review

- Inventory all originals, not only previously chosen clips. Probe actual duration, video bitrate, codecs, dimensions, fps, rotation and audio streams; do not infer a scene from timestamp or filename alone.
- Sample the full duration of every video. Increase sampling around content changes, key actions, poor exposure, shaky moves, occlusions, and proposed in/out points; short clips still deserve deliberate review. Where distributed frames are insufficient, play the relevant sequence.
- Record sampling density, inspected ranges and unresolved audio/visual issues. Do not claim to have watched or listened continuously merely because a script ran fast.
- Check full-original speech when it affects editing, using actual listening or authorized complete-original transcripts. A transcript of a previous cut does not cover omitted ranges. Preserve complete ideas and breathing room, not just a few quotable lines.
- If recognition is unclear, use context only as a flagged candidate. Never invent definite wording; leave unresolved text for user review. Do not install ASR models or send media/transcripts to cloud services without explicit consent.
- Request subagents only when the user authorizes delegation or applicable instructions require it; assign disjoint source ranges and aggregate evidence, not just file metadata. Avoid concurrent mouse control.

## Long-form story selection

- Do not force a two-minute deliverable when the user wants a longer Vlog. Determine duration from actual speech, activity, scenic payoff and the reviewed route.
- Keep representative arrival, location context, main sights, food details, people/reactions, travel transitions and an ending. Report missing coverage instead of fabricating a visit stage.
- 3–4-second advisory pacing and content ratios are diagnostics, not quotas. A continuous explanation or unfolding activity may need much longer. Avoid repetitive scenery without discarding all brief imperfect but informative shots.
- Where an obstruction is limited to an edge, a modest rectangular crop or a few clean seconds can rescue the location. Preserve useful context and do not claim lost detail has been restored.
- Respect the latest manual edit. When only one shot is missing or misplaced, insert/move/trim that shot and explicitly manage companion tracks; do not rebuild the entire timeline.

## Sound, subtitles and transitions

- Keep meaningful original speech, reactions and ambience. Confirm a local BGM file and publishing rights separately. Explicit speech windows can guide ducking; an SRT does not identify who spoke or prove a listening pass.
- User-supplied final SRT or full-original SRT can be imported on independent editable tracks. Subtitles should represent actual speech when requested, not a handful of decorative titles.
- Bottom-centered white text with black outline, legible canvas-specific size, no distracting animation; check horizontal and vertical safe areas. Long or overlapping lines stay flagged, not silently shortened or deleted.
- Use restrained transitions at meaningful time/location changes; do not add an effect at every cut or over an intact sentence. Resource existence, subscription requirements, source handles and native save/reopen must be verified.
- File checks, visible sound tracks/keyframes, actual listening and music publishing authorization are separate evidence layers.

## Export bitrate and delivery

Applies to manual Jianying export as well as the existing renderer. The tool does not automatically export.

1. Before export, use FFprobe to record video bitrate, codec, resolution and fps for **each complete original** used for comparison. For VBR, consider the selected segment's motion/detail; whole-file averages are not per-second limits.
2. Use those measured video bitrates as the baseline. A source around 8 Mb/s usually needs only a modest increase on re-encoding; high-bitrate originals deserve proportionate quality. Mixed-source edits are checked separately, not assigned a fixed one-size-fits-all number.
3. Trial-encode representative moving scenes and inspect quality before committing final settings. Constant-quality encoding still needs actual output bitrate measurement and adjustment; avoid uncontrolled file growth.
4. Report source and final **video** bitrate, codecs, duration and file size. Higher bitrate can reduce another encoding generation's loss; it cannot recover absent source detail.

Example diagnostic, replacing the path with an actual source:

```powershell
ffprobe -v error -show_entries "stream=codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,bit_rate:format=duration,size,bit_rate" -of json '<original-path>'
```

Container bitrate includes audio/overhead and is not always the video's bitrate. If stream bitrate is unavailable, label the estimate, use packet information where needed and do not present container average as an exact video measurement. Final listening/playback remains required even after successful decode.
