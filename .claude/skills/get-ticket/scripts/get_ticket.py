#!/usr/bin/env python3
"""Read tickets from the deployed ticketing backend.

Two modes:
  * With an id  -> GET {API_BASE_URL}/tickets/{id}  (a single ticket).
  * Without an id -> the first 100 tickets, oldest-first. The API only lists
    *by status*, so this queries every status (open, in_progress, resolved),
    paginates each with the opaque `cursor`, merges the results oldest-first, and
    caps at the limit. Pass --status to restrict to one status.

Reads connection config from the repo-root .env (as produced by scripts/gen_env.py)
and reuses/refreshes the Cognito JWT exactly like the create-ticket script: a valid
TICKET_TOKEN is reused, otherwise a fresh one is minted from
TICKET_USERNAME/TICKET_PASSWORD and written back to .env.

Fail-fast: any missing config or unexpected response exits non-zero with a clear,
single-line message. No secrets are ever printed.

Usage:
  python get_ticket.py 01KWZ7JRE9ZVG38W3X6YY9BYBD   # one ticket by id
  python get_ticket.py                               # first 100 tickets
  python get_ticket.py --status open --limit 50      # first 50 open tickets

Optional:
  --id ID           Same as the positional id (either form works).
  --status STATUS   Restrict the list to one of open|in_progress|resolved.
  --limit N         Max tickets to return in list mode (default 100).
  --env-file PATH   Path to the .env (default: repo-root .env, discovered upward).
  --json            Print raw JSON (a ticket object, or a list of them).
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

STATUSES = ("open", "in_progress", "resolved")
DEFAULT_LIMIT = 100


def fail(msg: str) -> "None":
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


class Unauthorized(Exception):
    """Raised when the API rejects the JWT (HTTP 401), so the caller can decide
    whether to re-mint a fresh token and retry."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class NotFound(Exception):
    """Raised on HTTP 404 (single-ticket lookup miss)."""


# --- .env + Cognito auth (kept in step with create-ticket's create_ticket.py) ---

