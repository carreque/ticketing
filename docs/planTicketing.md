# Internal Support Ticketing API — Implementation Plan

**Goal:** Build a serverless internal support-ticketing backend that lets authenticated users create and query tickets, persisted in DynamoDB, with email notification on creation, deployed entirely via Terraform.

**Architecture:** API Gateway HTTP API (JWT authorizer backed by a Cognito User Pool) fronts two least-privilege Lambdas — `createTicket` (validate → write DynamoDB → publish SNS) and `getTicket` (get-by-id and status-filtered query on a GSI). Application logic lives in pure, unit-tested Python modules; infrastructure is declared in Terraform. The build vendors runtime dependencies into each Lambda package and uses the AWS-managed Powertools layer for structured logging.

**Tech Stack:** Terraform ≥1.6 (AWS provider ~>5.0), Python 3.13 + boto3, Pydantic v2, python-ulid, AWS Lambda Powertools (Logger), DynamoDB (PAY_PER_REQUEST + GSI), SNS, Cognito, API Gateway v2. Tests: pytest + moto.

## Global Constraints

- **Terraform:** `required_version >= 1.6`; AWS provider `~> 5.0`, archive provider `~> 2.0`, null provider `~> 3.0`.
- **Python runtime:** `python3.13` for all Lambdas.
- **Resource naming:** every AWS resource name is prefixed with `var.project_name` (default `ticketing`).
- **DynamoDB table:** name `${project_name}-tickets`, partition key `id` (S), billing mode `PAY_PER_REQUEST`, one GSI `status-createdAt-index` (PK `status` S, SK `createdAt` S, projection ALL).
- **Field domains:** `priority` ∈ {`low`,`medium`,`high`,`critical`}; `status` ∈ {`open`,`in_progress`,`resolved`}; new tickets always get `status="open"`.
- **Server-generated fields:** `id` (ULID string), `createdAt` (ISO-8601 UTC), `status`. Clients may never set these.
- **IAM:** least privilege — `createTicket` gets only `dynamodb:PutItem` + `sns:Publish` + scoped logs; `getTicket` gets only `dynamodb:GetItem`/`Query` + scoped logs. No `logs:*`; use `logs:CreateLogStream` + `logs:PutLogEvents` scoped to each function's log group.
- **Error envelope:** all error responses are JSON `{"error": <code>, "message": <text>}`. No stack traces or internal details leaked to clients.
- **Pagination:** DynamoDB `LastEvaluatedKey` is exposed to clients only as an opaque base64 `cursor` / `nextCursor`.

---

## File Structure

```
ticketing/
  pytest.ini                       # pytest config: pythonpath=src, testpaths=tests
  requirements.txt                 # RUNTIME deps vendored into Lambda zips (pydantic, python-ulid)
  requirements-dev.txt             # test/dev deps (adds boto3, powertools, pytest, moto)
  README.md                        # deploy / JWT demo / teardown
  src/
    common/
      __init__.py
      models.py                    # Pydantic models + Priority/Status enums
      responses.py                 # JSON response/error builders + cursor encode/decode
      repository.py                # DynamoDB access (put / get / query_by_status)
    create_ticket/
      __init__.py
      handler.py                   # POST /tickets
    get_ticket/
      __init__.py
      handler.py                   # GET /tickets/{id} and GET /tickets?status=
  tests/
    conftest.py                    # env defaults, moto `aws` fixture, FakeContext
    unit/
      test_models.py
      test_responses.py
      test_repository.py
      test_create_handler.py
      test_get_handler.py
  terraform/
    main.tf                        # providers + version pins + data sources
    variables.tf
    dynamodb.tf
    sns.tf
    iam.tf                         # log groups + two roles/policies
    lambda.tf                      # build trigger + archives + two functions
    build.py                       # cross-platform packaging (pip --platform + copy src)
    cognito.tf
    apigw.tf                       # HTTP API + JWT authorizer + routes + permissions
    outputs.tf
```

**Responsibility boundaries:** `common/` is pure, cloud-aware-but-injectable logic (testable with moto, no API Gateway coupling). Each handler is a thin adapter: parse event → call common → format response. Terraform files split by service so each change set is reviewable in isolation.

---

## Task 1: Project scaffold, dependencies, and test harness

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `pytest.ini`
- Create: `src/common/__init__.py`, `src/create_ticket/__init__.py`, `src/get_ticket/__init__.py` (all empty)
- Create: `tests/conftest.py`
- Test: `tests/unit/test_smoke.py` (temporary, deleted at end of task)

**Interfaces:**
- Produces: the `aws` pytest fixture (moto-backed DynamoDB table `ticketing-tickets` + GSI + SNS topic, env vars set) and `FakeContext` / `lambda_context` fixture, both consumed by Tasks 4–6.
- Produces: env contract — `TABLE_NAME=ticketing-tickets`, `SNS_TOPIC_ARN`, `AWS_DEFAULT_REGION=us-east-1`.

- [ ] **Step 1: Create `requirements.txt` (runtime deps vendored into Lambda)**

```text
pydantic==2.*
python-ulid==2.*
```

- [ ] **Step 2: Create `requirements-dev.txt`**

```text
-r requirements.txt
boto3>=1.34
aws-lambda-powertools==3.*
pytest>=8.0
moto[dynamodb,sns]>=5.0
```

