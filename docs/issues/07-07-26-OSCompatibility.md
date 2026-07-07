# Issue — `terraform apply` fails in `null_resource.build`: `exec: "PowerShell": executable file not found` on macOS

**Date:** 2026-07-07
**Component:** Terraform (`terraform/lambda.tf`, `terraform/variables.tf`) · `local-exec` provisioner · Lambda packaging
**Status:** Resolved

## Symptom

After cloning the repo (originally developed on Windows) onto a **macOS** host and running
`terraform apply`, packaging failed:

```
Error: local-exec provisioner error

  with null_resource.build,
  on lambda.tf line 27, in resource "null_resource" "build":
  27:   provisioner "local-exec" {

Error running command '& './../.venv/Scripts/python.exe' './build.py'':
exec: "PowerShell": executable file not found in $PATH. Output:
```

## What made it confusing

The error text names `PowerShell`, not Python — so it reads like a shell problem rather
than a portability problem. In reality **two** Windows-only assumptions are baked into the
provisioner at once, and the interpreter is simply the first one Terraform trips over:

1. the interpreter `PowerShell` does not exist on macOS/Linux, and
2. even past that, the Windows venv path `.venv/Scripts/python.exe` is wrong on Unix
   (it lives at `.venv/bin/python`).

A fresh clone also has **no `.venv` at all**, so the referenced interpreter is missing
regardless of OS.

## Root cause

The provisioner was hard-coded for Windows — the exact "future improvement" flagged in the
notes of [28-06-26-pathInterpreterIssues.md](28-06-26-pathInterpreterIssues.md):

```hcl
provisioner "local-exec" {
  interpreter = ["PowerShell", "-Command"]
  command     = "& '${path.module}/../.venv/Scripts/python.exe' '${path.module}/build.py'"
}
```

On macOS/Linux:

- `interpreter = ["PowerShell", ...]` → Terraform tries to `exec` a binary literally named
  `PowerShell`, which is not on `$PATH` → *"executable file not found in $PATH"*. (Even the
  cross-platform PowerShell binary is `pwsh`, not `PowerShell`.)
- `.venv/Scripts/python.exe` is the **Windows** venv layout. The POSIX layout is
  `.venv/bin/python`.

As with every prior issue in this log, the offline gates (`terraform validate`, `fmt`,
`test`) never run provisioners, so this only surfaced at `apply`.

## How we diagnosed it

1. Read the failing block — `lambda.tf` line 27, the `local-exec` provisioner.
2. Matched the error `exec: "PowerShell": ... not found in $PATH` to the literal
   `interpreter = ["PowerShell", "-Command"]` — a Windows-only interpreter.
3. Noted the second, latent problem: `.venv/Scripts/python.exe` is the Windows venv path;
   Unix uses `.venv/bin/python`.
4. Confirmed the host had **no `.venv`** yet (`ls .venv/bin/python` → not found), so the
   interpreter path could not resolve even after the OS fix.

## Resolution

Made the interpreter/path **OS-agnostic** instead of Windows-specific, and created the
missing venv.

**1. `terraform/variables.tf`** — introduce an overridable interpreter-path variable
(default = the POSIX layout):

```hcl
variable "python_bin" {
  type        = string
  description = "Path to the Python interpreter used to run build.py (relative to the terraform module dir, or absolute). macOS/Linux venv: ../.venv/bin/python | Windows venv: ../.venv/Scripts/python.exe"
  default     = "../.venv/bin/python"
}
```

**2. `terraform/lambda.tf`** — drop the hard-coded PowerShell interpreter (Terraform then
uses the host default: `/bin/sh -c` on Unix) and reference the variable:

```hcl
provisioner "local-exec" {
  command = "'${var.python_bin}' '${path.module}/build.py'"
}
```

**3. Create the venv the provisioner expects** (from `ticketing/`):

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
```

`build.py` only needs **pip** — it downloads Linux/cp313 wheels via pip's `--platform` /
`--python-version` / `--only-binary=:all:` flags, so the local interpreter need not be
Python 3.13 (3.12 was used here).

Windows users are unaffected: run
`terraform apply -var 'python_bin=../.venv/Scripts/python.exe'` (whose default interpreter
is `cmd.exe`).

### Verification

- Ran the exact command Terraform now issues, from `terraform/`:
  `'../.venv/bin/python' './build.py'` → `EXIT=0`, producing `build/create_ticket` and
  `build/get_ticket` with the correct Linux wheels vendored
  (`pydantic_core-...-manylinux2014_x86_64`, `python-ulid`, etc.).
- `terraform fmt` → clean; `terraform validate` → `Success! The configuration is valid.`

## Notes / caveats

- This supersedes the Windows-only fix in
  [28-06-26-pathInterpreterIssues.md](28-06-26-pathInterpreterIssues.md); the two files
  together document the full round-trip (Windows fix → cross-OS generalization).
- `.venv/` is environment-specific and must **not** be committed — confirm it is in
  `.gitignore`.
- Removing the `interpreter` line means the host default applies: `/bin/sh -c` on
  macOS/Linux, `cmd.exe` on Windows. The single-quoted command is POSIX-shell friendly;
  Windows relies on the `python_bin` override plus `cmd.exe` tolerating the quotes.

## Takeaways

- Provisioner commands are a portability trap: hard-coded `interpreter`, `.exe` suffixes,
  and `Scripts/` vs `bin/` venv layouts all break the moment the repo moves OS. Prefer a
  **variable** for the interpreter path and let Terraform pick the host-default shell.
- The surface error can name the wrong layer (here: `PowerShell`, not the venv path or the
  missing `.venv`). Check every OS-specific assumption in the block, not just the one that
  threw.
- A cloned repo has no `.venv` — packaging steps that shell out to a venv interpreter need
  that venv created first, independent of the Terraform fix.
