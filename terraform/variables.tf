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

variable "powertools_layer_arn" {
  type        = string
  description = "ARN of the AWS-managed Lambda Powertools (Python) layer for the deploy region/arch."
  default     = "arn:aws:lambda:us-east-1:017000801446:layer:AWSLambdaPowertoolsPythonV3-python313-x86_64:34"
}