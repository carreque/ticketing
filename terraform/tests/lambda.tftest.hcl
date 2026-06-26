# Unit tests for the two Lambda functions (Task 9).
# mock_provider => runs offline at plan time, no AWS credentials, no build, no cost.
#
# Assertions target STATICALLY-CONFIGURED attributes only: function names,
# runtime, handler paths, the attached Powertools layer, and the env vars whose
# values are known at plan (TABLE_NAME = "<project>-tickets", POWERTOOLS_SERVICE_NAME).
# Computed values (archive output hashes/paths, the SNS topic ARN, role ARNs) are
# non-deterministic under the mock and are NOT asserted on by value.
#
# Two providers must be mocked beyond aws:
#  - archive: data.archive_file is read at plan time and would otherwise zip the
#    on-disk build/ dirs (which only exist after `terraform apply` runs build.py).
#  - aws iam policy document: the full module includes iam.tf, whose aws_iam_role
#    validates assume_role_policy as JSON; the mock's auto value isn't valid JSON,
#    so supply a valid default (we never assert on json).
mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

mock_provider "archive" {}

variables {
  support_email = "support@example.com"
}

run "function_names_runtime_and_handlers" {
  command = plan

  assert {
    condition     = aws_lambda_function.create_ticket.function_name == "ticketing-createTicket"
    error_message = "createTicket function name must be <project>-createTicket"
  }
  assert {
    condition     = aws_lambda_function.get_ticket.function_name == "ticketing-getTicket"
    error_message = "getTicket function name must be <project>-getTicket"
  }
  assert {
    condition     = aws_lambda_function.create_ticket.runtime == "python3.13"
    error_message = "createTicket runtime must be python3.13"
  }
  assert {
    condition     = aws_lambda_function.get_ticket.runtime == "python3.13"
    error_message = "getTicket runtime must be python3.13"
  }
  assert {
    condition     = aws_lambda_function.create_ticket.handler == "create_ticket.handler.handler"
    error_message = "createTicket handler must be create_ticket.handler.handler"
  }
  assert {
    condition     = aws_lambda_function.get_ticket.handler == "get_ticket.handler.handler"
    error_message = "getTicket handler must be get_ticket.handler.handler"
  }
}

run "powertools_layer_attached" {
  command = plan

  assert {
    condition     = contains(aws_lambda_function.create_ticket.layers, var.powertools_layer_arn)
    error_message = "createTicket must attach the Powertools layer (var.powertools_layer_arn)"
  }
  assert {
    condition     = contains(aws_lambda_function.get_ticket.layers, var.powertools_layer_arn)
    error_message = "getTicket must attach the Powertools layer (var.powertools_layer_arn)"
  }
}

run "create_ticket_environment" {
  command = plan

  # createTicket writes the table and publishes notifications: needs both TABLE_NAME and SNS_TOPIC_ARN.
  assert {
    condition     = aws_lambda_function.create_ticket.environment[0].variables["TABLE_NAME"] == "ticketing-tickets"
    error_message = "createTicket TABLE_NAME must be the tickets table name"
  }
  assert {
    condition     = aws_lambda_function.create_ticket.environment[0].variables["POWERTOOLS_SERVICE_NAME"] == "createTicket"
    error_message = "createTicket POWERTOOLS_SERVICE_NAME must be createTicket"
  }
  assert {
    condition     = contains(keys(aws_lambda_function.create_ticket.environment[0].variables), "SNS_TOPIC_ARN")
    error_message = "createTicket must receive SNS_TOPIC_ARN to publish notifications"
  }
}

run "get_ticket_environment" {
  command = plan

  # getTicket only reads: it gets TABLE_NAME but must NOT receive SNS_TOPIC_ARN (it never publishes).
  assert {
    condition     = aws_lambda_function.get_ticket.environment[0].variables["TABLE_NAME"] == "ticketing-tickets"
    error_message = "getTicket TABLE_NAME must be the tickets table name"
  }
  assert {
    condition     = aws_lambda_function.get_ticket.environment[0].variables["POWERTOOLS_SERVICE_NAME"] == "getTicket"
    error_message = "getTicket POWERTOOLS_SERVICE_NAME must be getTicket"
  }
  assert {
    condition     = !contains(keys(aws_lambda_function.get_ticket.environment[0].variables), "SNS_TOPIC_ARN")
    error_message = "getTicket must not receive SNS_TOPIC_ARN (read-only, never publishes)"
  }
}
