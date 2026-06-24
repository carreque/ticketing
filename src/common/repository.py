import boto3
import os
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
    
    def query_by_status(self, status: str, limit: int = 20, cursor: dict | None = None) -> tuple[list[dict], dict|None]:
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