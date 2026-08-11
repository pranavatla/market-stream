output "role_arn" {
  description = "ARN of the GitHub Actions deploy role — use as role-to-assume in the workflow"
  value       = aws_iam_role.github_actions.arn
}

output "role_name" {
  description = "Name of the GitHub Actions deploy role"
  value       = aws_iam_role.github_actions.name
}

output "oidc_provider_arn" {
  description = "ARN of the GitHub OIDC provider in use (created or pre-existing)"
  value       = local.oidc_provider_arn
}
