# Unit tests for CloudWatch log groups + least-privilege IAM roles (Task 8).
# mock_provider => runs offline at plan time, no AWS credentials or cost.
#
# Assertions target STATICALLY-CONFIGURED attributes only: policy-document
# statement actions/sids and statement counts (these lock in least privilege),
# role names, and log-group names/retention. Computed values (rendered policy
# .json, resource ARNs) are non-deterministic under the mock and are not asserted.
#
# The mock's auto-generated value for the computed `json` attribute is not valid
# JSON, which fails aws_iam_role's assume_role_policy validation. Supply a valid
# default so plan succeeds; we never assert on json (only on configured inputs).
mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

variables {
  support_email = "support@example.com"
}

run "log_groups_named_and_retained" {
  command = plan

  assert {
    condition     = aws_cloudwatch_log_group.create_ticket.name == "/aws/lambda/ticketing-createTicket"
    error_message = "createTicket log group must be /aws/lambda/<project>-createTicket"
  }
  assert {
    condition     = aws_cloudwatch_log_group.get_ticket.name == "/aws/lambda/ticketing-getTicket"
    error_message = "getTicket log group must be /aws/lambda/<project>-getTicket"
  }
  assert {
    condition     = aws_cloudwatch_log_group.create_ticket.retention_in_days == 14
    error_message = "createTicket log group retention must be 14 days"
  }
  assert {
    condition     = aws_cloudwatch_log_group.get_ticket.retention_in_days == 14
    error_message = "getTicket log group retention must be 14 days"
  }
}

run "roles_named_per_function" {
  command = plan

  assert {
    condition     = aws_iam_role.create_ticket.name == "ticketing-createTicket-role"
    error_message = "createTicket role name must be <project>-createTicket-role"
  }
  assert {
    condition     = aws_iam_role.get_ticket.name == "ticketing-getTicket-role"
    error_message = "getTicket role name must be <project>-getTicket-role"
  }
}

run "lambda_assume_role_is_lambda_service" {
  command = plan

  assert {
    condition     = data.aws_iam_policy_document.lambda_assume.statement[0].actions == toset(["sts:AssumeRole"])
    error_message = "Assume-role policy must allow exactly sts:AssumeRole"
  }
}

run "create_ticket_least_privilege" {
  command = plan

  # Exactly three statements: write ticket, publish, scoped logs — nothing more.
  assert {
    condition     = length(data.aws_iam_policy_document.create_ticket.statement) == 3
    error_message = "createTicket policy must have exactly 3 statements (write, publish, logs)"
  }
  assert {
    condition     = data.aws_iam_policy_document.create_ticket.statement[0].actions == toset(["dynamodb:PutItem"])
    error_message = "createTicket DynamoDB access must be exactly dynamodb:PutItem (write-only)"
  }
  assert {
    condition     = data.aws_iam_policy_document.create_ticket.statement[1].actions == toset(["sns:Publish"])
    error_message = "createTicket SNS access must be exactly sns:Publish"
  }
  assert {
    condition     = data.aws_iam_policy_document.create_ticket.statement[2].actions == toset(["logs:CreateLogStream", "logs:PutLogEvents"])
    error_message = "createTicket logs must be scoped to CreateLogStream+PutLogEvents (never logs:*)"
  }
}

run "get_ticket_least_privilege" {
  command = plan

  # Exactly two statements: read ticket(s), scoped logs — no write, no publish.
  assert {
    condition     = length(data.aws_iam_policy_document.get_ticket.statement) == 2
    error_message = "getTicket policy must have exactly 2 statements (read, logs)"
  }
  assert {
    condition     = data.aws_iam_policy_document.get_ticket.statement[0].actions == toset(["dynamodb:GetItem", "dynamodb:Query"])
    error_message = "getTicket DynamoDB access must be exactly GetItem+Query (read-only)"
  }
  assert {
    condition     = data.aws_iam_policy_document.get_ticket.statement[1].actions == toset(["logs:CreateLogStream", "logs:PutLogEvents"])
    error_message = "getTicket logs must be scoped to CreateLogStream+PutLogEvents (never logs:*)"
  }
}
