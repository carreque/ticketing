# Unit tests for the API Gateway HTTP API, JWT authorizer, routes, and lambda
# permissions (Task 11). mock_provider => runs offline at plan time, no AWS
# credentials, no build, no cost.
#
# Assertions target STATICALLY-CONFIGURED attributes only: API name + protocol,
# authorizer type + identity sources, the three route_keys each protected with
# JWT, and the two aws_lambda_permission principals/actions. Computed values
# (integration IDs, execution_arn, invoke URLs, jwt_configuration.issuer which
# interpolates the region + pool id) are non-deterministic under the mock and are
# NOT asserted on by value.
#
# Two providers must be mocked beyond aws's resources:
#  - archive: data.archive_file (from lambda.tf, part of the root module) is read
#    at plan time and would otherwise zip the on-disk build/ dirs that only exist
#    after `terraform apply` runs build.py.
#  - aws iam policy document: iam.tf's aws_iam_role validates assume_role_policy as
#    JSON; supply a valid default (we never assert on json).
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

run "api_name_and_protocol" {
  command = plan

  assert {
    condition     = aws_apigatewayv2_api.http.name == "ticketing-api"
    error_message = "HTTP API name must be <project_name>-api"
  }
  assert {
    condition     = aws_apigatewayv2_api.http.protocol_type == "HTTP"
    error_message = "API protocol_type must be HTTP"
  }
}

run "jwt_authorizer" {
  command = plan

  assert {
    condition     = aws_apigatewayv2_authorizer.cognito.authorizer_type == "JWT"
    error_message = "Authorizer type must be JWT"
  }
  assert {
    condition     = aws_apigatewayv2_authorizer.cognito.identity_sources == toset(["$request.header.Authorization"])
    error_message = "Authorizer identity source must be the Authorization header"
  }
}

run "routes_are_jwt_protected" {
  command = plan

  assert {
    condition     = aws_apigatewayv2_route.create_ticket.route_key == "POST /tickets"
    error_message = "create_ticket route_key must be 'POST /tickets'"
  }
  assert {
    condition     = aws_apigatewayv2_route.create_ticket.authorization_type == "JWT"
    error_message = "POST /tickets must be JWT-protected"
  }
  assert {
    condition     = aws_apigatewayv2_route.get_ticket_by_id.route_key == "GET /tickets/{id}"
    error_message = "get_ticket_by_id route_key must be 'GET /tickets/{id}'"
  }
  assert {
    condition     = aws_apigatewayv2_route.get_ticket_by_id.authorization_type == "JWT"
    error_message = "GET /tickets/{id} must be JWT-protected"
  }
  assert {
    condition     = aws_apigatewayv2_route.list_tickets.route_key == "GET /tickets"
    error_message = "list_tickets route_key must be 'GET /tickets'"
  }
  assert {
    condition     = aws_apigatewayv2_route.list_tickets.authorization_type == "JWT"
    error_message = "GET /tickets must be JWT-protected"
  }
}

run "lambda_permissions_allow_apigateway" {
  command = plan

  assert {
    condition     = aws_lambda_permission.create_ticket.principal == "apigateway.amazonaws.com"
    error_message = "createTicket invoke permission principal must be apigateway.amazonaws.com"
  }
  assert {
    condition     = aws_lambda_permission.create_ticket.action == "lambda:InvokeFunction"
    error_message = "createTicket permission action must be lambda:InvokeFunction"
  }
  assert {
    condition     = aws_lambda_permission.get_ticket.principal == "apigateway.amazonaws.com"
    error_message = "getTicket invoke permission principal must be apigateway.amazonaws.com"
  }
  assert {
    condition     = aws_lambda_permission.get_ticket.action == "lambda:InvokeFunction"
    error_message = "getTicket permission action must be lambda:InvokeFunction"
  }
}
