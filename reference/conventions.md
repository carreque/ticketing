## Conventions from the plan

- We are going to follow a TDD approach. You will write the test and I will write the code to make the tests pass.
- You will avoid to commit any file where a sensitive information is stored there such as AWS keys, secrets or passwords.
- Every part of the system should be tested through a test before it is commited.
- `requirements.txt` = **runtime** deps vendored into Lambda zips (keep minimal: pydantic, python-ulid). `requirements-dev.txt` = test/dev deps. Don't add runtime deps that aren't needed inside the Lambda.
- Enums values should be in Uppercase.
- Powertools is supplied as the AWS-managed **layer** at runtime (`var.powertools_layer_arn`), not vendored.
- Terraform is split one file per service (`dynamodb.tf`, `sns.tf`, `iam.tf`, `lambda.tf`, `cognito.tf`, `apigw.tf`) so each change set is reviewable in isolation.