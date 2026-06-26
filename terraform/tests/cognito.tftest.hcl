# Unit tests for the Cognito user pool, app client, and domain (Task 10).
# mock_provider => runs offline at plan time, no AWS credentials, no cost.
#
# Assertions target STATICALLY-CONFIGURED attributes only: pool/client names,
# generate_secret, the explicit auth flows, the password policy minimum length,
# and the *static prefix* of the domain. The domain interpolates
# data.aws_caller_identity.current.account_id (computed, non-deterministic under
# the mock), so we assert only its "ticketing-" prefix via startswith, never the
# full value.
#
# mock_data supplies a valid IAM policy json so iam.tf's roles (part of the root
# module) plan without failing assume_role_policy JSON validation.
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

run "user_pool_name_and_password_policy" {
  command = plan

  assert {
    condition     = aws_cognito_user_pool.main.name == "ticketing-users"
    error_message = "User pool name must be <project_name>-users"
  }
  assert {
    condition     = one(aws_cognito_user_pool.main.password_policy).minimum_length == 8
    error_message = "Password policy minimum length must be 8"
  }
}

run "app_client_name_and_no_secret" {
  command = plan

  assert {
    condition     = aws_cognito_user_pool_client.api.name == "ticketing-api-client"
    error_message = "App client name must be <project_name>-api-client"
  }
  assert {
    condition     = aws_cognito_user_pool_client.api.generate_secret == false
    error_message = "App client must be public (generate_secret = false) for the JWT/SPA flow"
  }
}

run "app_client_explicit_auth_flows" {
  command = plan

  assert {
    condition     = contains(aws_cognito_user_pool_client.api.explicit_auth_flows, "ALLOW_USER_PASSWORD_AUTH")
    error_message = "App client must allow ALLOW_USER_PASSWORD_AUTH"
  }
  assert {
    condition     = contains(aws_cognito_user_pool_client.api.explicit_auth_flows, "ALLOW_REFRESH_TOKEN_AUTH")
    error_message = "App client must allow ALLOW_REFRESH_TOKEN_AUTH"
  }
}

run "user_pool_domain_prefix" {
  command = plan

  assert {
    condition     = startswith(aws_cognito_user_pool_domain.main.domain, "ticketing-")
    error_message = "User pool domain must be prefixed with <project_name>- (account id appended)"
  }
}
