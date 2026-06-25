resource "aws_sns_topic" "tickets" {
  name = "${var.project_name}-notifications"
}

resource "aws_sns_topic_subscription" "support_email" {
  topic_arn = aws_sns_topic.tickets.arn
  protocol  = "email"
  endpoint  = var.support_email
}