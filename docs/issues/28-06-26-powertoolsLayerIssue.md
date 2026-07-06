# Issue — `terraform apply` fails creating Lambdas: `AccessDeniedException` on `lambda:GetLayerVersion` for the Powertools layer

**Date:** 2026-06-28
**Component:** Terraform (`terraform/variables.tf`, `terraform/lambda.tf`) · Lambda · AWS-managed Powertools layer
**Status:** Resolved

## Symptom

During `terraform apply -var-file=./environments/dev.tfvars`, both Lambda functions
failed to create:

```
Error: creating Lambda Function (ticketing-createTicket): operation error Lambda:
  CreateFunction, https response error StatusCode: 403,
  api error AccessDeniedException: User:
  arn:aws:sts::590184028094:assumed-role/AWSReservedSSO_AdministratorAccess_.../Carlos
  is not authorized to perform: lambda:GetLayerVersion on resource:
  arn:aws:lambda:us-east-1:017000801446:layer:AWSLambdaPowertoolsPythonV3-python313-x86_64:3
  because no resource-based policy allows the lambda:GetLayerVersion action

  with aws_lambda_function.create_ticket, on lambda.tf line 33
```

(Same error for `aws_lambda_function.get_ticket`.)

## What made it confusing

The caller is `AWSReservedSSO_AdministratorAccess` — full admin on account
`590184028094`. An `AccessDenied` despite admin looks wrong at first glance.

The key phrase is **"because no resource-based policy allows the lambda:GetLayerVersion
action"**. The layer lives in account **`017000801446`** — AWS's *managed Powertools*
account, not ours. Using another account's layer requires **two** grants:

1. The caller's IAM identity allows `lambda:GetLayerVersion` (we have it via admin), **and**
2. The **layer version's resource-based policy** grants access to our principal/public.

AWS publishes the Powertools layers with a public resource policy — but **only for
versions that actually exist**. The config pinned version **`:3`**, which was never
published for this region/runtime/arch, so there is no resource policy granting it →
403. Admin on our account cannot override a resource policy owned by AWS's account.

## Root cause

`terraform/variables.tf` pinned a non-existent layer version:

```hcl
variable "powertools_layer_arn" {
  type    = string
  default = "arn:aws:lambda:us-east-1:017000801446:layer:AWSLambdaPowertoolsPythonV3-python313-x86_64:3"
}
```

Version `:3` is not a published version of this layer. Published versions are
region-specific and increment over time; the pinned `:3` was stale/invalid.

## How we diagnosed it

1. Confirmed it was **not** our IAM: caller is `AdministratorAccess`; the message points
   at a missing **resource-based** policy on a layer in account `017000801446`.
2. Probed the pinned version directly — denied:

   ```bash
   aws lambda get-layer-version-by-arn \
     --arn "arn:aws:lambda:us-east-1:017000801446:layer:AWSLambdaPowertoolsPythonV3-python313-x86_64:3" \
     --region us-east-1
   # AccessDeniedException ... no resource-based policy allows lambda:GetLayerVersion
   ```

3. Probed a range of version numbers — valid published versions are publicly readable
   and return success. Found `:4` through `:34` accessible; `:3` and `:35`+ not. So the
   latest published version was **`:34`**.
4. Verified `:34` compatibility:

   ```bash
   aws lambda get-layer-version-by-arn \
     --arn "arn:aws:lambda:us-east-1:017000801446:layer:AWSLambdaPowertoolsPythonV3-python313-x86_64:34" \
     --region us-east-1 \
     --query '{Arn:LayerVersionArn,Runtimes:CompatibleRuntimes,Archs:CompatibleArchitectures}'
   # Runtimes: ["python3.13"], Archs: ["x86_64"]  ✓
   ```

## Resolution

Pinned a currently-published, compatible version (`:34`) in two places:

- `terraform/variables.tf` — updated the `powertools_layer_arn` **default** from `:3`
  to `:34`.
- `terraform/environments/dev.tfvars` — explicitly pinned the layer for the dev
  environment so deploys don't silently drift with the default:

  ```hcl
  powertools_layer_arn = "arn:aws:lambda:us-east-1:017000801446:layer:AWSLambdaPowertoolsPythonV3-python313-x86_64:34"
  ```

`terraform validate` → `Success! The configuration is valid.` Re-running `apply` then
creates both Lambdas (state from the earlier partial apply — DynamoDB, SNS, IAM,
Cognito, the build — is retained).

## Notes / caveats

- **The layer version number is region-specific.** The account (`017000801446`), layer
  name, runtime and arch stay the same, but the *version* differs per region. Deploying
  to a region other than `us-east-1` requires looking up that region's version and
  overriding `powertools_layer_arn` in that environment's tfvars.
- Powertools publishes new layer versions over time; `:34` was the latest accessible at
  the time of writing (2026-06-28). Pinning a specific version (rather than chasing
  "latest") keeps deploys reproducible.
- This never surfaced in `terraform validate` / `terraform test` (mock provider) — only
  a real `apply` calls `GetLayerVersion`.

## Takeaways

- An `AccessDenied` on a cross-account ARN despite local admin usually means a
  **resource-based policy** problem on the *other* account's resource, not your IAM.
- For AWS-managed layers, verify the exact ARN/version exists and is shared before
  pinning: `aws lambda get-layer-version-by-arn --arn <arn> --region <r>`.
- Pin layer versions per environment (tfvars) for reproducibility; remember the version
  is region-specific.
