---
name: create-ticket
description: Create a support ticket against the deployed internal ticketing backend (POST /tickets). Use this whenever the user wants to file, open, raise, log, or submit a support ticket, report an incident/outage, or otherwise create a ticket in this project's ticketing API — even if they don't say the word "ticket" (e.g. "the VPN is down for Finance, let the support team know"). Handles Cognito JWT auth and reads connection config from the repo-root .env.
disable-model-invocation: true
---

# Create a support ticket

Files a ticket by calling `POST {API_BASE_URL}/tickets` on the deployed stack. The
server generates `id`, `createdAt`, and `status` (`open`) — you only supply the four
client fields below. Auth is a Cognito JWT sent as `Authorization: Bearer <token>`.

Do the work by running `scripts/create_ticket.py` — it owns the fiddly parts (finding
`.env`, minting the JWT with an unsigned Cognito call, POSTing, and turning the API's
error envelope into a readable message). Don't hand-roll `curl`/`boto3`; the script is
the tested path.

## The four fields you must collect

| Field            | Rule                                              |
| ---------------- | ------------------------------------------------- |
| `priority`       | exactly one of `low`, `medium`, `high`, `critical`|
| `description`    | 1–2000 chars, a brief incident description        |
| `requestingArea` | 1–200 chars, the department (e.g. Finance, IT)    |
| `reportedBy`     | 1–200 chars, who is reporting (username/email)    |

The API uses `extra="forbid"`, so never invent extra fields (no `status`, no `id`) —
they cause a 400. Enum values are lowercase.

## Workflow

1. **Gather the four fields.** Pull them from the user's request. If any are missing or
   ambiguous, ask — but infer sensibly first (e.g. "the VPN is down for the whole
   Finance floor, this is urgent" → `priority=high` or `critical`, `description` = the
   incident, `requestingArea=Finance`). Map natural-language urgency to the closest enum
   rather than asking pedantically; confirm `priority` if it's a real judgment call.
   For `reportedBy`, prefer an explicit name/username the user gives; if none is
   available, ask rather than guessing.

2. **Confirm before sending.** This writes to the live backend and emails the support
   team via SNS, so echo the assembled ticket back in one line and proceed unless the
   user is clearly still deciding. Don't create duplicates — one call per ticket.

3. **Run the script** from the repo root:

   ```bash
   python SKILLS/create-ticket/scripts/create_ticket.py \
     --priority high \
     --description "VPN down for the whole Finance floor" \
     --requesting-area Finance \
     --reported-by jdoe
   ```

   On Windows use the project venv interpreter if a bare `python` isn't the 3.13 env:
   `.venv/Scripts/python.exe SKILLS/create-ticket/scripts/create_ticket.py ...`.

4. **Report the result.** On success the script prints the new `id`, `status`, and
   `createdAt` — relay the `id` to the user, since that's what they'll use to query the
   ticket later (`GET /tickets/{id}`). On failure it exits non-zero with a one-line
   reason; surface that verbatim and, if it's a config/credential problem, point at the
   fix below rather than retrying blindly.

## Configuration & credentials

The script reads the repo-root `.env` (produced by `scripts/gen_env.py` after
`terraform apply`) for `API_BASE_URL`, `USER_POOL_CLIENT_ID`, and `USER_POOL_ID`. It
needs credentials to mint the JWT, resolved in this order:

- `TICKET_TOKEN` — a pre-obtained Cognito **IdToken** (with or without a `Bearer `
  prefix). If set, auth is skipped entirely.
- `TICKET_USERNAME` + `TICKET_PASSWORD` — exchanged for an IdToken via Cognito
  `USER_PASSWORD_AUTH`. This is the normal path.

All three credential values are read from the same repo-root `.env`; a matching real
environment variable, if present, overrides the `.env` value for that call. These are
secrets — the script never prints them, and `.env` must stay out of version control. If
none are set in either place, tell the user to add them to `.env` or export them,
e.g. (PowerShell) `$env:TICKET_USERNAME="demo@example.com"; $env:TICKET_PASSWORD="..."`.
The README's "Get a JWT" section shows how to create a demo user with a permanent
password (a permanent password matters — otherwise Cognito returns a challenge instead
of a token, and the script will say so).

## Common failures and what they mean

- **"no .env found"** — the stack config isn't generated. Run `python scripts/gen_env.py`
  (after a `terraform apply`), or pass `--env-file`.
- **"no credentials"** — set `TICKET_USERNAME`/`TICKET_PASSWORD` (or `TICKET_TOKEN`).
- **"401 Unauthorized"** — the token was rejected: expired, wrong user pool, or an
  `AccessToken` was supplied where an `IdToken` is required. Re-mint via env creds.
- **"400 validation_error"** — a field is missing/invalid or an extra field leaked in.
  Check `priority` is a valid enum and only the four fields are sent.
