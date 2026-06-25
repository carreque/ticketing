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