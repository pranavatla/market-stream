output "secret_arn" {
  description = "ARN of the app secrets bundle — used by ECS valueFrom references"
  value       = aws_secretsmanager_secret.app.arn
}

output "secret_name" {
  description = "Name of the secret"
  value       = aws_secretsmanager_secret.app.name
}
