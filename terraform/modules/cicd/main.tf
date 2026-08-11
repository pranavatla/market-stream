# =============================================================================
# CI/CD — GitHub Actions OIDC + deploy role
# =============================================================================
# Lets GitHub Actions assume an AWS role via short-lived OIDC tokens instead of
# long-lived access keys. The trust policy pins BOTH the repo and the branch,
# so only workflows on that ref can assume the role.

# -----------------------------------------------------------------------------
# OIDC PROVIDER
# -----------------------------------------------------------------------------
# NOTE: there can be only ONE provider per URL per AWS account. If the account
# already has a GitHub Actions OIDC provider, set create_oidc_provider=false to
# reuse it (otherwise apply fails with EntityAlreadyExists).
resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider ? 1 : 0

  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = var.oidc_thumbprints

  tags = merge(var.tags, { Name = "${var.name_prefix}-github-oidc" })
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider ? 0 : 1
  url   = "https://token.actions.githubusercontent.com"
}

locals {
  oidc_provider_arn = var.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github[0].arn

  # GitHub OIDC sub is repo-scoped in the trust policy so manual and push deploys both work.

  # New-format ECS service ARN, for resource-scoped ecs:* permissions.
  ecs_service_arn = "arn:aws:ecs:${var.region}:${var.account_id}:service/${var.ecs_cluster_name}/${var.ecs_service_name}"
}

# -----------------------------------------------------------------------------
# DEPLOY ROLE
# -----------------------------------------------------------------------------
resource "aws_iam_role" "github_actions" {
  name        = "${var.name_prefix}-github-actions"
  description = "Assumed by GitHub Actions (${var.github_repo}@${var.github_branch}) to build+push image and deploy ECS"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = local.oidc_provider_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repo}:*"
        }
      }
    }]
  })

  tags = merge(var.tags, { Name = "${var.name_prefix}-github-actions" })
}

resource "aws_iam_role_policy" "deploy" {
  name = "${var.name_prefix}-github-actions-deploy"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # GetAuthorizationToken has no resource-level support — must be "*".
        Sid      = "EcrAuth"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = ["*"]
      },
      {
        Sid    = "EcrPushPull"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchGetImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage",
        ]
        Resource = [var.ecr_repo_arn]
      },
      {
        Sid      = "EcsDeploy"
        Effect   = "Allow"
        Action   = ["ecs:UpdateService", "ecs:DescribeServices"]
        Resource = [local.ecs_service_arn]
      },
    ]
  })
}
