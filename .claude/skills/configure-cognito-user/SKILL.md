---
name: configure-cognito-user
description: Create and configure the Cognito user for this ticketing stack from the repo-root .env (TICKET_USERNAME/TICKET_PASSWORD), setting a permanent password so the credentials actually authenticate. Use this whenever the user wants to create/register/set up/provision the Cognito login for the deployed backend, "make the .env credentials work", get past a NEW_PASSWORD_REQUIRED / FORCE_CHANGE_PASSWORD challenge, fix a 401 from create-ticket caused by a user that doesn't exist yet, or otherwise prep auth before filing tickets — even if they don't say "Cognito". This is the missing step between `gen_env.py` and the create-ticket skill.
disable-model-invocation: true
---

# Configure the Cognito user

`scripts/gen_env.py` writes a random `TICKET_USERNAME`/`TICKET_PASSWORD` into the
repo-root `.env` but **does not create the matching Cognito user** — so those
credentials don't authenticate yet, and `create-ticket` gets a 401 (or Cognito
returns a `NEW_PASSWORD_REQUIRED` challenge instead of a token). This skill closes
that gap: it creates the user in the deployed User Pool and sets a **permanent**
password, leaving the account `CONFIRMED` and ready for `USER_PASSWORD_AUTH`.

Do the work by running `scripts/configure_user.py`. It owns the fiddly parts
(finding `.env`, the two-call `AdminCreateUser` + `AdminSetUserPassword` sequence,
idempotency, and turning Cognito errors into readable messages). Don't hand-roll
`aws cognito-idp ...`; the script is the tested path.

## Why a permanent password (the whole point)

`AdminCreateUser` alone leaves the account in `FORCE_CHANGE_PASSWORD`, so
`USER_PASSWORD_AUTH` returns a `NEW_PASSWORD_REQUIRED` challenge rather than an
IdToken — and `create-ticket` can't authenticate. `AdminSetUserPassword` with
`Permanent=True` moves the account to `CONFIRMED`, which is what makes the token
flow work. The script always does both.

## Prerequisites

- **`.env` populated** with `USER_POOL_ID`, `TICKET_USERNAME`, `TICKET_PASSWORD`
  (run `python scripts/gen_env.py` after `terraform apply`).
- **AWS credentials** for the principal you run `terraform apply` with — it needs
  `cognito-idp:AdminCreateUser` and `cognito-idp:AdminSetUserPassword`. These are
  admin (SigV4-signed) calls, unlike the unsigned public auth `create-ticket` uses.
- **Dev venv active** — the script imports `boto3` (in `requirements-dev.txt`):
  `source .venv/bin/activate && pip install -r requirements-dev.txt`.

## Workflow

1. **Confirm the target.** This creates a real user in the **live** Cognito pool.
   Echo the username and `USER_POOL_ID` it will act on, then proceed unless the user
   is clearly still deciding.

2. **Run the script** from the repo root:

   ```bash
   python .claude/skills/configure-cognito-user/scripts/configure_user.py
   ```

   On Windows, use the project venv interpreter if a bare `python` isn't the dev env:
   `.venv\Scripts\python.exe .claude\configure-cognito-user\scripts\configure_user.py`.
   Pass `--env-file PATH` to target a `.env` outside the repo root.

3. **Report the result.** On success it prints the username, pool id, and status
   (`created` vs `already existed -> password reset`) — relay that. On failure it
   exits non-zero with a one-line reason; surface it verbatim and point at the fix
   below rather than retrying blindly.

4. **Point the user at the next step.** With the user configured, they can mint a
   token / file a ticket via the **create-ticket** skill — it will no longer 401.

## Idempotency

Safe to re-run: if the user already exists, the create is a no-op and the permanent
password is simply re-asserted. Use this to reset the password after `gen_env.py`
regenerates the credentials.

## Security

`TICKET_PASSWORD` is a secret — the script never prints it, and `.env` must stay out
of version control (it's gitignored). Nothing here writes credentials anywhere new.

## Common failures and what they mean

- **"missing from .env: …"** — the stack config isn't generated. Run
  `python scripts/gen_env.py` (after `terraform apply`), or pass `--env-file`.
- **"password rejected by the pool policy"** (`InvalidPasswordException`) —
  `TICKET_PASSWORD` violates the pool policy (min 8, upper + lower + digit; symbols
  not required). Fix the value in `.env` and re-run.
- **"user pool '…' not found"** (`ResourceNotFoundException`) — a stale
  `USER_POOL_ID` (e.g. after a destroy/recreate). Re-run `python scripts/gen_env.py`.
- **"no AWS credentials found"** / `AccessDeniedException` — the AWS principal is
  missing or lacks `cognito-idp:AdminCreateUser` / `AdminSetUserPassword`. Use the
  same credentials as `terraform apply`.
- **"boto3 is required …"** — you're not in the dev venv. Activate `.venv` and
  install `requirements-dev.txt`.
