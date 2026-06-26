locals {
  src_dir   = "${path.module}/../src"
  build_dir = "${path.module}/build"
}

data "archive_file" "create_ticket" {
  type        = "zip"
  source_dir  = "${local.build_dir}/create_ticket"
  output_path = "${path.module}/dist/create_ticket.zip"
  depends_on  = [null_resource.build]
}

data "archive_file" "get_ticket" {
  type        = "zip"
  source_dir  = "${local.build_dir}/get_ticket"
  output_path = "${path.module}/dist/get_ticket.zip"
  depends_on  = [null_resource.build]
}

resource "null_resource" "build" {
  triggers = {
    requirements = filemd5("${path.module}/../requirements.txt")
    sources      = sha1(join("", [for f in fileset(local.src_dir, "**/*.py") : filemd5("${local.src_dir}/${f}")]))
    builder      = filemd5("${path.module}/build.py")
  }

  provisioner "local-exec" {
    command = "${path.module}/../.venv/Scripts/python.exe ${path.module}/build.py"
  }
}

resource "aws_lambda_function" "create_ticket" {
  function_name    = "${var.project_name}-createTicket"
  role             = aws_iam_role.create_ticket.arn
  runtime          = "python3.13"
  handler          = "create_ticket.handler.handler"
  filename         = data.archive_file.create_ticket.output_path
  source_code_hash = data.archive_file.create_ticket.output_base64sha256
  timeout          = 10
  memory_size      = 256
  layers           = [var.powertools_layer_arn]

  environment {
    variables = {
      TABLE_NAME              = aws_dynamodb_table.tickets.name
      SNS_TOPIC_ARN           = aws_sns_topic.tickets.arn
      POWERTOOLS_SERVICE_NAME = "createTicket"
      LOG_LEVEL               = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.create_ticket]
}

resource "aws_lambda_function" "get_ticket" {
  function_name    = "${var.project_name}-getTicket"
  role             = aws_iam_role.get_ticket.arn
  runtime          = "python3.13"
  handler          = "get_ticket.handler.handler"
  filename         = data.archive_file.get_ticket.output_path
  source_code_hash = data.archive_file.get_ticket.output_base64sha256
  timeout          = 10
  memory_size      = 256
  layers           = [var.powertools_layer_arn]

  environment {
    variables = {
      TABLE_NAME              = aws_dynamodb_table.tickets.name
      POWERTOOLS_SERVICE_NAME = "getTicket"
      LOG_LEVEL               = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.get_ticket]
}