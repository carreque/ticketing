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
import json
import os
import sys
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


def get_token(env: dict) -> str:
    """Reuse TICKET_TOKEN if provided, else exchange username/password for an
    IdToken via Cognito USER_PASSWORD_AUTH (an unauthenticated public flow).

    Credentials are read from the .env values (env), with any matching real
    environment variable taking precedence so a per-call override still works."""
    token = os.environ.get("TICKET_TOKEN") or env.get("TICKET_TOKEN")
    if token:
        return token.removeprefix("Bearer ").strip()

    username = os.environ.get("TICKET_USERNAME") or env.get("TICKET_USERNAME")
    password = os.environ.get("TICKET_PASSWORD") or env.get("TICKET_PASSWORD")
    if not username or not password:
        fail("no credentials - set TICKET_USERNAME and TICKET_PASSWORD (or "
             "TICKET_TOKEN with a pre-obtained IdToken) in .env or the environment.")

    client_id = env.get("USER_POOL_CLIENT_ID")
    if not client_id:
        fail("USER_POOL_CLIENT_ID missing from .env - re-run scripts/gen_env.py.")

    try:
        import boto3
        from botocore import UNSIGNED
        from botocore.config import Config
    except ImportError:
        fail("boto3 is required to mint a JWT - `pip install boto3` (it's in "
             "requirements-dev.txt) or supply TICKET_TOKEN instead.")

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
             "Set a permanent password (see README) so no challenge is required.")
    return id_token


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
            fail(f"401 Unauthorized - token rejected by the API authorizer. {detail}")
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

    env = load_env(find_env_file(args.env_file))
    token = get_token(env)
    ticket = post_ticket(env, token, {
        "priority": args.priority,
        "description": args.description,
        "requestingArea": args.requesting_area,
        "reportedBy": args.reported_by,
    })

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
