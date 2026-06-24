
import json
import base64

def response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body)
    }

def error(status_code: int, code: str, message: str) -> dict:
    return response(status_code, {
        "error": code,
        "message": message
        })

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