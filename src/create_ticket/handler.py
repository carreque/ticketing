import json
import os
from datetime import datetime, timezone

import boto3
from aws_lambda_powertools import Logger
from pydantic import ValidationError
from ulid import ULID

from common.models import Status, Ticket
from common.responses import error,response
from common.repository import TicketRepository
from exceptions.apiError import ApiError

logger = Logger(service="createTicket")
repo = TicketRepository()
sns = boto3.client("sns")

def validateBody(raw : str) -> any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("request body is not valid JSON")
        raise ApiError(400, "invalid_json", "Request body is not valid JSON")

def validateModel(body: any) -> Ticket:
    try:
        return Ticket.model_validate(body)
    except ValidationError as exc:
        fields = ", ".join(".".join(str(p) for p in e["loc"]) for e in exc.errors())
        logger.warning("validation failed", extra={"fields": fields})
        raise ApiError(400, "validation_error", f"Invalid or missing fields: {fields}")

def createTicket(ticket : Ticket) -> Ticket:
    ticket = {
        "id": str(ULID()),
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "status": Status.OPEN.value,
        "priority": ticket.priority.value,
        "description": ticket.description,
        "requestingArea": ticket.requestingArea,
        "reportedBy": ticket.reportedBy,
    }
    repo.put(ticket)
    return ticket

def sendSnsTopic(ticket : Ticket):
    topic_arn = os.environ.get("SNS_TOPIC_ARN")
    if topic_arn:
        sns.publish(
            TopicArn=topic_arn,
            Subject="New support ticket",
            Message=json.dumps(ticket),
        )

@logger.inject_lambda_context(correlation_id_path="requestContext.requestId")
def handler(event, context):

    try:
        raw = event.get("body") or "{}"
        body = validateBody(raw)
        data = validateModel(body)
        ticket = createTicket(data) 
        sendSnsTopic(ticket)
        logger.info("ticket created", extra={"ticket_id": ticket["id"]})
        return response(201, ticket)
    except ApiError as err:
        return error(err.status_code, err.code, err.message)