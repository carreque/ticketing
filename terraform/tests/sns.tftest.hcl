# Unit tests for the SNS topic + email subscription (Task 7).
mock_provider "aws" {}

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
