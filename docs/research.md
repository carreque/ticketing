# Research — Internal Support Ticketing API (Phase 1, Serverless Backend)

> How I would build the system shown in `ticketing.png` / described in `project.md`.
> Date: 2026-06-21 · Stack chosen: **Terraform · Python 3.13 · API Gateway HTTP API + Cognito · DynamoDB · SNS · CloudWatch**

---

## 1. Problem recap

A mid-sized financial-sector company needs a lightweight, managed, scalable backend
to **create** and **query** internal support tickets in a structured way, replacing
an informal email/spreadsheet process. Goals: remove duplicates and lost requests,
add traceability, and lay a foundation for later metrics and a portal — **not** a
full ITSM platform.

Stated requirements: create + query endpoints, DynamoDB persistence, basic
validation, clear error handling, CloudWatch logging/traceability, and
least-privilege IAM. SNS email confirmation was an intentional extra and is kept.

---

## 2. Decisions made (and why)

| Decision | Choice | Rationale |
|---|---|---|
| Deliverable | Working code + IaC | A buildable, deployable project, not just docs. |
| IaC tool | **Terraform** | Industry-standard, portfolio-friendly, strong state mgmt, cloud-agnostic. |
| Runtime | **Python 3.13** + boto3 | Concise, readable, excellent AWS support; presentable backend code. |
| Compute shape | **Two Lambdas** (`createTicket`, `getTicket`) | Each gets its own minimal role — strongest least-privilege story. |
| Email path | **SNS as-is** (topic + email subscription) | Matches the diagram; notifies a support mailbox per new ticket. |
| API auth | **Cognito** (JWT authorizer) | Realistic for an internal portal later; validates tokens at the gateway. |

### Two upgrades over the original `project.md` draft
1. **`logs:*` → scoped log permissions.** Replace the broad `logs:*` with
   `logs:CreateLogStream` + `logs:PutLogEvents` scoped to each function's log group
   (the log group itself is created by Terraform). Honors the least-privilege intent
   more rigorously.
2. **API Gateway type made explicit: HTTP API (API Gateway v2).** Native JWT
   authorizer for Cognito, cheaper and simpler than REST API for this stack.

---

## 3. Target architecture

```
Client ──(JWT)──► API Gateway HTTP API ──JWT authorizer──► Cognito User Pool
                        │
        POST /tickets ──┼──► createTicket Lambda ──PutItem──► DynamoDB
                        │           └──Publish──► SNS topic ──email──► support mailbox
   GET /tickets/{id} ───┤
   GET /tickets?status ─┴──► getTicket Lambda ──GetItem / Query──► DynamoDB
                                    │
                          both ─────┴──structured logs──► CloudWatch Logs
```

- **API Gateway HTTP API** is the single entry point. A **JWT authorizer** backed by
  a **Cognito User Pool** validates tokens, so unauthenticated requests never reach
  Lambda.
- **createTicket** validates the payload, writes to DynamoDB, and publishes to SNS.
- **getTicket** serves both get-by-id and filtered list/query (read-only).
- Both functions emit structured logs to **CloudWatch Logs**.
- Boundary is an **AWS Region** (no VPC — these managed serverless services don't
  need VPC placement; it would only add operational complexity).

---

## 4. Compute — least-privilege IAM

Two functions, two execution roles, each scoped to specific resource ARNs:

| Function | Triggers | IAM permissions |
|---|---|---|
| `createTicket` | `POST /tickets` | `dynamodb:PutItem` on table · `sns:Publish` on topic · scoped log perms |
| `getTicket` | `GET /tickets/{id}`, `GET /tickets` | `dynamodb:GetItem` / `Query` on table + index · scoped log perms |

Splitting create from read means the read path never holds write or publish
permissions — the key advantage over the single-`ticketProcessingRole` diagram.

---

## 5. Data model & DynamoDB design

- **Table `tickets`**, billing mode **PAY_PER_REQUEST** (on-demand): no capacity
  planning, fits spiky internal load, cost-efficient at low volume.
