---
name: get-ticket
description: Read tickets from the deployed internal ticketing backend (GET /tickets). Use this whenever the user wants to look up, fetch, view, check, get, or list support tickets in this project's ticketing API — a single ticket by its id, or the first 100 tickets when no id is given (optionally filtered by status). Trigger even if they don't say "ticket" (e.g. "what did we get for that outage, id 01KWZ...", "show me the open ones"). Handles Cognito JWT auth and reads connection config from the repo-root .env.
disable-model-invocation: true
---

# Read support tickets

Reads from the deployed stack. Two modes:

- **By id** → `GET {API_BASE_URL}/tickets/{id}` returns one ticket.
- **No id** → the **first 100 tickets, oldest-first**. The API only lists *by status*
  (there's no "list all" route), so the script queries each status
  (`open`, `in_progress`, `resolved`), paginates each with the opaque `cursor`, merges
  the results oldest-first, and caps at the limit. Pass a status to restrict it.

Do the work by running `scripts/get_ticket.py` — it owns the fiddly parts (finding
`.env`, reusing/refreshing the Cognito JWT, the required-`status` + pagination dance,
and turning the API's error envelope into a readable message). Don't hand-roll
`curl`/`boto3`; the script is the tested path. This is **read-only** — it never writes
a ticket (that's the create-ticket skill).

## Workflow

1. **Decide the mode.** If the user gives a ticket id, fetch that one. Otherwise list
   the first 100. If they mention a state ("the open ones", "resolved tickets"), pass
   `--status` with the matching enum (`open`, `in_progress`, `resolved` — lowercase).

2. **Run the script** from the repo root:

   ```bash
   # one ticket by id
   python .claude/skills/get-ticket/scripts/get_ticket.py 01KWZ7JRE9ZVG38W3X6YY9BYBD

   # first 100 tickets (all statuses), oldest-first
   python .claude/skills/get-ticket/scripts/get_ticket.py

   # first 50 open tickets
   python .claude/skills/get-ticket/scripts/get_ticket.py --status open --limit 50
   ```

   The id is also accepted as `--id <id>`. Add `--json` to get raw JSON (a ticket
   object, or an array). On Windows use the project venv interpreter if a bare `python`
   isn't the dev env:
   `.venv\Scripts\python.exe .claude\skills\get-ticket\scripts\get_ticket.py ...`.

3. **Report the result.** Single mode prints the ticket's fields; list mode prints one
   line per ticket (`createdAt  id  [status/priority]  area  <reportedBy>`) and the
   count. Relay what the user asked for; if they wanted a specific ticket that isn't
   there, the script exits non-zero with a clear "not found (404)".

## Options

| Flag           | Meaning                                                          |
| -------------- | --------------------------------------------------------------- |
| *(positional)* | Ticket id — omit to list. `--id ID` is the same.                |
| `--status`     | List only one status: `open`, `in_progress`, `resolved`.        |
| `--limit N`    | Max tickets in list mode (default 100).                         |
| `--json`       | Print raw JSON instead of the formatted view.                   |
| `--env-file`   | Point at a `.env` outside the repo root.                        |

`--status` is list-only; passing it together with an id is rejected.

## Configuration & credentials

Identical to the create-ticket skill — the script reads the repo-root `.env` (from
`scripts/gen_env.py`) for `API_BASE_URL`, `USER_POOL_CLIENT_ID`, and `USER_POOL_ID`, and
manages the JWT for you: a non-expired `TICKET_TOKEN` is reused; otherwise a fresh
IdToken is minted from `TICKET_USERNAME`/`TICKET_PASSWORD` via `USER_PASSWORD_AUTH` and
written back to `.env`. If a token is rejected server-side (401) it re-mints once and
retries. So as long as the Cognito user exists (set it up with the
**configure-cognito-user** skill) and username/password are in `.env`, reads just work.
These values are secrets — the script never prints them, and `.env` stays out of git.

## Common failures and what they mean

- **"no .env found"** — run `python scripts/gen_env.py` (after `terraform apply`), or
  pass `--env-file`.
- **"ticket '…' not found (404)"** — no ticket with that id. Check the id (they're
  ULIDs, case-sensitive).
- **"no credentials" / challenge** — set `TICKET_USERNAME`/`TICKET_PASSWORD`; if Cognito
  returns a challenge, the user needs a permanent password (configure-cognito-user).
- **"401 … even after re-minting a fresh token"** — a config mismatch, not a stale
  token: wrong `USER_POOL_CLIENT_ID`/`USER_POOL_ID` for this API. Re-run
  `scripts/gen_env.py`.
- **"400 validation_error"** — an out-of-range value reached the API (e.g. a bad
  `status`). Use the documented enums.
