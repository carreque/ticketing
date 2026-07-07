#!/usr/bin/env python3
"""Create (or repair) the Cognito user that TICKET_USERNAME/TICKET_PASSWORD name.

`scripts/gen_env.py` writes a random TICKET_USERNAME/TICKET_PASSWORD into the
repo-root .env but deliberately does not create the matching Cognito user - so
the create-ticket flow has credentials that don't yet authenticate. This script
closes that gap: it reads USER_POOL_ID + TICKET_USERNAME/TICKET_PASSWORD from the
.env and, against the live user pool,

  1. AdminCreateUser (welcome email suppressed), and
  2. AdminSetUserPassword(..., Permanent=True)

so the account lands in CONFIRMED state and USER_PASSWORD_AUTH returns a token
instead of a NEW_PASSWORD_REQUIRED challenge.

Idempotent: if the user already exists, the create is treated as a no-op and the
permanent password is (re)asserted. No secret is ever printed.

Unlike create_ticket.py (which mints an *unsigned* public Cognito call), the
Admin* APIs are SigV4-signed and need real AWS credentials with
cognito-idp:AdminCreateUser + cognito-idp:AdminSetUserPassword - the same
principal you run `terraform apply` with. Run from the dev venv (needs boto3).

Usage:
  python .claude/skills/configure-cognito-user/scripts/configure_user.py

Optional:
  --env-file PATH   Path to the .env (default: repo-root .env, discovered upward).
"""
import argparse
import os
import sys
from pathlib import Path


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
    """Parse a KEY=value .env into a dict; a matching real environment variable
    wins, so callers can point at another stack/user per-call without editing
    the file (same convention as create_ticket.py)."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip().strip('"').strip("'")
    for key in ("USER_POOL_ID", "TICKET_USERNAME", "TICKET_PASSWORD"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def region_from(env: dict) -> str:
    if os.environ.get("AWS_REGION"):
        return os.environ["AWS_REGION"]
    # Cognito pool ids look like "us-east-1_ABC123XYZ".
    pool = env.get("USER_POOL_ID", "")
    if "_" in pool:
        return pool.split("_", 1)[0]
    fail("could not determine AWS region - set AWS_REGION.")


def configure_user(env: dict) -> None:
    pool_id = env.get("USER_POOL_ID")
    username = env.get("TICKET_USERNAME")
    password = env.get("TICKET_PASSWORD")
    missing = [k for k, v in (
        ("USER_POOL_ID", pool_id),
        ("TICKET_USERNAME", username),
        ("TICKET_PASSWORD", password),
    ) if not v]
    if missing:
        fail(f"missing from .env: {', '.join(missing)} - re-run "
             "`python scripts/gen_env.py` after `terraform apply`.")

    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
    except ImportError:
        fail("boto3 is required for the admin Cognito calls - activate the dev venv "
             "and `pip install -r requirements-dev.txt` (boto3 is listed there).")

    client = boto3.client("cognito-idp", region_name=region_from(env))

    created = True
    try:
        client.admin_create_user(
            UserPoolId=pool_id,
            Username=username,
            MessageAction="SUPPRESS",  # no welcome email; pool has no verified channel
        )
    except client.exceptions.UsernameExistsException:
        created = False  # idempotent: fall through and just (re)assert the password
    except client.exceptions.InvalidPasswordException as exc:
        fail(f"password rejected by the pool policy (min 8, upper+lower+digit): {exc}")
    except client.exceptions.ResourceNotFoundException:
        fail(f"user pool '{pool_id}' not found - stale USER_POOL_ID? re-run "
             "`python scripts/gen_env.py`.")
    except NoCredentialsError:
        fail("no AWS credentials found - configure the principal you run "
             "`terraform apply` with (needs cognito-idp:AdminCreateUser).")
    except (ClientError, BotoCoreError) as exc:
        fail(f"AdminCreateUser failed: {type(exc).__name__}: {exc}")

    try:
        client.admin_set_user_password(
            UserPoolId=pool_id,
            Username=username,
            Password=password,
            Permanent=True,  # -> CONFIRMED, so USER_PASSWORD_AUTH returns a token
        )
    except client.exceptions.InvalidPasswordException as exc:
        fail(f"password rejected by the pool policy (min 8, upper+lower+digit): {exc}")
    except (ClientError, BotoCoreError) as exc:
        fail(f"AdminSetUserPassword failed: {type(exc).__name__}: {exc}")

    status = "created" if created else "already existed -> password reset"
    print("Cognito user configured:")
    print(f"  username: {username}")
    print(f"  poolId:   {pool_id}")
    print(f"  status:   {status} (permanent password set; account CONFIRMED)")
    print("Next: mint a token / file a ticket with the create-ticket skill.")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Create/repair the Cognito user from .env credentials.")
    ap.add_argument("--env-file", dest="env_file")
    args = ap.parse_args()
    configure_user(load_env(find_env_file(args.env_file)))


if __name__ == "__main__":
    main()
