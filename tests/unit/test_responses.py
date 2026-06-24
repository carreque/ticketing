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
