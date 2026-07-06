# Issue — `terraform apply` fails in the `null_resource.build` local-exec provisioner on Windows

**Date:** 2026-06-28
**Component:** Terraform (`terraform/lambda.tf`) · `local-exec` provisioner · Lambda packaging
**Status:** Resolved

## Symptom

During `terraform apply -var-file=./environments/dev.tfvars`, packaging failed:

```
Error: local-exec provisioner error

  with null_resource.build,
  on lambda.tf line 27, in resource "null_resource" "build":
  27:   provisioner "local-exec" {

Error running command './../.venv/Scripts/python.exe ./build.py': exit status 1.
Output: "." no se reconoce como un comando interno o externo,
programa o archivo por lotes ejecutable.
```

The Spanish message translates to: **"'.' is not recognized as an internal or external
command, operable program or batch file."**

## Root cause

The provisioner was:

```hcl
provisioner "local-exec" {
  command = "${path.module}/../.venv/Scripts/python.exe ${path.module}/build.py"
}
```

When Terraform is invoked with `-chdir=terraform`, `path.module` resolves to `.`, so the
command string becomes:

```
./../.venv/Scripts/python.exe ./build.py
```

On Windows, `local-exec` runs through **`cmd.exe`** by default. `cmd.exe` does not accept
a leading `./` with **forward slashes** for an executable path — it parses the leading
`.` as the command name (and `/...` as switches), producing the *"'.' is not recognized"*
error. The build never ran.

This was invisible to the offline gates: `terraform validate`, `terraform fmt`, and
`terraform test` (with `mock_provider`) **never execute provisioners**, so the problem
only surfaced at `apply`.

## How we diagnosed it

1. Read the failing block — `lambda.tf` line 27, the `local-exec` provisioner.
2. Recognized `path.module == "."` under `-chdir=terraform`, making the command
   `./../.venv/Scripts/python.exe ./build.py`.
3. Identified the default Windows interpreter (`cmd.exe`) as unable to handle the
   forward-slash `./` executable path — the source of *"'.' is not recognized"*.

## Resolution

Run the provisioner through **PowerShell** (which handles forward slashes and `./`
relative paths) instead of the default `cmd.exe`, invoking the interpreter with the `&`
call operator and quoting the paths (so spaces are also safe):

```hcl
provisioner "local-exec" {
  interpreter = ["PowerShell", "-Command"]
  command     = "& '${path.module}/../.venv/Scripts/python.exe' '${path.module}/build.py'"
}
```

### Verification

- `terraform fmt` → clean; `terraform validate` → `Success! The configuration is valid.`
- Ran the exact command Terraform now issues, from the `terraform/` directory:

  ```powershell
  & './../.venv/Scripts/python.exe' './build.py'
  ```

  Result: `EXIT=0`, with both `terraform/build/create_ticket` and
  `terraform/build/get_ticket` produced (vendored `pydantic`, `pydantic-core` cp313,
  `python-ulid`, etc.). Re-running `terraform apply` then proceeds past the build step.

## Notes / caveats

- **Windows-specific.** This fix hard-codes the PowerShell interpreter and the
  `.venv/Scripts/python.exe` path. On macOS/Linux the interpreter line must be removed
  (or made conditional) and the path changed to `.venv/bin/python` — consistent with the
  note in `AGENTS.md`. A future improvement is to make the interpreter/path OS-agnostic
  via a variable.
- Because the previous `apply` failed **inside** the provisioner, `null_resource.build`
  was never marked created, so the build re-runs on the next `apply` (the packaging step
  is idempotent — it wipes and rebuilds `terraform/build/`).
- Offline Terraform gates do not run provisioners; only `plan` (partially) and `apply`
  exercise this path. Validate/test passing is **not** evidence the build provisioner
  works.

## Takeaways

- On Windows, `local-exec` defaults to `cmd.exe`; forward-slash `./` executable paths
  fail. Set `interpreter = ["PowerShell", "-Command"]` (or convert to backslash paths)
  for relative-path commands.
- Use the PowerShell `&` call operator and single-quote paths when the executable path is
  built from interpolations.
- `path.module` is **relative** (`.` under `-chdir`), so any command built from it is a
  relative path the chosen interpreter must understand.