- [ ] **Step 3: Create `pytest.ini`**

```ini
[pytest]
pythonpath = src
testpaths = tests
```

- [ ] **Step 4: Create the three empty `__init__.py` package files**

Create `src/common/__init__.py`, `src/create_ticket/__init__.py`, `src/get_ticket/__init__.py`, each as an empty file.

- [ ] **Step 5: Create `tests/conftest.py`**

```python
import os

# Set before any boto3 import so clients never reach real AWS.
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("TABLE_NAME", "ticketing-tickets")
os.environ.setdefault("SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:123456789012:ticketing-notifications")

import boto3  # noqa: E402  (must come after env defaults)
import pytest  # noqa: E402
from moto import mock_aws  # noqa: E402


class FakeContext:
    function_name = "test"
    memory_limit_in_mb = 128
    invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:test"
    aws_request_id = "req-test-1"


@pytest.fixture
def lambda_context():
    return FakeContext()


@pytest.fixture
def aws(monkeypatch):
    """Moto-backed DynamoDB table (+GSI) and SNS topic matching the Terraform schema."""
    with mock_aws():
        ddb = boto3.resource("dynamodb")
        ddb.create_table(
            TableName="ticketing-tickets",
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "id", "AttributeType": "S"},
                {"AttributeName": "status", "AttributeType": "S"},
                {"AttributeName": "createdAt", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "status-createdAt-index",
                    "KeySchema": [
                        {"AttributeName": "status", "KeyType": "HASH"},
                        {"AttributeName": "createdAt", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
        )
        sns = boto3.client("sns")
        topic_arn = sns.create_topic(Name="ticketing-notifications")["TopicArn"]
        monkeypatch.setenv("SNS_TOPIC_ARN", topic_arn)
        monkeypatch.setenv("TABLE_NAME", "ticketing-tickets")
        yield
```

- [ ] **Step 6: Create a temporary smoke test `tests/unit/test_smoke.py`**

```python
def test_harness_runs():
    assert True
```

- [ ] **Step 7: Install dev deps and run the smoke test to verify the harness works**

Run:
```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests/unit/test_smoke.py -v
```
Expected: `1 passed`.

- [ ] **Step 8: Delete the temporary smoke test**

Delete `tests/unit/test_smoke.py`.

- [ ] **Step 9: Commit**

```bash
git add requirements.txt requirements-dev.txt pytest.ini src tests
git commit -m "chore: project scaffold, deps, and pytest+moto harness"
```

---

## Task 2: Pydantic models and enums (`common/models.py`)

**Files:**
- Create: `src/common/models.py`
- Test: `tests/unit/test_models.py`

**Interfaces:**
- Produces: `Priority(str, Enum)` with members `low|medium|high|critical`; `Status(str, Enum)` with members `open|in_progress|resolved`; `TicketCreate` (fields `priority: Priority`, `description: str`, `requestingArea: str`, `reportedBy: str`; rejects extra/missing/blank). Consumed by Task 5 (`createTicket`) and Task 6 (`getTicket` validates the `status` query param against `Status`).

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_models.py`:
```python
import pytest
from pydantic import ValidationError

from common.models import Priority, Status, TicketCreate


def test_valid_ticket_create():
    t = TicketCreate(
        priority="high", description="Printer down",
        requestingArea="Finance", reportedBy="jdoe",
    )
    assert t.priority is Priority.high
    assert t.description == "Printer down"


def test_status_enum_values():
    assert {s.value for s in Status} == {"open", "in_progress", "resolved"}


def test_invalid_priority_rejected():
    with pytest.raises(ValidationError):
        TicketCreate(priority="urgent", description="x", requestingArea="IT", reportedBy="a")


def test_missing_field_rejected():
    with pytest.raises(ValidationError):
        TicketCreate(priority="low", description="x", requestingArea="IT")


def test_extra_field_rejected():
    with pytest.raises(ValidationError):
        TicketCreate(
            priority="low", description="x", requestingArea="IT",
            reportedBy="a", status="open",
        )


