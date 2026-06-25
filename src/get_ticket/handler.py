from aws_lambda_powertools import Logger

from common.models import Status, Ticket
from common.repository import TicketRepository
from common.responses import decode_cursor, encode_cursor, error, response
from exceptions.apiError import ApiError

logger = Logger(service="getTicket")
repo = TicketRepository()

def getTicket(ticket_id : str) -> Ticket:
    if ticket_id:
        item = repo.get(ticket_id)
        if item is None:
            raise ApiError(404,"not_found", "Ticket not found" )
        return response(200, item)

def getStatus(queryStringParameters : any) -> Status:
    status = queryStringParameters.get("status")
    
    if not status:
        raise ApiError(400, "validation_error", "Query parameter 'status' is required")
    try:
        return Status(status)
    except ValueError:
        raise ApiError(400, "validation_error", f"Invalid status value: {status}")

def getLimit(queryStringParameters : any) -> int:
    try:
        return int(queryStringParameters.get("limit", 20))
    except (TypeError, ValueError):
        raise ApiError(400, "validation_error", "Query parameter 'limit' must be an integer")
    
@logger.inject_lambda_context
def handler(event, context):
    path_params = event.get("pathParameters") or {}
    ticket_id = path_params.get("id")
    qs = event.get("queryStringParameters") or {}

    try:
        if ticket_id:
            return getTicket(ticket_id)
        
        status = getStatus(qs)
        limit = getLimit(qs)
        cursor = decode_cursor(qs.get("cursor"))
        items, last_key = repo.query_by_status(status, limit=limit, cursor=cursor)
        return response(200, {"items": items, "nextCursor": encode_cursor(last_key)})
    except ApiError as err:
        return error(err.status_code, err.code, err.message)
