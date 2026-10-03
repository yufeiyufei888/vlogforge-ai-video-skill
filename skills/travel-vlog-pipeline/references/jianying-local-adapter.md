# Companion MCP / CLI contract

The mechanical implementation and installation guide are maintained only in [jianying-MCP](https://github.com/yufeiyufei888/jianying-MCP). Do not copy its complete implementation or the upstream `jianying-editor` into this travel skill. This reference is a routing contract, not a second implementation.

## Runtime

Prefer a locally verified `jianying-local` stdio MCP; without a connected MCP use the same standalone Python CLI at `<tool-root>/scripts/jianying_local/cli.py`. A trusted startup JSON config defines drafts/work/backend/worker/application/codec/Codex paths, without fixed personal directories. Tool requests cannot select executable commands or roots.

Fresh installs are unaccepted. Backend source and binary dependencies are external, pinned and separately verified; no automatic installation, registration or extra speech models. Compatibility currently targets Windows Jianying 11.5.0.14471, legacy plain schema and tested single-timeline nested saved state. CI does not validate native playback.

## Calls

| Call | Travel skill responsibility |
| --- | --- |
| `doctor` | Confirm runtime, editor state, local native gate |
| `list_drafts` | Choose an exact source identity, avoid unrelated drafts |
| `inspect_draft` | Read latest state, actual track/segment IDs, dependencies and pagination fingerprint |
| `plan_draft` | Send the reviewed explicit `create/enrich/patch` request, review changed ranges/duration/warnings |
| `apply_plan` | Apply only the reviewed plan ID/hash to a new draft/copy while Jianying is exited |
| `verify_draft` | Exact delivery verification, then saved semantic checks after native review |

MCP `plan_draft` takes `{"request":<request>}`; CLI takes the request JSON itself. Time is integer microseconds and gain is a linear coefficient, not decibels. Current examples and parameter names live in [API documentation](https://github.com/yufeiyufei888/jianying-MCP/blob/main/docs/api.md).

Example CLI diagnostic:

```powershell
& '<existing-worker-python>' -I -B -X utf8 '<tool-root>\scripts\jianying_local\cli.py' doctor --config '<trusted-startup-config>'
```

`create` accepts the travel skill's reviewed complete originals. `enrich` only appends confirmed BGM/transitions on a copy. `patch` uses explicit local edits, companion policies, SRT/relink requests, not wholesale main-track reconstruction.

Do not alter frozen plans, forge native test records, copy another user's acceptance or hide unsupported structures through high-level loading. On source/config/media changes, make a fresh preview. After interrupted writes inspect the persisted receipt first; never invent a new request ID and blindly retry.

Separate file validation, additive draft registration, editor save/reopen, listening and music publishing rights in the handoff. All private footage, transcripts, receipts and config remain local.