def test_blank_description_rejected():
    with pytest.raises(ValidationError):
        TicketCreate(priority="low", description="", requestingArea="IT", reportedBy="a")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'common.models'`.

- [ ] **Step 3: Write the minimal implementation**

`src/common/models.py`:
```python
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Priority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Status(str, Enum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"


class TicketCreate(BaseModel):
    """Client-supplied fields for POST /tickets. Server fields are not accepted here."""

    model_config = ConfigDict(extra="forbid")

    priority: Priority
    description: str = Field(min_length=1, max_length=2000)
    requestingArea: str = Field(min_length=1, max_length=200)
    reportedBy: str = Field(min_length=1, max_length=200)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_models.py -v`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/common/models.py tests/unit/test_models.py
git commit -m "feat: ticket models and priority/status enums"
```

---

## Task 3: Response builders and cursor codec (`common/responses.py`)

**Files:**
- Create: `src/common/responses.py`
- Test: `tests/unit/test_responses.py`

**Interfaces:**
- Produces: `response(status_code: int, body: dict) -> dict` (API Gateway v2 proxy shape with JSON `Content-Type`); `error(status_code: int, code: str, message: str) -> dict`; `encode_cursor(key: dict | None) -> str | None`; `decode_cursor(cursor: str | None) -> dict | None`. Consumed by Tasks 5 and 6.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_responses.py`:
```python
import json

from common.responses import response, error, encode_cursor, decode_cursor


def test_response_shape():
    r = response(201, {"id": "1"})
    assert r["statusCode"] == 201
    assert r["headers"]["Content-Type"] == "application/json"
    assert json.loads(r["body"]) == {"id": "1"}


def test_error_shape():
    r = error(404, "not_found", "Ticket not found")
    assert r["statusCode"] == 404
    assert json.loads(r["body"]) == {"error": "not_found", "message": "Ticket not found"}


def test_cursor_roundtrip():
    key = {"id": "01H", "status": "open", "createdAt": "2026-01-01T00:00:00+00:00"}
    enc = encode_cursor(key)
    assert isinstance(enc, str)
    assert decode_cursor(enc) == key


def test_cursor_none_passthrough():
    assert encode_cursor(None) is None
    assert decode_cursor(None) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_responses.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'common.responses'`.

- [ ] **Step 3: Write the minimal implementation**

`src/common/responses.py`:
```python
import base64
import json


def response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def error(status_code: int, code: str, message: str) -> dict:
    return response(status_code, {"error": code, "message": message})


def encode_cursor(key: dict | None) -> str | None:
    if not key:
        return None
    raw = json.dumps(key, sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str | None) -> dict | None:
    if not cursor:
        return None
    raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
    return json.loads(raw.decode("utf-8"))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_responses.py -v`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/common/responses.py tests/unit/test_responses.py
git commit -m "feat: JSON response/error builders and opaque pagination cursor"
```

---

## Task 4: DynamoDB repository (`common/repository.py`)

**Files:**
- Create: `src/common/repository.py`
- Test: `tests/unit/test_repository.py`

**Interfaces:**
- Produces: `class TicketRepository`. Constructor `TicketRepository(table=None)` — when `table` is None it binds `boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])`. Methods: `put(ticket: dict) -> None`; `get(ticket_id: str) -> dict | None`; `query_by_status(status: str, limit: int = 20, cursor: dict | None = None) -> tuple[list[dict], dict | None]` returning `(items_oldest_first, last_evaluated_key_or_None)`. Consumed by Tasks 5 and 6.
- Module constant: `STATUS_INDEX = "status-createdAt-index"`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_repository.py`:
```python
from common.repository import TicketRepository


def _ticket(tid, created_at, status="open"):
    return {
        "id": tid, "createdAt": created_at, "status": status,
        "priority": "low", "description": "d",
        "requestingArea": "IT", "reportedBy": "a",
    }


def test_put_and_get(aws):
    repo = TicketRepository()
    t = _ticket("t1", "2026-01-01T00:00:00+00:00")
    repo.put(t)
    assert repo.get("t1") == t


def test_get_missing_returns_none(aws):
    repo = TicketRepository()
    assert repo.get("nope") is None


def test_query_by_status_oldest_first(aws):
    repo = TicketRepository()
    for tid, ts in [("t0", "2026-01-03"), ("t1", "2026-01-01"), ("t2", "2026-01-02")]:
        repo.put(_ticket(tid, ts))
    items, cursor = repo.query_by_status("open", limit=10)
    assert [i["createdAt"] for i in items] == ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert cursor is None


def test_query_pagination(aws):
    repo = TicketRepository()
    for i in range(3):
        repo.put(_ticket(f"t{i}", f"2026-01-0{i + 1}"))
    first, cursor = repo.query_by_status("open", limit=2)
    assert len(first) == 2
    assert cursor is not None
    second, cursor2 = repo.query_by_status("open", limit=2, cursor=cursor)
    assert len(second) == 1
    assert cursor2 is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'common.repository'`.

- [ ] **Step 3: Write the minimal implementation**

`src/common/repository.py`:
```python
import os

import boto3
from boto3.dynamodb.conditions import Key

STATUS_INDEX = "status-createdAt-index"


class TicketRepository:
    def __init__(self, table=None):
        if table is None:
            table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
        self.table = table

    def put(self, ticket: dict) -> None:
        self.table.put_item(Item=ticket)

    def get(self, ticket_id: str) -> dict | None:
        resp = self.table.get_item(Key={"id": ticket_id})
        return resp.get("Item")

    def query_by_status(
        self, status: str, limit: int = 20, cursor: dict | None = None
    ) -> tuple[list[dict], dict | None]:
        kwargs = {
            "IndexName": STATUS_INDEX,
            "KeyConditionExpression": Key("status").eq(status),
            "Limit": limit,
            "ScanIndexForward": True,  # createdAt ascending → oldest first
        }
        if cursor:
            kwargs["ExclusiveStartKey"] = cursor
        resp = self.table.query(**kwargs)
        return resp.get("Items", []), resp.get("LastEvaluatedKey")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_repository.py -v`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/common/repository.py tests/unit/test_repository.py
git commit -m "feat: DynamoDB repository with status-index query and pagination"
```

---

## Task 5: `createTicket` handler (`create_ticket/handler.py`)

**Files:**
- Create: `src/create_ticket/handler.py`
- Test: `tests/unit/test_create_handler.py`

**Interfaces:**
- Consumes: `TicketCreate`, `Status` (Task 2); `response`, `error` (Task 3); `TicketRepository` (Task 4).
- Produces: `handler(event, context) -> dict`. Reads `event["body"]` (JSON string). On success: generates `id` (ULID), `createdAt` (ISO-8601 UTC), `status="open"`, writes via `repo.put`, publishes the ticket JSON to `SNS_TOPIC_ARN` (skipped if unset), returns **201** with the ticket. Errors: **400** `invalid_json` on unparseable body, **400** `validation_error` on schema failure. Module global `repo` (a `TicketRepository`) is reassignable by tests.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_create_handler.py`:
```python
import json

import create_ticket.handler as create_mod
from common.repository import TicketRepository


def _event(body_dict):
    return {"body": json.dumps(body_dict), "requestContext": {"requestId": "req-1"}}


def test_create_happy_path(aws, lambda_context):
    create_mod.repo = TicketRepository()
    resp = create_mod.handler(
        _event({
            "priority": "high", "description": "VPN down",
            "requestingArea": "Finance", "reportedBy": "jdoe",
        }),
        lambda_context,
    )
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["status"] == "open"
    assert body["priority"] == "high"
    assert body["id"]
    assert body["createdAt"]
    assert create_mod.repo.get(body["id"]) is not None


def test_create_rejects_client_status(aws, lambda_context):
    create_mod.repo = TicketRepository()
    resp = create_mod.handler(
        _event({
            "priority": "low", "description": "x", "requestingArea": "IT",
            "reportedBy": "a", "status": "resolved",
        }),
        lambda_context,
    )
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"] == "validation_error"


def test_create_invalid_priority(aws, lambda_context):
    create_mod.repo = TicketRepository()
    resp = create_mod.handler(
        _event({"priority": "urgent", "description": "x",
                "requestingArea": "IT", "reportedBy": "a"}),
        lambda_context,
    )
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"] == "validation_error"


def test_create_bad_json(aws, lambda_context):
    create_mod.repo = TicketRepository()
    resp = create_mod.handler(
        {"body": "{not json", "requestContext": {"requestId": "r"}},
        lambda_context,
    )
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"] == "invalid_json"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_create_handler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'create_ticket.handler'`.

- [ ] **Step 3: Write the minimal implementation**

`src/create_ticket/handler.py`:
```python
import json
import os
from datetime import datetime, timezone

import boto3
from aws_lambda_powertools import Logger
from pydantic import ValidationError
from ulid import ULID

from common.models import Status, TicketCreate
from common.repository import TicketRepository
from common.responses import error, response

logger = Logger(service="createTicket")
repo = TicketRepository()
sns = boto3.client("sns")


@logger.inject_lambda_context(correlation_id_path="requestContext.requestId")
def handler(event, context):
    raw = event.get("body") or "{}"
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("request body is not valid JSON")
        return error(400, "invalid_json", "Request body is not valid JSON")

    try:
        data = TicketCreate.model_validate(body)
    except ValidationError as exc:
        fields = ", ".join(".".join(str(p) for p in e["loc"]) for e in exc.errors())
        logger.warning("validation failed", extra={"fields": fields})
        return error(400, "validation_error", f"Invalid or missing fields: {fields}")

    ticket = {
        "id": str(ULID()),
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "status": Status.open.value,
        "priority": data.priority.value,
        "description": data.description,
        "requestingArea": data.requestingArea,
        "reportedBy": data.reportedBy,
    }

    repo.put(ticket)

    topic_arn = os.environ.get("SNS_TOPIC_ARN")
    if topic_arn:
        sns.publish(
            TopicArn=topic_arn,
            Subject="New support ticket",
            Message=json.dumps(ticket),
        )

    logger.info("ticket created", extra={"ticket_id": ticket["id"]})
    return response(201, ticket)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_create_handler.py -v`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/create_ticket/handler.py tests/unit/test_create_handler.py
git commit -m "feat: createTicket handler (validate, persist, notify)"
```

---

## Task 6: `getTicket` handler (`get_ticket/handler.py`)

**Files:**
- Create: `src/get_ticket/handler.py`
- Test: `tests/unit/test_get_handler.py`

**Interfaces:**
- Consumes: `Status` (Task 2); `response`, `error`, `encode_cursor`, `decode_cursor` (Task 3); `TicketRepository` (Task 4).
- Produces: `handler(event, context) -> dict`. If `event["pathParameters"]["id"]` is present → get-by-id: **200** ticket or **404** `not_found`. Otherwise list mode on `event["queryStringParameters"]`: requires `status` (**400** `validation_error` if missing or not a valid `Status`); optional `limit` (default 20) and `cursor`; returns **200** `{"items": [...], "nextCursor": <str|null>}`. Module global `repo` is reassignable by tests.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_get_handler.py`:
```python
import json

import get_ticket.handler as get_mod
from common.repository import TicketRepository


def _seed(repo):
    repo.put({
        "id": "abc", "createdAt": "2026-01-01T00:00:00+00:00", "status": "open",
        "priority": "low", "description": "d", "requestingArea": "IT", "reportedBy": "a",
    })


def test_get_by_id_found(aws, lambda_context):
    get_mod.repo = TicketRepository()
    _seed(get_mod.repo)
    resp = get_mod.handler({"pathParameters": {"id": "abc"}}, lambda_context)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["id"] == "abc"


def test_get_by_id_not_found(aws, lambda_context):
    get_mod.repo = TicketRepository()
    resp = get_mod.handler({"pathParameters": {"id": "missing"}}, lambda_context)
    assert resp["statusCode"] == 404
    assert json.loads(resp["body"])["error"] == "not_found"


def test_list_by_status(aws, lambda_context):
    get_mod.repo = TicketRepository()
    _seed(get_mod.repo)
    resp = get_mod.handler({"queryStringParameters": {"status": "open"}}, lambda_context)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert len(body["items"]) == 1
    assert body["nextCursor"] is None


def test_list_missing_status(aws, lambda_context):
    get_mod.repo = TicketRepository()
    resp = get_mod.handler({"queryStringParameters": None}, lambda_context)
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"] == "validation_error"


def test_list_invalid_status(aws, lambda_context):
    get_mod.repo = TicketRepository()
    resp = get_mod.handler({"queryStringParameters": {"status": "banana"}}, lambda_context)
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"] == "validation_error"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_get_handler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'get_ticket.handler'`.

- [ ] **Step 3: Write the minimal implementation**

`src/get_ticket/handler.py`:
```python
from aws_lambda_powertools import Logger

from common.models import Status
from common.repository import TicketRepository
from common.responses import decode_cursor, encode_cursor, error, response

logger = Logger(service="getTicket")
repo = TicketRepository()


@logger.inject_lambda_context
def handler(event, context):
    path_params = event.get("pathParameters") or {}
    ticket_id = path_params.get("id")

    if ticket_id:
        item = repo.get(ticket_id)
        if item is None:
            return error(404, "not_found", "Ticket not found")
        return response(200, item)

    qs = event.get("queryStringParameters") or {}
    status = qs.get("status")
    if not status:
        return error(400, "validation_error", "Query parameter 'status' is required")
    try:
        Status(status)
    except ValueError:
        return error(400, "validation_error", f"Invalid status value: {status}")

    try:
        limit = int(qs.get("limit", 20))
    except (TypeError, ValueError):
        return error(400, "validation_error", "Query parameter 'limit' must be an integer")

    cursor = decode_cursor(qs.get("cursor"))
    items, last_key = repo.query_by_status(status, limit=limit, cursor=cursor)
    return response(200, {"items": items, "nextCursor": encode_cursor(last_key)})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_get_handler.py -v`
Expected: `5 passed`.

- [ ] **Step 5: Run the full suite as a regression gate**

Run: `python -m pytest -v`
Expected: all tests pass (Tasks 2–6).

- [ ] **Step 6: Commit**

```bash
git add src/get_ticket/handler.py tests/unit/test_get_handler.py
git commit -m "feat: getTicket handler (get-by-id and status query with pagination)"
```

---

## Task 7: Terraform foundation — providers, variables, DynamoDB, SNS

**Files:**
- Create: `terraform/main.tf`
- Create: `terraform/variables.tf`
- Create: `terraform/dynamodb.tf`
- Create: `terraform/sns.tf`

**Interfaces:**
- Produces (referenced by later Terraform tasks): `aws_dynamodb_table.tickets` (`.arn`, `.name`); `aws_sns_topic.tickets` (`.arn`); `data.aws_caller_identity.current`; `data.aws_region.current`; vars `project_name`, `aws_region`, `support_email`.

- [ ] **Step 1: Create `terraform/main.tf`**

```hcl
terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

data "aws_region" "current" {}
```

- [ ] **Step 2: Create `terraform/variables.tf`**

```hcl
variable "project_name" {
  type        = string
  description = "Prefix applied to all resource names."
  default     = "ticketing"
}

variable "aws_region" {
  type        = string
  description = "AWS region to deploy into."
  default     = "us-east-1"
}

variable "support_email" {
  type        = string
  description = "Email address subscribed to the SNS topic for new-ticket notifications."
}
```

- [ ] **Step 3: Create `terraform/dynamodb.tf`**

```hcl
resource "aws_dynamodb_table" "tickets" {
  name         = "${var.project_name}-tickets"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }

  attribute {
    name = "status"
    type = "S"
  }

  attribute {
    name = "createdAt"
    type = "S"
  }

  global_secondary_index {
    name            = "status-createdAt-index"
    hash_key        = "status"
    range_key       = "createdAt"
    projection_type = "ALL"
  }

  tags = {
    Project = var.project_name
  }
}
```

- [ ] **Step 4: Create `terraform/sns.tf`**

```hcl
resource "aws_sns_topic" "tickets" {
  name = "${var.project_name}-notifications"
}

resource "aws_sns_topic_subscription" "support_email" {
  topic_arn = aws_sns_topic.tickets.arn
  protocol  = "email"
  endpoint  = var.support_email
}
```

- [ ] **Step 5: Initialize and validate**

Run:
```bash
cd terraform
terraform init -backend=false
terraform fmt -check
terraform validate
```
Expected: `terraform fmt -check` prints nothing (formatted); `terraform validate` prints `Success! The configuration is valid.` (`terraform init` downloads providers; no AWS credentials required for validate.)

- [ ] **Step 6: Commit**

```bash
git add terraform/main.tf terraform/variables.tf terraform/dynamodb.tf terraform/sns.tf
git commit -m "feat(infra): providers, variables, DynamoDB table+GSI, SNS topic"
```

---

## Task 8: Terraform — CloudWatch log groups and least-privilege IAM roles

**Files:**
- Create: `terraform/iam.tf`

**Interfaces:**
- Consumes: `aws_dynamodb_table.tickets.arn`, `aws_sns_topic.tickets.arn` (Task 7).
- Produces (referenced by Task 9): `aws_iam_role.create_ticket.arn`, `aws_iam_role.get_ticket.arn`, `aws_cloudwatch_log_group.create_ticket` (`.name`, `.arn`), `aws_cloudwatch_log_group.get_ticket` (`.name`, `.arn`).

- [ ] **Step 1: Create `terraform/iam.tf`**

```hcl
resource "aws_cloudwatch_log_group" "create_ticket" {
  name              = "/aws/lambda/${var.project_name}-createTicket"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "get_ticket" {
  name              = "/aws/lambda/${var.project_name}-getTicket"
  retention_in_days = 14
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# ---- createTicket role: write + publish only ----
resource "aws_iam_role" "create_ticket" {
  name               = "${var.project_name}-createTicket-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "create_ticket" {
  statement {
    sid       = "WriteTicket"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.tickets.arn]
  }

  statement {
    sid       = "PublishNotification"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.tickets.arn]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.create_ticket.arn}:*"]
  }
}

resource "aws_iam_role_policy" "create_ticket" {
  name   = "${var.project_name}-createTicket-policy"
  role   = aws_iam_role.create_ticket.id
  policy = data.aws_iam_policy_document.create_ticket.json
}

# ---- getTicket role: read only ----
resource "aws_iam_role" "get_ticket" {
  name               = "${var.project_name}-getTicket-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "get_ticket" {
  statement {
    sid     = "ReadTicket"
    actions = ["dynamodb:GetItem", "dynamodb:Query"]
    resources = [
      aws_dynamodb_table.tickets.arn,
      "${aws_dynamodb_table.tickets.arn}/index/status-createdAt-index",
    ]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.get_ticket.arn}:*"]
  }
}

resource "aws_iam_role_policy" "get_ticket" {
  name   = "${var.project_name}-getTicket-policy"
  role   = aws_iam_role.get_ticket.id
  policy = data.aws_iam_policy_document.get_ticket.json
}
```

- [ ] **Step 2: Validate**

Run:
```bash
cd terraform
terraform fmt -check
terraform validate
```
Expected: formatted; `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

```bash
git add terraform/iam.tf
git commit -m "feat(infra): log groups and least-privilege IAM roles per function"
```

---

## Task 9: Terraform — Lambda packaging and functions

**Files:**
- Create: `terraform/build.py`
- Create: `terraform/lambda.tf`

**Interfaces:**
- Consumes: `aws_iam_role.create_ticket.arn`, `aws_iam_role.get_ticket.arn`, `aws_cloudwatch_log_group.*` (Task 8); `aws_dynamodb_table.tickets.name`, `aws_sns_topic.tickets.arn` (Task 7).
- Produces (referenced by Task 11): `aws_lambda_function.create_ticket` (`.invoke_arn`, `.function_name`), `aws_lambda_function.get_ticket` (`.invoke_arn`, `.function_name`); var `powertools_layer_arn`.
- Build contract: `build.py` vendors `requirements.txt` deps (Linux/cp313 wheels) plus `src/{create_ticket|common}` and `src/{get_ticket|common}` into `terraform/build/<func>/`, which `archive_file` zips. Lambda handler paths: `create_ticket.handler.handler`, `get_ticket.handler.handler`.

- [ ] **Step 1: Create `terraform/build.py`**

```python
"""Cross-platform Lambda packager: vendor runtime deps + copy source per function."""

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "..", "src")
BUILD = os.path.join(ROOT, "build")
REQUIREMENTS = os.path.join(ROOT, "..", "requirements.txt")

