# DEBUG — Issue log index

This folder is a **debugging journal**: one file per real problem hit while building
and deploying the ticketing backend, written *after* it was diagnosed so the next
person (or the next you) can recognize the symptom fast and skip the investigation.

Every issue so far shares a theme worth stating up front:

> **The offline gates never caught any of these.** `terraform validate`, `terraform fmt`,
> `terraform test` (mock_provider) and the pytest suite all passed — the failures only
> surfaced at real `plan`/`apply`/invocation. Passing local checks is **not** evidence a
> deploy works.

## Index

| Date | Issue | Component | Status |
|------|-------|-----------|--------|
| 2026-06-28 | [`terraform plan` → `InvalidClientTokenId` despite valid SSO login](28-06-26-credentialsIssue.md) | Terraform · AWS credential resolution | ✅ Resolved (permanent fix applied) |
| 2026-06-28 | [`local-exec` build provisioner fails on Windows (`'.' is not recognized`)](28-06-26-pathInterpreterIssues.md) | Terraform `lambda.tf` · packaging | ✅ Resolved |
| 2026-06-28 | [`AccessDeniedException` on `lambda:GetLayerVersion` for the Powertools layer](28-06-26-powertoolsLayerIssue.md) | Terraform `variables.tf`/`lambda.tf` · Lambda layer | ✅ Resolved |
| 2026-06-28 | [Every authenticated call → 500: Lambda import crash (`No module named 'exceptions'`)](28-06-26-lambdaIssues.md) | `build.py` packaging · handlers | ✅ Resolved |
| 2026-07-07 | [`local-exec` build provisioner fails on macOS (`exec: "PowerShell": ... not found in $PATH`)](07-07-26-OSCompatibility.md) | Terraform `lambda.tf`/`variables.tf` · packaging | ✅ Resolved |

## Adding a new issue

1. Create `docs/issues/<DD-MM-YY>-<shortName>.md` (e.g. `06-07-26-corsPreflight.md`).
2. Copy the template below and fill it in.
3. Add a row to the bottom of the **Index** table above (oldest-first ordering).
4. Keep secrets out: redact keys/tokens/emails as the existing files do (`<stale>`, `...`).

## Template

```markdown
# Issue — <one-line symptom in plain language>

**Date:** YYYY-MM-DD
**Component:** <area / file(s) · service>
**Status:** Open | Investigating | Resolved | Resolved (workaround)

## Symptom
What was observed (error text, HTTP status, command that triggered it).

## What made it confusing   <!-- optional; use when the surface error misleads -->
The misleading signal and the key clue that cut through it.

## Root cause
The actual mechanism, precisely.

## How we diagnosed it
Numbered steps that led to the root cause — reproducible next time.

## Resolution
The fix (with the exact diff/command), plus any workaround used before it.

## Takeaways
Durable lessons — what to check first if this class of bug recurs.
```
