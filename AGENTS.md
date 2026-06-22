# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

This repo is **pre-implementation**. Only design artifacts exist so far:
- `docs/research.md` — the design rationale (stack choices, data model, API contracts, scope).
- `docs/planTicketing.md` — a 12-task, TDD-structured implementation plan with full code for every file. **This is the source of truth for what to build.** Execute it task-by-task; tasks have checkbox steps and inter-task interface contracts.
- `ticketing.drawio` / `ticketing.png` — the architecture diagram the design is derived from.

There is no `src/`, `terraform/`, or `tests/` yet, and **git is not initialized** even though the plan's steps include `git commit`. Run `git init` before following commit steps.

When implementing, follow the plan's TDD flow (write failing test → run → minimal implementation → run → commit) — do not skip ahead or batch tasks together, since later tasks depend on the exact interfaces (function signatures, the reassignable module-global `repo`, resource names) produced by earlier ones.

## What is being built

A serverless internal support-ticketing backend, deployed entirely via Terraform:

```
Client ─(JWT)─► API Gateway HTTP API ─JWT authorizer─► Cognito User Pool
   POST /tickets ──► createTicket Lambda ──► DynamoDB
                            └──► SNS topic ──email──► support mailbox
   GET /tickets/{id}, GET /tickets?status= ──► getTicket Lambda ──► DynamoDB
```

**Stack:** Terraform ≥1.6 (AWS provider ~>5.0) · Python 3.13 + boto3 · Pydantic v2 · python-ulid · AWS Lambda Powertools (Logger) · DynamoDB (PAY_PER_REQUEST + one GSI) · SNS · Cognito · API Gateway v2. Tests: pytest + moto.

## Architecture (the parts that span files)

- **`src/common/` is pure, injectable logic; handlers are thin adapters.** `common/` (models, responses, repository) is unit-testable with moto and has zero API-Gateway coupling. Each handler does: parse event → call common → format response. Keep this boundary — business logic does not belong in handlers.
- **`TicketRepository(table=None)`** defaults to binding `boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])`. Both handlers expose a **module-global `repo`** that tests reassign to a moto-backed instance — preserve that exact pattern when editing handlers.
- **Two Lambdas, two least-privilege roles.** `createTicket` gets only `dynamodb:PutItem` + `sns:Publish` + scoped log perms; `getTicket` gets only `dynamodb:GetItem`/`Query` (table + index) + scoped log perms. Never broaden to `logs:*` — use `logs:CreateLogStream` + `logs:PutLogEvents` scoped to each function's log group.
- **Server-generated fields are never client-settable:** `id` (ULID), `createdAt` (ISO-8601 UTC), `status` (always `"open"` on create). `TicketCreate` uses `extra="forbid"` so a client-supplied `status` is a 400. Domains: `priority ∈ {low,medium,high,critical}`, `status ∈ {open,in_progress,resolved}`.
- **Error envelope** is uniform JSON `{"error": <code>, "message": <text>}` — no stack traces or internals leaked.
- **Pagination:** DynamoDB `LastEvaluatedKey` is exposed only as an opaque base64 `cursor`/`nextCursor` via `encode_cursor`/`decode_cursor`; status lists are returned oldest-first via the `status-createdAt-index` GSI.
- **Resource naming:** every AWS resource is prefixed with `var.project_name` (default `ticketing`); the GSI name `status-createdAt-index` is referenced identically in the conftest fixture, repository, IAM policy, and table definition — keep them in sync.

## Commands

Local dev & tests (from repo root; `pytest.ini` sets `pythonpath=src`, `testpaths=tests`):
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -v                              # full suite
python -m pytest tests/unit/test_models.py -v    # single test file
python -m pytest tests/unit/test_models.py::test_valid_ticket_create -v   # single test
```

Lambda packaging (vendors Linux/cp313 wheels + copies `src` per function into `terraform/build/<func>/`):
```bash
python terraform/build.py
```

Terraform (from `terraform/`):
```bash
terraform init -backend=false   # validate-only; no AWS creds needed
terraform fmt -check            # must print nothing (formatted)
terraform validate              # must print "Success! The configuration is valid."
terraform init                  # for a real deploy
terraform apply  -var "support_email=you@example.com"   # runs build.py, then provisions
terraform destroy -var "support_email=you@example.com"
```

Note: `terraform apply` invokes `build.py` via `local-exec` using `.venv/Scripts/python.exe` (Windows). On non-Windows hosts change that to `.venv/bin/python`; if `.venv` is absent, substitute an interpreter that has the dev deps installed.

- To check about conventions please take a look at @reference/conventions.md
- To check about out-of-scope, please take a look at @reference/out-of-scope.md