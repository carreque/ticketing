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
