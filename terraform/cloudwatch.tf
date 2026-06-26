resource "aws_cloudwatch_log_group" "create_ticket" {
  name              = "/aws/lambda/${var.project_name}-createTicket"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "get_ticket" {
  name              = "/aws/lambda/${var.project_name}-getTicket"
  retention_in_days = 14
}