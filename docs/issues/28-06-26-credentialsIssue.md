# Issue — `terraform plan` fails with `InvalidClientTokenId` despite a valid SSO login

**Date:** 2026-06-28
**Component:** Terraform (`terraform/`) · AWS credential resolution
**Status:** Resolved (workaround applied; permanent fix recommended)

## Symptom

Running the plan against the dev environment:

```bash
terraform -chdir=terraform plan -var-file=./environments/dev.tfvars
```

The configuration parsed and planned fine (`Plan: 25 to add`), but Terraform then
errored at the provider credential check:

```
Error: Retrieving AWS account details: validating provider credentials:
  retrieving caller identity from STS: operation error STS: GetCallerIdentity,
  https response error StatusCode: 403,
  api error InvalidClientTokenId: The security token included in the request is invalid.
  with provider["registry.terraform.io/hashicorp/aws"],
  on main.tf line 20, in provider "aws":
  20: provider "aws" {
```

This persisted **even after** a successful `aws sso login --sso-session bootcamp`.

## What made it confusing

`aws sts get-caller-identity` succeeded and returned the expected SSO identity:

```json
{
  "UserId": "AROAYS2NVS67OXH4F3WBU:Carlos",
  "Account": "590184028094",
  "Arn": "arn:aws:sts::590184028094:assumed-role/AWSReservedSSO_AdministratorAccess_.../Carlos"
}
```

So the AWS CLI resolved SSO correctly, while Terraform — in the same shell, with the
same `AWS_PROFILE=bootcamp-administrator-access` and **no** static creds in the
environment — still got a 403.

The `InvalidClientTokenId` error is the key clue: it means **static access keys were
sent and rejected**, not that credentials were missing (a missing SSO session produces
a different "no valid credential sources" error).

## Root cause

The profile `bootcamp-administrator-access` was defined in **two** places with a
**name collision**:

- `~/.aws/config` → defined it as an **SSO** profile (correct, freshly logged in):

  ```ini
  [sso-session bootcamp]
  sso_start_url = https://bootcampblockstellartcq.awsapps.com/start
  sso_region = us-east-1
  sso_registration_scopes = sso:account:access

  [profile bootcamp-administrator-access]
  sso_session     = bootcamp
  sso_account_id  = 590184028094
  sso_role_name   = AdministratorAccess
  region          = us-east-1
  ```

- `~/.aws/credentials` → had a stale section of the **same name** holding static keys:

  ```ini
  [bootcamp-administrator-access]
  aws_access_key_id     = <stale>
  aws_secret_access_key = <stale>
  ```

For a named profile, the shared **credentials** file takes precedence over the
**config** file. The AWS CLI v2 still resolved the SSO session, but Terraform's AWS SDK
(provider `~> 5.0`) picked up the **stale static keys** from `~/.aws/credentials` for
that profile name and sent them to STS → `InvalidClientTokenId`.

In short: same profile name, two definitions, different precedence rules between the
CLI and the Terraform SDK.

## How we diagnosed it

1. Confirmed the live identity worked: `aws sts get-caller-identity` → valid SSO ARN.
2. Inspected the shell env — `AWS_PROFILE=bootcamp-administrator-access`, **no**
   `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN` set. So the bad
   keys were not coming from the environment.
3. Inspected `~/.aws/config` and `~/.aws/credentials` and found the duplicate
   `bootcamp-administrator-access` entry — SSO in config, static keys in credentials.

## Resolution (workaround used)

Export the already-valid SSO session into environment variables (which outrank profile
resolution) for the Terraform run only — non-destructive, touches no files:

```bash
eval "$(aws configure export-credentials --profile bootcamp-administrator-access --format env)"
"C:/Program Files/terraform/terraform.exe" -chdir=terraform plan -var-file=./environments/dev.tfvars
```

Result:

```
Plan: 25 to add, 0 to change, 0 to destroy.
```

> Note: this export is **per-shell only**. It does not persist to a later
> `terraform apply` in a new shell — re-run the `eval` line, or apply the permanent fix.

## Permanent fix (recommended)

Remove the stale static-key block for this profile from `~/.aws/credentials` so the
name resolves to the SSO definition in `~/.aws/config` for both the CLI and Terraform:

```ini
# delete this whole section from ~/.aws/credentials
[bootcamp-administrator-access]
aws_access_key_id     = ...
aws_secret_access_key = ...
```

After that, both `aws` and `terraform` resolve the SSO session identically with no env
juggling. (Back up the file before editing.)

## Takeaways

- `InvalidClientTokenId` = static keys were sent and rejected — look for a stale
  credentials entry, not a missing SSO login.
- A profile name appearing in **both** `~/.aws/config` (SSO) and `~/.aws/credentials`
  (static) is a trap: the CLI and the Terraform AWS SDK can resolve it differently.
- `aws configure export-credentials --format env` is a clean, file-free way to hand a
  live SSO session to any tool that isn't resolving the profile correctly.
- Terraform's offline gates (`terraform test` with `mock_provider`, `terraform validate`)
  never hit this — only `plan`/`apply` touch real STS.

## Update — permanent fix applied (2026-06-28)

The recommended permanent fix was applied and verified:

- Backed up `~/.aws/credentials` → `~/.aws/credentials.bak-20260628`.
- Removed the stale `[bootcamp-administrator-access]` static-key section; `[default]`
  left untouched.
- Verified `terraform -chdir=terraform plan -var-file=./environments/dev.tfvars`
  succeeds with **no** env-export workaround and **no** static keys in the environment
  (`AWS_ACCESS_KEY_ID` unset) — the SSO profile now resolves cleanly, no
  `InvalidClientTokenId`.
