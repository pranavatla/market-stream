# =============================================================================
# ROOT OUTPUTS — aggregated from modules
# =============================================================================

output "app_url" {
  description = "Application URL"
  value       = "https://${local.fqdn}"
}

output "alb_dns" {
  description = "ALB DNS (use before Route 53 propagates)"
  value       = module.loadbalancer.alb_dns_name
}

output "ecr_repo_url" {
  description = "ECR repository URL for docker push"
  value       = module.storage.ecr_repo_url
}

output "rds_endpoint" {
  description = "RDS endpoint (empty if database disabled)"
  value       = var.database.enabled ? module.database[0].endpoint : "N/A (sqlite mode)"
}

output "frontend_bucket" {
  description = "S3 bucket for frontend assets"
  value       = module.storage.frontend_bucket
}

output "vpc_id" {
  description = "VPC ID"
  value       = module.networking.vpc_id
}

output "github_actions_role_arn" {
  description = "IAM role ARN for GitHub Actions OIDC — set as role-to-assume in .github/workflows/deploy.yml"
  value       = module.cicd.role_arn
}

# =============================================================================
# OPERATIONAL COMMANDS
# =============================================================================

output "commands" {
  description = "Copy-paste commands for common operations"
  value = {
    push_image = join("\n", [
      "aws ecr get-login-password --region ${var.region} | docker login --username AWS --password-stdin ${module.storage.ecr_repo_url}",
      "docker build --platform linux/amd64 -t ${module.storage.ecr_repo_url}:${var.container.image_tag} .",
      "docker push ${module.storage.ecr_repo_url}:${var.container.image_tag}",
    ])
    deploy_frontend = "aws s3 sync frontend/ s3://${module.storage.frontend_bucket}/ --delete"
    force_deploy    = "aws ecs update-service --cluster ${local.name_prefix}-cluster --service ${local.name_prefix} --force-new-deployment --region ${var.region}"
    view_logs       = "aws logs tail /ecs/${local.name_prefix} --follow --region ${var.region}"
    service_status  = "aws ecs describe-services --cluster ${local.name_prefix}-cluster --services ${local.name_prefix} --region ${var.region} --query 'services[0].{Status:status,Running:runningCount,Desired:desiredCount}'"
  }
}

# =============================================================================
# COST ESTIMATE
# =============================================================================

output "estimated_monthly_cost" {
  description = "Estimated monthly cost breakdown"

  value = {
    alb = "$16.20"

    rds = var.database.enabled ? format(
      "$%.2f",
      var.database.multi_az ? 23.36 : 11.68
    ) : "$0 (disabled)"

    fargate = format(
      "$%.2f",
      var.container.desired_count * 9.01
    )

    nat = var.nat_type == "instance" ? "$2.63" : "$32.85"

    s3_r53_ecr = "$1.50"

    total = format(
      "$%.2f",
      16.20 +
      (var.database.enabled ? (var.database.multi_az ? 23.36 : 11.68) : 0) +
      (var.container.desired_count * 9.01) +
      (var.nat_type == "instance" ? 2.63 : 32.85) +
      1.50
    )
  }
}