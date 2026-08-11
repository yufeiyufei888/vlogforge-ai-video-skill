# Contributing

Thanks for helping improve VlogForge AI.

## Before opening a pull request

1. Keep the repository focused on the single `travel-vlog-pipeline` skill.
2. Do not commit footage, rendered media, `.vendor`, `.venv`, `.tools`, model weights, credentials, or personal paths.
3. Preserve originals, versioned outputs, explicit human approval, and full-decode acceptance boundaries.
4. Update the artifact contract when a persisted JSON schema changes.
5. Add or update tests for deterministic Python behavior.
6. Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
py -3 -m unittest discover -s .\skills\travel-vlog-pipeline\tests -v
```

## Pull requests

Keep each pull request narrow. Explain what changed, why it is safe, which artifacts or schemas are affected, and what validation was completed. Changes that weaken source preservation, integrity verification, approval binding, or final QA need explicit justification and test coverage.

## Upstream code

Do not copy upstream implementation code into this repository unless its license clearly permits redistribution and attribution requirements are satisfied. Keep unlicensed upstream snapshots as local `.vendor` dependencies.
