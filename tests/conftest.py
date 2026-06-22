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