def find_env_file(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            fail(f"--env-file not found: {p}")
        return p
    for start in (Path.cwd(), Path(__file__).resolve().parent):
        for d in (start, *start.parents):
            candidate = d / ".env"
            if candidate.is_file():
                return candidate
    fail("no .env found - run `python scripts/gen_env.py` after `terraform apply`, "
         "or pass --env-file.")


def load_env(path: Path) -> dict:
    """Parse a KEY=value .env into a dict; a matching real environment variable
    wins, so callers can point at another stack per-call without editing the file."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip().strip('"').strip("'")
    for key in ("API_BASE_URL", "USER_POOL_ID", "USER_POOL_CLIENT_ID"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def region_from(env: dict) -> str:
    if os.environ.get("AWS_REGION"):
        return os.environ["AWS_REGION"]
    pool = env.get("USER_POOL_ID", "")
    if "_" in pool:
        return pool.split("_", 1)[0]
    host = env.get("API_BASE_URL", "")
    parts = host.split(".")
    if "execute-api" in parts:
        return parts[parts.index("execute-api") + 1]
    fail("could not determine AWS region - set AWS_REGION.")


def token_is_fresh(token: str, skew: int = 60) -> bool:
    """True if `token` is a JWT whose `exp` is still comfortably in the future - a
    cheap local check (no network) so we don't spend a request on a stale token."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload)).get("exp")
        return bool(exp) and time.time() + skew < float(exp)
    except Exception:
        return False


def mint_token(env: dict) -> str:
    """Exchange TICKET_USERNAME/TICKET_PASSWORD for a fresh Cognito IdToken via
    USER_PASSWORD_AUTH (an unauthenticated public flow)."""
    username = os.environ.get("TICKET_USERNAME") or env.get("TICKET_USERNAME")
    password = os.environ.get("TICKET_PASSWORD") or env.get("TICKET_PASSWORD")
    if not username or not password:
        fail("no credentials - set TICKET_USERNAME and TICKET_PASSWORD (or a valid "
             "TICKET_TOKEN) in .env or the environment.")

    client_id = env.get("USER_POOL_CLIENT_ID")
    if not client_id:
        fail("USER_POOL_CLIENT_ID missing from .env - re-run scripts/gen_env.py.")

    try:
        import boto3
        from botocore import UNSIGNED
        from botocore.config import Config
    except ImportError:
        fail("boto3 is required to mint a JWT - `pip install boto3` (it's in "
             "requirements-dev.txt) or supply a valid TICKET_TOKEN instead.")

    client = boto3.client(
        "cognito-idp",
        region_name=region_from(env),
        config=Config(signature_version=UNSIGNED),
    )
    try:
        resp = client.initiate_auth(
            AuthFlow="USER_PASSWORD_AUTH",
            ClientId=client_id,
            AuthParameters={"USERNAME": username, "PASSWORD": password},
        )
    except Exception as exc:  # boto ClientError etc. - surface reason, not secrets
        fail(f"Cognito authentication failed: {type(exc).__name__}: {exc}")

    result = resp.get("AuthenticationResult") or {}
    id_token = result.get("IdToken")
    if not id_token:
        challenge = resp.get("ChallengeName", "unknown")
        fail(f"no IdToken returned - Cognito responded with challenge '{challenge}'. "
             "Set a permanent password (the configure-cognito-user skill) so no "
             "challenge is required.")
    return id_token


def persist_token(env_path: Path, token: str) -> None:
    """Write the freshly minted IdToken back into .env under TICKET_TOKEN so later
    calls reuse it until it expires."""
    lines = env_path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("TICKET_TOKEN="):
            lines[i] = f"TICKET_TOKEN={token}"
            break
    else:
        lines.append(f"TICKET_TOKEN={token}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def get_token(env: dict, env_path: Path) -> "tuple[str, bool]":
    """Return (id_token, freshly_minted). Reuse a non-expired TICKET_TOKEN, else
    mint from credentials and persist it back to .env."""
    existing = os.environ.get("TICKET_TOKEN") or env.get("TICKET_TOKEN")
    if existing:
        existing = existing.removeprefix("Bearer ").strip()
        if token_is_fresh(existing):
            return existing, False
    token = mint_token(env)
    persist_token(env_path, token)
    return token, True


# --- HTTP GET helpers ---

def http_get(url: str, token: str) -> dict:
    req = urllib.request.Request(
        url, method="GET", headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        try:
            env_err = json.loads(detail)
            detail = f"{env_err.get('error')}: {env_err.get('message')}"
        except json.JSONDecodeError:
            pass
        if exc.code == 401:
            raise Unauthorized(detail)
        if exc.code == 404:
            raise NotFound(detail)
        fail(f"GET {url} returned {exc.code}. {detail}")
    except urllib.error.URLError as exc:
        fail(f"could not reach {url}: {exc.reason}")


def api_base(env: dict) -> str:
    base = env.get("API_BASE_URL")
    if not base:
        fail("API_BASE_URL missing from .env - re-run scripts/gen_env.py.")
    return base.rstrip("/")


def get_one(env: dict, token: str, ticket_id: str) -> dict:
    url = api_base(env) + "/tickets/" + urllib.parse.quote(ticket_id, safe="")
    try:
        return http_get(url, token)
    except NotFound:
        fail(f"ticket '{ticket_id}' not found (404).")


def _list_one_status(env: dict, token: str, status: str, limit: int) -> list:
    """Page through GET /tickets?status=... following `nextCursor` until we have
    `limit` items for this status or the list is exhausted."""
    base = api_base(env)
    items: list = []
    cursor = None
    while len(items) < limit:
        params = {"status": status, "limit": str(limit - len(items))}
        if cursor:
            params["cursor"] = cursor
        body = http_get(base + "/tickets?" + urllib.parse.urlencode(params), token)
        items.extend(body.get("items", []))
        cursor = body.get("nextCursor")
        if not cursor:
            break
    return items[:limit]


def list_tickets(env: dict, token: str, limit: int, status: str | None) -> list:
    """The first `limit` tickets, oldest-first. With no status filter, gather up to
    `limit` from each status and merge - the globally-oldest `limit` are guaranteed
    to be within that union (each per-status list is already oldest-first)."""
    statuses = [status] if status else list(STATUSES)
    merged: list = []
    for st in statuses:
        merged.extend(_list_one_status(env, token, st, limit))
    # createdAt is ISO-8601 UTC, so lexical sort == chronological; id breaks ties.
    merged.sort(key=lambda t: (t.get("createdAt", ""), t.get("id", "")))
    return merged[:limit]


# --- output ---

def print_ticket(t: dict) -> None:
    print(f"  id:          {t.get('id')}")
    print(f"  status:      {t.get('status')}")
    print(f"  priority:    {t.get('priority')}")
    print(f"  createdAt:   {t.get('createdAt')}")
    print(f"  area:        {t.get('requestingArea')}")
    print(f"  reportedBy:  {t.get('reportedBy')}")
    print(f"  description: {t.get('description')}")


def print_list(items: list, status: str | None, limit: int) -> None:
    scope = f"status={status}" if status else "all statuses"
    print(f"Retrieved {len(items)} ticket(s), oldest-first ({scope}, limit {limit}):")
    for t in items:
        print(f"  {t.get('createdAt','?')}  {t.get('id','?')}  "
              f"[{t.get('status','?')}/{t.get('priority','?')}]  "
              f"{t.get('requestingArea','?')}  <{t.get('reportedBy','?')}>")
    if not items:
        print("  (none)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Read tickets from the ticketing API.")
    ap.add_argument("ticket_id", nargs="?", help="ticket id (omit to list tickets)")
    ap.add_argument("--id", dest="id_opt", help="ticket id (alternative to positional)")
    ap.add_argument("--status", choices=STATUSES, help="restrict the list to one status")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                    help=f"max tickets in list mode (default {DEFAULT_LIMIT})")
    ap.add_argument("--env-file", dest="env_file")
    ap.add_argument("--json", action="store_true", help="print raw JSON")
    args = ap.parse_args()

    ticket_id = args.id_opt or args.ticket_id
    if ticket_id and args.status:
        fail("--status applies only to the list (no-id) mode; drop it when fetching "
             "a single ticket by id.")
    if args.limit < 1:
        fail("--limit must be >= 1.")

    env_path = find_env_file(args.env_file)
    env = load_env(env_path)
    token, freshly_minted = get_token(env, env_path)

    def run(tok: str):
        if ticket_id:
            return ("one", get_one(env, tok, ticket_id))
        return ("list", list_tickets(env, tok, args.limit, args.status))

    try:
        kind, data = run(token)
    except Unauthorized as exc:
        # A pre-supplied token passed the local expiry check but the API rejected it.
        # Mint fresh from .env creds, persist, retry once. A just-minted token that's
        # still rejected won't be fixed by minting again.
        if freshly_minted:
            fail(f"401 Unauthorized - freshly minted token rejected by the API "
                 f"authorizer. {exc.detail}")
        print("info: TICKET_TOKEN rejected (401) - re-minting from "
              "TICKET_USERNAME/TICKET_PASSWORD.", file=sys.stderr)
        token = mint_token(env)
        persist_token(env_path, token)
        try:
            kind, data = run(token)
        except Unauthorized as exc2:
            fail(f"401 Unauthorized even after re-minting a fresh token. {exc2.detail}")

    if args.json:
        print(json.dumps(data, indent=2))
    elif kind == "one":
        print("Ticket:")
        print_ticket(data)
    else:
        print_list(data, args.status, args.limit)


if __name__ == "__main__":
    main()
