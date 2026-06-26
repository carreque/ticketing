# Unit tests for the SNS topic + email subscription (Task 7).
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
  support_email = "support@example.com"
}

run "topic_name" {
  command = plan

  assert {
    condition     = aws_sns_topic.tickets.name == "ticketing-notifications"
    error_message = "SNS topic name must be <project_name>-notifications"
  }
}

run "email_subscription_targets_support_email" {
  command = plan

  assert {
    condition     = aws_sns_topic_subscription.support_email.protocol == "email"
    error_message = "Support subscription must use the email protocol"
  }
  assert {
    condition     = aws_sns_topic_subscription.support_email.endpoint == "support@example.com"
    error_message = "Support subscription endpoint must equal var.support_email"
  }
}
