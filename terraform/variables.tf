variable "project_name" {
  type        = string
  description = "Prefix applied to all resource names."
  default     = "ticketing"
}

variable "aws_region" {
  type        = string
  description = "AWS region to deploy into."
  default     = "us-east-1"
}

variable "support_email" {
  type        = string
  description = "Email address subscribed to the SNS topic for new-ticket notifications."
}

variable "python_bin" {
  type        = string
  description = "Path to the Python interpreter used to run build.py (relative to the terraform module dir, or absolute). macOS/Linux venv: ../.venv/bin/python | Windows venv: ../.venv/Scripts/python.exe"
  default     = "../.venv/bin/python"
}

variable "powertools_layer_arn" {
  type        = string
  description = "ARN of the AWS-managed Lambda Powertools (Python) layer for the deploy region/arch."
  default     = "arn:aws:lambda:us-east-1:017000801446:layer:AWSLambdaPowertoolsPythonV3-python313-x86_64:34"
}