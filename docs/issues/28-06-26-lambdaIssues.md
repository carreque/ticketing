# Issue — every authenticated API call returns `Internal Server Error`: Lambda crashes at import (`No module named 'exceptions'`)

**Date:** 2026-06-28
**Component:** Lambda packaging (`terraform/build.py`) · `create_ticket` / `get_ticket` handlers
**Status:** Resolved

## Symptom

Infrastructure deployed successfully and the JWT authorizer worked (an unauthenticated
request correctly returned **401**). But **every authenticated request** — create, get,
list, and even deliberately-invalid input — returned:

```
HTTP 500
{"message":"Internal Server Error"}
```

The fact that even a request that should be a **400 validation_error** came back as 500
was the key tell: the function was failing **before any handler logic ran** — i.e. at
cold-start / import, so the outcome was identical regardless of input.

## Diagnosis

`terraform validate` / `terraform test` can't catch this (they never invoke the
function), so we went to the runtime logs.

1. Found the latest log stream and read the events:

   ```bash
   export MSYS_NO_PATHCONV=1   # stop Git Bash mangling the /aws/lambda/... name
   LG="/aws/lambda/ticketing-createTicket"
   STREAM=$(aws logs describe-log-streams --log-group-name "$LG" \
     --order-by LastEventTime --descending --max-items 1 \
     --query 'logStreams[0].logStreamName' --output text)
   aws logs get-log-events --log-group-name "$LG" --log-stream-name "$STREAM" \
     --query 'events[*].message' --output text
   ```

   > Side note: Git Bash rewrites a leading `/aws/lambda/...` into a Windows path,
   > producing `InvalidParameterException` on `logGroupName`. Prefix the command with
   > `MSYS_NO_PATHCONV=1` (or use the PowerShell tool) to stop the path conversion.

2. The log showed the real error:

   ```
   [ERROR] Runtime.ImportModuleError: Unable to import module 'create_ticket.handler':
   No module named 'exceptions'
   INIT_REPORT ... Phase: init  Status: error  Error Type: Runtime.ImportModuleError
   ```

3. Located the import in the source — both handlers depend on a custom module:

   ```
   src/create_ticket/handler.py:13:  from exceptions.apiError import ApiError
   src/get_ticket/handler.py:6:      from exceptions.apiError import ApiError
   ```

   `src/exceptions/apiError.py` exists and defines `ApiError`.

## Root cause

`terraform/build.py` vendors only an explicit allow-list of source packages into each
Lambda zip. That map did **not** include the `exceptions` package:

```python
FUNCS = {
    "create_ticket": ["create_ticket", "common"],
    "get_ticket": ["get_ticket", "common"],
}
```

So the deployed zips contained `create_ticket`/`get_ticket` + `common` but **not**
`exceptions/`. At runtime the very first `import` of the handler failed with
`No module named 'exceptions'`, crashing every invocation with a generic 500.

Why the unit tests didn't catch it: `pytest.ini` sets `pythonpath = src`, so
`exceptions` is importable during local tests. The gap existed **only in the packaged
artifact**, which the tests never exercise.

## Resolution

Add `exceptions` to both functions' package lists in `terraform/build.py`:

```python
FUNCS = {
    "create_ticket": ["create_ticket", "common", "exceptions"],
    "get_ticket": ["get_ticket", "common", "exceptions"],
}
```

Editing `build.py` changes the `null_resource.build` `builder` trigger
(`filemd5(build.py)`), so the next `terraform apply` repackages and the changed
`source_code_hash` updates both Lambda functions.

### Verification

- Local rebuild — `terraform/build/{create_ticket,get_ticket}/exceptions/apiError.py`
  present in both; `python -c "import exceptions.apiError"` (with the build dir on the
  path) succeeds.
- `terraform apply -auto-approve -var-file=./environments/dev.tfvars` →
  `1 added, 2 changed, 1 destroyed` (both Lambdas modified).
- Full API re-test, all green:

  | Test | Result |
  |------|--------|
  | no token | 401 |
  | `POST /tickets` (valid) | 201 (server-set `id`/`createdAt`/`status:"open"`) |
  | `GET /tickets/{id}` | 200 |
  | `GET /tickets?status=open` | 200 `{items:[…],nextCursor:null}` |
  | bad priority | 400 `validation_error` |
  | unknown id | 404 `not_found` |

## Takeaways

- `build.py` uses an **explicit package allow-list**, not "copy everything under src/".
  Any new top-level source package a handler imports (here, `exceptions`) must be added
  to that function's `FUNCS` entry, or it won't ship.
- A 500 that is identical for valid *and* invalid input points at **import/cold-start
  failure**, not handler logic — go straight to the function's CloudWatch logs.
- Passing unit tests are **not** proof the Lambda package is complete: `pythonpath=src`
  makes everything importable locally; only the zip reveals packaging gaps. Consider a
  build-time import smoke test against `terraform/build/<func>/` to catch this earlier.
- On Windows/Git Bash, prefix AWS CLI calls that take `/aws/lambda/...`-style names with
  `MSYS_NO_PATHCONV=1` to avoid POSIX→Windows path mangling.