# function package dir -> source packages to include
FUNCS = {
    "create_ticket": ["create_ticket", "common"],
    "get_ticket": ["get_ticket", "common"],
}


def build():
    if os.path.exists(BUILD):
        shutil.rmtree(BUILD)
    for func, packages in FUNCS.items():
        target = os.path.join(BUILD, func)
        os.makedirs(target)
        for pkg in packages:
            shutil.copytree(os.path.join(SRC, pkg), os.path.join(target, pkg))
        subprocess.check_call([
            sys.executable, "-m", "pip", "install",
            "--platform", "manylinux2014_x86_64",
            "--implementation", "cp",
            "--python-version", "3.13",
            "--only-binary=:all:",
            "--target", target,
            "-r", REQUIREMENTS,
        ])


if __name__ == "__main__":
    build()
```

- [ ] **Step 2: Create `terraform/lambda.tf`**

```hcl
locals {
  src_dir   = "${path.module}/../src"
  build_dir = "${path.module}/build"
}

variable "powertools_layer_arn" {
  type        = string
  description = "ARN of the AWS-managed Lambda Powertools (Python) layer for the deploy region/arch."
  default     = "arn:aws:lambda:us-east-1:017000801446:layer:AWSLambdaPowertoolsPythonV3-python313-x86_64:3"
}

