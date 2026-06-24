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
