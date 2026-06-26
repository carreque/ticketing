
data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "create_ticket" {
  statement {
    sid       = "WriteTicket"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.tickets.arn]
  }

  statement {
    sid       = "PublishNotification"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.tickets.arn]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.create_ticket.arn}:*"]
  }
}

data "aws_iam_policy_document" "get_ticket" {
  statement {
    sid       = "ReadTicket"
    actions   = ["dynamodb:GetItem", "dynamodb:Query"]
    resources = [aws_dynamodb_table.tickets.arn, "${aws_dynamodb_table.tickets.arn}/index/status-createdAt-index"]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.get_ticket.arn}:*"]
  }
}

resource "aws_iam_role" "create_ticket" {
  name               = "${var.project_name}-createTicket-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "create_ticket" {
  name   = "${var.project_name}-createTicket-policy"
  role   = aws_iam_role.create_ticket.id
  policy = data.aws_iam_policy_document.create_ticket.json
}

resource "aws_iam_role" "get_ticket" {
  name               = "${var.project_name}-getTicket-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "get_ticket" {
  name   = "${var.project_name}-getTicket-policy"
  role   = aws_iam_role.get_ticket.id
  policy = data.aws_iam_policy_document.get_ticket.json
}