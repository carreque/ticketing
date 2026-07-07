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
   python .claude/skills/create-ticket/scripts/create_ticket.py \
     --priority high \
     --description "VPN down for the whole Finance floor" \
     --requesting-area Finance \
     --reported-by jdoe
   ```

   On Windows use the project venv interpreter if a bare `python` isn't the 3.13 env:
   `.venv\Scripts\python.exe .claude\skills\create-ticket\scripts\create_ticket.py ...`.

4. **Report the result.** On success the script prints the new `id`, `status`, and
   `createdAt` — relay the `id` to the user, since that's what they'll use to query the
   ticket later (`GET /tickets/{id}`). On failure it exits non-zero with a one-line
   reason; surface that verbatim and, if it's a config/credential problem, point at the
   fix below rather than retrying blindly.

## Configuration & credentials

The script reads the repo-root `.env` (produced by `scripts/gen_env.py` after
`terraform apply`) for `API_BASE_URL`, `USER_POOL_CLIENT_ID`, and `USER_POOL_ID`. It
manages the JWT for you — you don't need to obtain one by hand:

- `TICKET_TOKEN` — a Cognito **IdToken** (with or without a `Bearer ` prefix). It's
  reused **only if it hasn't expired** (a local `exp` check, no network). If it's
  missing, expired, or malformed, the script mints a fresh one.
- `TICKET_USERNAME` + `TICKET_PASSWORD` — exchanged for a fresh IdToken via Cognito
  `USER_PASSWORD_AUTH` whenever a valid `TICKET_TOKEN` isn't available. The new token
  is **written back into `.env` under `TICKET_TOKEN`**, so later calls reuse it until
  it expires and then self-heal by re-minting.
- **Server-side rejection is also handled:** if a token passes the local expiry check
  but the API still returns 401 (revoked, wrong pool), the script re-mints from
  username/password and retries the POST once.

So the practical contract is: **as long as `TICKET_USERNAME`/`TICKET_PASSWORD` are set
and the Cognito user exists, ticket creation just works** — `TICKET_TOKEN` can be empty
or stale. Configure that user with the **configure-cognito-user** skill (it sets a
*permanent* password — otherwise Cognito returns a challenge instead of a token, and the
script will say so).

All values are read from the same repo-root `.env`; a matching real environment
variable, if present, overrides the `.env` value for that call. These are secrets — the
script never prints them, and `.env` must stay out of version control. If no credentials
are set anywhere, tell the user to add them to `.env` or export them, e.g. (PowerShell)
`$env:TICKET_USERNAME="demo@example.com"; $env:TICKET_PASSWORD="..."`.

## Common failures and what they mean

- **"no .env found"** — the stack config isn't generated. Run `python scripts/gen_env.py`
  (after a `terraform apply`), or pass `--env-file`.
- **"no credentials"** — set `TICKET_USERNAME`/`TICKET_PASSWORD` (or a valid
  `TICKET_TOKEN`). Note the script auto-mints and refreshes `TICKET_TOKEN`, so you
  normally only need username/password.
- **"401 Unauthorized … even after re-minting a fresh token"** — the freshly minted
  IdToken was still rejected by the API authorizer. That points at a mismatch, not a
  stale token: wrong `USER_POOL_CLIENT_ID`/`USER_POOL_ID` for this API, or an
  `AccessToken` where an `IdToken` is required. Re-run `scripts/gen_env.py`.
- **"no IdToken returned … challenge"** — the Cognito user has a temporary password.
  Run the **configure-cognito-user** skill to set a permanent one.
- **"400 validation_error"** — a field is missing/invalid or an extra field leaked in.
  Check `priority` is a valid enum and only the four fields are sent.