- **Primary key:** `id` (partition key) — a **ULID** (time-sortable, URL-safe,
  collision-resistant).
- **GSI `status-createdAt-index`:** PK = `status`, SK = `createdAt`.
  Enables `GET /tickets?status=open` returned oldest-first, which directly answers
  *"which tickets stay open longest."*

| Field | Type | Notes |
|---|---|---|
| `id` | S | ULID, server-generated |
| `createdAt` | S | ISO-8601 UTC, server-generated |
| `priority` | S | low \| medium \| high \| critical |
| `status` | S | open \| in_progress \| resolved (default `open`) |
| `description` | S | brief incident description |
| `requestingArea` | S | department submitting the request |
| `reportedBy` | S | identifying data of the reporting user |

*Future (noted, not built):* a `requestingArea` GSI for per-department metrics —
YAGNI for Phase 1.

---

## 6. API contracts

| Method / path | Behavior | Responses |
|---|---|---|
| `POST /tickets` | body `{priority, description, requestingArea, reportedBy}`; server sets `id`, `createdAt`, `status="open"` | **201** + ticket / **400** / **401** |
| `GET /tickets/{id}` | fetch one ticket | **200** ticket / **404** / **401** |
| `GET /tickets?status=open&limit=&cursor=` | paginated query on the GSI | **200** `{items, nextCursor}` / **401** |

- `priority` ∈ {low, medium, high, critical}; `status` ∈ {open, in_progress, resolved}.
- Pagination via DynamoDB `LastEvaluatedKey` exposed as an opaque `cursor`.

---

## 7. Validation, error handling, logging

- **Validation:** **Pydantic v2** models parse and validate the request body; invalid
  input returns **400** with field-level errors.
- **Errors:** consistent JSON `{ "error": <code>, "message": <text> }`.
  Status codes: 400 (validation), 401 (authorizer), 404 (not found), 500 (internal).
  No stack traces or internal details leaked to clients.
- **Logging / traceability:** **AWS Lambda Powertools (Python)** Logger emits
  structured JSON logs to CloudWatch with a correlation id per request — clean,
  idiomatic traceability satisfying the requirement.

---

## 8. Proposed project layout

```
ticketing/
  terraform/
    main.tf  variables.tf  outputs.tf
    apigw.tf  cognito.tf  lambda.tf  dynamodb.tf  sns.tf  iam.tf
  src/
    create_ticket/handler.py
    get_ticket/handler.py
    common/
      models.py        # Pydantic models + enums
      repository.py    # DynamoDB access
      responses.py     # standard JSON responses / errors
  tests/
    unit/              # pytest + moto mocks
  requirements.txt
  README.md
```

---

## 9. Testing & quality

- **Unit tests:** pytest + **moto** to mock DynamoDB and SNS. Cover: payload
  validation, create happy-path, get-by-id, status query, 404, and auth-failure shape.
- **IaC checks:** `terraform fmt` and `terraform validate` in the loop.
- **README:** deploy steps, how to obtain a Cognito JWT for demoing the API, and
  teardown instructions.

---

## 10. Scope boundaries

- **In scope (Phase 1):** structured ticket creation + query, persistence,
  validation, error handling, logging/traceability, least-privilege IAM, SNS email
  confirmation, Cognito auth.
- **Out of scope (future phases):** full service-desk / ITSM platform, internal
  portal, web application, per-department metrics dashboards, integrations with other
  corporate systems.

---

## 11. Notable design insight — SNS vs SES

The diagram labels the SNS edge "Send Email" as a confirmation back to the
*reporting user*. In reality **SNS publishes to subscribers of a topic** — it cannot
natively send a personalized transactional email to an arbitrary reporter's address
per ticket. For Phase 1 we keep SNS as a **support-team notification** (a fixed
mailbox / the support team subscribes to the topic and is notified on each new
ticket). **Amazon SES** is the correct service for true per-reporter transactional
email and is the recommended path for a future phase.