resource "null_resource" "build" {
  triggers = {
    requirements = filemd5("${path.module}/../requirements.txt")
    sources      = sha1(join("", [for f in fileset(local.src_dir, "**/*.py") : filemd5("${local.src_dir}/${f}")]))
    builder      = filemd5("${path.module}/build.py")
  }

  provisioner "local-exec" {
    command = "${path.module}/../.venv/Scripts/python.exe ${path.module}/build.py"
  }
}

data "archive_file" "create_ticket" {
  type        = "zip"
  source_dir  = "${local.build_dir}/create_ticket"
  output_path = "${path.module}/dist/create_ticket.zip"
  depends_on  = [null_resource.build]
}

data "archive_file" "get_ticket" {
  type        = "zip"
  source_dir  = "${local.build_dir}/get_ticket"
  output_path = "${path.module}/dist/get_ticket.zip"
  depends_on  = [null_resource.build]
}

resource "aws_lambda_function" "create_ticket" {
  function_name    = "${var.project_name}-createTicket"
  role             = aws_iam_role.create_ticket.arn
  runtime          = "python3.13"
  handler          = "create_ticket.handler.handler"
  filename         = data.archive_file.create_ticket.output_path
  source_code_hash = data.archive_file.create_ticket.output_base64sha256
  timeout          = 10
  memory_size      = 256
  layers           = [var.powertools_layer_arn]

  environment {
    variables = {
      TABLE_NAME              = aws_dynamodb_table.tickets.name
      SNS_TOPIC_ARN           = aws_sns_topic.tickets.arn
      POWERTOOLS_SERVICE_NAME = "createTicket"
      LOG_LEVEL               = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.create_ticket]
}

resource "aws_lambda_function" "get_ticket" {
  function_name    = "${var.project_name}-getTicket"
  role             = aws_iam_role.get_ticket.arn
  runtime          = "python3.13"
  handler          = "get_ticket.handler.handler"
  filename         = data.archive_file.get_ticket.output_path
  source_code_hash = data.archive_file.get_ticket.output_base64sha256
  timeout          = 10
  memory_size      = 256
  layers           = [var.powertools_layer_arn]

  environment {
    variables = {
      TABLE_NAME              = aws_dynamodb_table.tickets.name
      POWERTOOLS_SERVICE_NAME = "getTicket"
      LOG_LEVEL               = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.get_ticket]
}
```

> **Note for the implementer:** the `local-exec` command above assumes a project virtualenv at `.venv` (created in Task 13's README flow: `python -m venv .venv`). On non-Windows hosts change `.venv/Scripts/python.exe` to `.venv/bin/python`. `terraform validate` does **not** run `build.py`; the packaging only executes on `terraform apply`. If `.venv` is absent at apply time, substitute the interpreter that has the dev deps installed.

- [ ] **Step 3: Validate**

Run:
```bash
cd terraform
terraform fmt -check
terraform validate
```
Expected: formatted; `Success! The configuration is valid.`

- [ ] **Step 4: Verify the packager produces importable zips (no AWS needed)**

Run from the project root:
```bash
python terraform/build.py
python -c "import zipfile; z=zipfile.ZipFile('terraform/dist/create_ticket.zip') if __import__('os').path.exists('terraform/dist/create_ticket.zip') else None"
ls terraform/build/create_ticket
ls terraform/build/get_ticket
```
Expected: both `terraform/build/<func>/` dirs contain `common/`, the handler package, and the vendored `pydantic`/`ulid` directories. (The zips are produced by `terraform apply`; this step confirms `build.py` itself works.)

- [ ] **Step 5: Commit**

```bash
git add terraform/build.py terraform/lambda.tf
git commit -m "feat(infra): Lambda packaging (vendored deps + Powertools layer) and functions"
```

---

## Task 10: Terraform — Cognito User Pool and client

**Files:**
- Create: `terraform/cognito.tf`

**Interfaces:**
- Consumes: `data.aws_caller_identity.current.account_id` (Task 7).
- Produces (referenced by Task 11): `aws_cognito_user_pool.main` (`.id`), `aws_cognito_user_pool_client.api` (`.id`).

- [ ] **Step 1: Create `terraform/cognito.tf`**

```hcl
resource "aws_cognito_user_pool" "main" {
  name = "${var.project_name}-users"

  password_policy {
    minimum_length    = 8
    require_lowercase = true
    require_numbers   = true
    require_uppercase = true
    require_symbols   = false
  }
}

resource "aws_cognito_user_pool_client" "api" {
  name            = "${var.project_name}-api-client"
  user_pool_id    = aws_cognito_user_pool.main.id
  generate_secret = false

  explicit_auth_flows = [
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]
}

resource "aws_cognito_user_pool_domain" "main" {
  domain       = "${var.project_name}-${data.aws_caller_identity.current.account_id}"
  user_pool_id = aws_cognito_user_pool.main.id
}
```

- [ ] **Step 2: Validate**

Run:
```bash
cd terraform
terraform fmt -check
terraform validate
```
Expected: formatted; `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

```bash
git add terraform/cognito.tf
git commit -m "feat(infra): Cognito user pool, app client, and domain"
```

---

## Task 11: Terraform — API Gateway HTTP API, routes, authorizer, outputs

**Files:**
- Create: `terraform/apigw.tf`
- Create: `terraform/outputs.tf`

**Interfaces:**
- Consumes: `aws_cognito_user_pool.main.id`, `aws_cognito_user_pool_client.api.id` (Task 10); `aws_lambda_function.create_ticket`, `aws_lambda_function.get_ticket` (Task 9); `data.aws_region.current.name` (Task 7).
- Produces: deployed HTTP API with routes `POST /tickets`, `GET /tickets/{id}`, `GET /tickets` (all JWT-protected); outputs `api_base_url`, `user_pool_id`, `user_pool_client_id`, `sns_topic_arn`, `dynamodb_table`.

- [ ] **Step 1: Create `terraform/apigw.tf`**

```hcl
resource "aws_apigatewayv2_api" "http" {
  name          = "${var.project_name}-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.http.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "cognito-jwt"

  jwt_configuration {
    audience = [aws_cognito_user_pool_client.api.id]
    issuer   = "https://cognito-idp.${data.aws_region.current.name}.amazonaws.com/${aws_cognito_user_pool.main.id}"
  }
}

resource "aws_apigatewayv2_integration" "create_ticket" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.create_ticket.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_integration" "get_ticket" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.get_ticket.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "create_ticket" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "POST /tickets"
  target             = "integrations/${aws_apigatewayv2_integration.create_ticket.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_apigatewayv2_route" "get_ticket_by_id" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "GET /tickets/{id}"
  target             = "integrations/${aws_apigatewayv2_integration.get_ticket.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_apigatewayv2_route" "list_tickets" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "GET /tickets"
  target             = "integrations/${aws_apigatewayv2_integration.get_ticket.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "create_ticket" {
  statement_id  = "AllowAPIGWInvokeCreate"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.create_ticket.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}

resource "aws_lambda_permission" "get_ticket" {
  statement_id  = "AllowAPIGWInvokeGet"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.get_ticket.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}
```

- [ ] **Step 2: Create `terraform/outputs.tf`**

```hcl
output "api_base_url" {
  description = "Base invoke URL for the HTTP API ($default stage)."
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "user_pool_id" {
  value = aws_cognito_user_pool.main.id
}

output "user_pool_client_id" {
  value = aws_cognito_user_pool_client.api.id
}

output "sns_topic_arn" {
  value = aws_sns_topic.tickets.arn
}

output "dynamodb_table" {
  value = aws_dynamodb_table.tickets.name
}
```

- [ ] **Step 3: Validate the full configuration**

Run:
```bash
cd terraform
terraform fmt -check
terraform validate
```
Expected: formatted; `Success! The configuration is valid.`

- [ ] **Step 4: Commit**

```bash
git add terraform/apigw.tf terraform/outputs.tf
git commit -m "feat(infra): HTTP API, JWT authorizer, routes, lambda permissions, outputs"
```

---

## Task 12: README — deploy, JWT demo, teardown

**Files:**
- Create: `README.md`

**Interfaces:**
- Consumes: Terraform outputs (Task 11) and the build flow (Task 9). No code interface.

- [ ] **Step 1: Create `README.md`**

````markdown
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
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with deploy, JWT demo, and teardown"
```

---

## Notes carried from research (do not re-litigate)

- **SNS, not SES:** SNS is a *support-team* notification (subscribers of the topic), not a personalized per-reporter email. Per-reporter transactional email = Amazon SES, future phase. Kept as-is.
- **Out of scope (Phase 1):** ITSM platform, web portal, per-department metrics, corporate integrations. The `requestingArea` GSI is deliberately not built (YAGNI).
- **No VPC:** managed serverless services don't need VPC placement here.

---

## Self-Review (completed against `docs/research.md`)

**Spec coverage:**
- §3/§4 two Lambdas + per-function roles → Tasks 5, 6, 8, 9. ✓
- §5 DynamoDB table + GSI (ULID id, status/createdAt) → Tasks 1 (moto mirror), 4, 7. ✓
- §6 API contracts (POST/GET-by-id/GET-list with pagination) → Tasks 5, 6, 11. ✓
- §7 Pydantic validation, `{error,message}` envelope, Powertools structured logs → Tasks 2, 3, 5, 6. ✓
- §2/§3 Cognito JWT authorizer on HTTP API → Tasks 10, 11. ✓
- §2 SNS topic + email subscription → Task 7. ✓
- "two upgrades": scoped log perms (Task 8 — `logs:CreateLogStream`+`logs:PutLogEvents` only) and explicit HTTP API v2 (Task 11). ✓
- §9 pytest+moto, `terraform fmt`/`validate`, README (deploy/JWT/teardown) → Tasks 1–6, every Terraform task, Task 12. ✓
- §8 project layout → matches the File Structure section. ✓

**Placeholder scan:** no TBD/TODO/"handle edge cases"/"similar to Task N" — every code and command step is concrete.

**Type consistency:** `TicketRepository(table=None)`, `put`/`get`/`query_by_status`, `response`/`error`/`encode_cursor`/`decode_cursor`, `Priority`/`Status`, and the module-global `repo` name are used identically across Tasks 4–6. Terraform resource addresses referenced in later tasks (`aws_dynamodb_table.tickets`, `aws_sns_topic.tickets`, `aws_iam_role.*`, `aws_lambda_function.*`, `aws_cognito_*`) match their definitions. GSI name `status-createdAt-index` is identical in conftest, repository, IAM policy, and the table definition.

---

## Execution Handoff

Plan complete and saved to `docs/planTicketing.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration (`superpowers:subagent-driven-development`).
2. **Inline Execution** — execute tasks in this session with batch checkpoints (`superpowers:executing-plans`).

Which approach?
