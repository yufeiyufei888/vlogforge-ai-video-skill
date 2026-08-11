# Upstream Sources

## MaxAzure Engineering Backbone

- Repository: `https://github.com/maxazure/video-editing-skill`
- Pinned commit: `b3d80f9a9b6eb79b8aa0a9881bbf7b0c115d23ce`
- Local path: `<workspace>/.vendor/video-editing-skill-main`
- Responsibilities used here: project bootstrap, transcript-shaped render contract, single-pass renderer, edit preflight, versioned output, and render QA.
- Licensing note: no root license file was present in the inspected snapshot. Keep it as a local dependency; do not redistribute copied code or imply a license grant.

## Vlog Narrative Reference

- Repository: `https://github.com/znyupup/ai-video-editing-skill`
- Pinned commit: `b6429ab550a64c595dc68d42c47cf2b489a50619`
- Local path: `<workspace>/.vendor/ai-video-editing-skill-main`
- Responsibilities used here: travel shot-analysis shape, recommended ranges, three-act pacing guidance, storyboard, and dashboard.
- License: MIT in the inspected snapshot.

## Integration Boundary

The upstream Vlog repository does not contain a full analysis/rendering CLI. Its only current executable scripts generate storyboard and dashboard review pages. This integration therefore compiles its rules into a separate normalized timeline and MaxAzure render config instead of pretending the two schemas already match.

`assets/upstream-lock.json` pins each complete local vendor tree, not only the named entry scripts. The tree digest incorporates every non-ephemeral relative path, byte length, and file SHA-256 plus the expected file count. Setup and all later gates reject `__pycache__`, `.pyc`, `.pyo`, symlinks, junctions, and other reparse points in either vendor tree. Any other file addition, deletion, or byte change blocks doctor, preflight, approval, render, and QA.
