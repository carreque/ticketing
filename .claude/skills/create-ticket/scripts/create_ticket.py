#!/usr/bin/env python3
"""Create a support ticket against the deployed ticketing backend.

Reads connection config from the repo-root .env (as produced by
scripts/gen_env.py), mints a Cognito JWT from TICKET_USERNAME/TICKET_PASSWORD
(or reuses TICKET_TOKEN), then POSTs to {API_BASE_URL}/tickets.

Fail-fast: any missing config or non-2xx response exits non-zero with a clear,
single-line message. No secrets are ever printed.

Usage:
  python create_ticket.py \
      --priority high \
      --description "VPN down for the whole Finance floor" \
      --requesting-area Finance \
      --reported-by jdoe

Optional:
  --env-file PATH   Path to the .env (default: repo-root .env, discovered upward).
  --json            Print only the created ticket as JSON (for scripting).
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PRIORITIES = ("low", "medium", "high", "critical")


def fail(msg: str) -> "None":
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def find_env_file(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            fail(f"--env-file not found: {p}")
        return p
    # Walk upward from CWD, then from this script's location, looking for .env.
    for start in (Path.cwd(), Path(__file__).resolve().parent):
        for d in (start, *start.parents):
            candidate = d / ".env"
            if candidate.is_file():
                return candidate
    fail("no .env found - run `python scripts/gen_env.py` after `terraform apply`, "
         "or pass --env-file.")


def load_env(path: Path) -> dict:
    """Parse a KEY=value .env into a dict; values already present in the real
    environment win, so callers can override without editing the file."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip().strip('"').strip("'")
    # Real environment overrides file (lets you point at another stack per-call).
    for key in ("API_BASE_URL", "USER_POOL_ID", "USER_POOL_CLIENT_ID"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def region_from(env: dict) -> str:
    if os.environ.get("AWS_REGION"):
        return os.environ["AWS_REGION"]
    # Cognito pool ids look like "eu-west-1_ABC123XYZ".
    pool = env.get("USER_POOL_ID", "")
    if "_" in pool:
        return pool.split("_", 1)[0]
    # Fall back to the API host: https://xxx.execute-api.<region>.amazonaws.com
    host = env.get("API_BASE_URL", "")
    parts = host.split(".")
    if "execute-api" in parts:
        return parts[parts.index("execute-api") + 1]
    fail("could not determine AWS region - set AWS_REGION.")


class Unauthorized(Exception):
    """Raised when the API rejects the JWT (HTTP 401), so the caller can decide
    whether to re-mint a fresh token and retry."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


def token_is_fresh(token: str, skew: int = 60) -> bool:
    """True if `token` is a JWT whose `exp` is still comfortably in the future.

    A cheap local check - no network, no signature verification - that catches the
    common invalid case (an expired/stale TICKET_TOKEN) before we waste a POST on a
    guaranteed 401. Malformed or unparseable tokens count as not fresh, so we
    re-mint rather than trust them."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)  # restore base64url padding
        exp = json.loads(base64.urlsafe_b64decode(payload)).get("exp")
        return bool(exp) and time.time() + skew < float(exp)
    except Exception:
        return False


def mint_token(env: dict) -> str:
    """Exchange TICKET_USERNAME/TICKET_PASSWORD for a fresh Cognito IdToken via
    USER_PASSWORD_AUTH (an unauthenticated public flow).

    Credentials are read from the .env values (env), with any matching real
    environment variable taking precedence so a per-call override still works."""
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
        config=Config(signature_version=UNSIGNED),  # InitiateAuth needs no AWS creds
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
    calls reuse it until it expires. Preserves every other line; replaces the
    existing TICKET_TOKEN line in place, or appends one if it's absent."""
    lines = env_path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("TICKET_TOKEN="):
            lines[i] = f"TICKET_TOKEN={token}"
            break
    else:
        lines.append(f"TICKET_TOKEN={token}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def get_token(env: dict, env_path: Path) -> "tuple[str, bool]":
    """Return (id_token, freshly_minted).

    Reuse TICKET_TOKEN only if it's a JWT that hasn't expired; otherwise mint a
    fresh one from the .env credentials and persist it back to .env. The
    `freshly_minted` flag tells the caller whether a later server-side 401 is worth
    a re-mint+retry - a token we just minted that's still rejected won't be fixed
    by minting again."""
    existing = os.environ.get("TICKET_TOKEN") or env.get("TICKET_TOKEN")
    if existing:
        existing = existing.removeprefix("Bearer ").strip()
        if token_is_fresh(existing):
            return existing, False
    token = mint_token(env)
    persist_token(env_path, token)
    return token, True


def post_ticket(env: dict, token: str, ticket: dict) -> dict:
    base = env.get("API_BASE_URL")
    if not base:
        fail("API_BASE_URL missing from .env - re-run scripts/gen_env.py.")
    url = base.rstrip("/") + "/tickets"
    body = json.dumps(ticket).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
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
        fail(f"POST /tickets returned {exc.code}. {detail}")
    except urllib.error.URLError as exc:
        fail(f"could not reach {url}: {exc.reason}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Create a support ticket via the API.")
    ap.add_argument("--priority", required=True, choices=PRIORITIES)
    ap.add_argument("--description", required=True)
    ap.add_argument("--requesting-area", required=True, dest="requesting_area")
    ap.add_argument("--reported-by", required=True, dest="reported_by")
    ap.add_argument("--env-file", dest="env_file")
    ap.add_argument("--json", action="store_true", help="print only the ticket JSON")
    args = ap.parse_args()

    if not args.description.strip():
        fail("--description must not be empty.")

    env_path = find_env_file(args.env_file)
    env = load_env(env_path)
    body = {
        "priority": args.priority,
        "description": args.description,
        "requestingArea": args.requesting_area,
        "reportedBy": args.reported_by,
    }

    token, freshly_minted = get_token(env, env_path)
    try:
        ticket = post_ticket(env, token, body)
    except Unauthorized as exc:
        # A pre-supplied TICKET_TOKEN passed the local expiry check but the API
        # still rejected it (revoked, wrong pool, etc.). Mint a fresh token from
        # the .env credentials, persist it, and retry once. If the token we just
        # minted is the one being rejected, minting again won't help - so give up.
        if freshly_minted:
            fail(f"401 Unauthorized - freshly minted token rejected by the API "
                 f"authorizer. {exc.detail}")
        print("info: TICKET_TOKEN rejected (401) - re-minting from "
              "TICKET_USERNAME/TICKET_PASSWORD.", file=sys.stderr)
        token = mint_token(env)
        persist_token(env_path, token)
        try:
            ticket = post_ticket(env, token, body)
        except Unauthorized as exc2:
            fail(f"401 Unauthorized even after re-minting a fresh token. {exc2.detail}")

    if args.json:
        print(json.dumps(ticket, indent=2))
    else:
        print("Ticket created:")
        print(f"  id:         {ticket.get('id')}")
        print(f"  status:     {ticket.get('status')}")
        print(f"  priority:   {ticket.get('priority')}")
        print(f"  createdAt:  {ticket.get('createdAt')}")
        print(f"  area:       {ticket.get('requestingArea')}")
        print(f"  reportedBy: {ticket.get('reportedBy')}")


if __name__ == "__main__":
    main()
