output "api_base_url" {
  description = "Base invoke URL for the HTTP API ($default stage)."
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "user_pool_id" {
  value = aws_cognito_user_pool.main.id
}

output "user_pool_client_id" {
  value = aws_cognito_user_pool_client.api.id
}

output "sns_topic_arn" {
  value = aws_sns_topic.tickets.arn
}

output "dynamodb_table" {
  value = aws_dynamodb_table.tickets.name
}