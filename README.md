# Internal Support Ticketing API

Serverless backend to create and query internal support tickets.
API Gateway HTTP API (Cognito JWT) → two least-privilege Lambdas → DynamoDB, with
SNS email notification on each new ticket. See `docs/research.md` for the design.

## Architecture

```
Client ──(JWT)──► API Gateway HTTP API ──JWT authorizer──► Cognito User Pool
        POST /tickets ──► createTicket Lambda ──► DynamoDB
                                 └──► SNS topic ──email──► support mailbox
        GET /tickets/{id}, GET /tickets?status= ──► getTicket Lambda ──► DynamoDB
```

## Prerequisites

- Terraform >= 1.6, AWS credentials configured, Python 3.13.

## Local development & tests

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -v
```

## Deploy

```bash
cd terraform
terraform init
terraform apply -var "support_email=you@example.com"
```

`terraform apply` runs `build.py` (vendors deps into each Lambda zip), then provisions
all resources. Confirm the SNS subscription email to receive notifications.

Capture the outputs:

```bash
terraform output
# api_base_url, user_pool_id, user_pool_client_id, sns_topic_arn, dynamodb_table
```

## Get a JWT for demoing the API

Create a user and set a permanent password (replace IDs with `terraform output` values):

```bash
aws cognito-idp admin-create-user \
  --user-pool-id <user_pool_id> --username demo@example.com --message-action SUPPRESS
aws cognito-idp admin-set-user-password \
  --user-pool-id <user_pool_id> --username demo@example.com \
  --password 'Passw0rd!' --permanent

aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --client-id <user_pool_client_id> \
  --auth-parameters USERNAME=demo@example.com,PASSWORD='Passw0rd!' \
  --query 'AuthenticationResult.IdToken' --output text
```

Use the returned token as `Authorization: Bearer <IdToken>`.

## Call the API

```bash
BASE=<api_base_url>
TOKEN=<IdToken>

# Create
curl -s -X POST "$BASE/tickets" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"priority":"high","description":"VPN down","requestingArea":"Finance","reportedBy":"jdoe"}'

# Get by id
curl -s "$BASE/tickets/<id>" -H "Authorization: Bearer $TOKEN"

# List open tickets (oldest first), paginated
curl -s "$BASE/tickets?status=open&limit=20" -H "Authorization: Bearer $TOKEN"
```

## Teardown

```bash
cd terraform
terraform destroy -var "support_email=you@example.com"
```
