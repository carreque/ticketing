# Unit tests for the DynamoDB table + GSI (Task 7).
# mock_provider => runs offline at plan time, no AWS credentials or cost.
# mock_data supplies a valid IAM policy json so the iam.tf roles (now part of the
# root module) plan without failing assume_role_policy JSON validation.
mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

variables {
  support_email = "test@example.com"
}

run "table_name_billing_and_key" {
  command = plan

  assert {
    condition     = aws_dynamodb_table.tickets.name == "ticketing-tickets"
    error_message = "Table name must be <project_name>-tickets"
  }
  assert {
    condition     = aws_dynamodb_table.tickets.billing_mode == "PAY_PER_REQUEST"
    error_message = "Table must use on-demand (PAY_PER_REQUEST) billing"
  }
  assert {
    condition     = aws_dynamodb_table.tickets.hash_key == "id"
    error_message = "Partition key must be id"
  }
}

run "gsi_matches_status_createdat_index" {
  command = plan

  assert {
    condition     = one(aws_dynamodb_table.tickets.global_secondary_index).name == "status-createdAt-index"
    error_message = "GSI name must be status-createdAt-index (kept in sync with repository/IAM/conftest)"
  }
  assert {
    condition     = one(aws_dynamodb_table.tickets.global_secondary_index).hash_key == "status"
    error_message = "GSI partition key must be status"
  }
  assert {
    condition     = one(aws_dynamodb_table.tickets.global_secondary_index).range_key == "createdAt"
    error_message = "GSI sort key must be createdAt"
  }
  assert {
    condition     = one(aws_dynamodb_table.tickets.global_secondary_index).projection_type == "ALL"
    error_message = "GSI projection type must be ALL"
  }
}
