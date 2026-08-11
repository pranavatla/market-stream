variable "name_prefix" {
  description = "Resource name prefix — role is named {name_prefix}-github-actions"
  type        = string
}

variable "account_id" {
  description = "AWS account ID, for constructing the ECS service ARN"
  type        = string
}

variable "region" {
  description = "AWS region, for constructing the ECS service ARN"
  type        = string
}

variable "github_repo" {
  description = "GitHub repository in owner/name form — trust is pinned to this repo"
  type        = string
}

variable "github_branch" {
  description = "Branch whose workflows may assume the role"
  type        = string
}

variable "ecr_repo_arn" {
  description = "ARN of the ECR repo the workflow pushes to"
  type        = string
}

variable "ecs_cluster_name" {
  description = "ECS cluster name the service runs on"
  type        = string
}

variable "ecs_service_name" {
  description = "ECS service the workflow force-deploys"
  type        = string
}

variable "create_oidc_provider" {
  description = "Create the GitHub OIDC provider. Set false to reuse an existing one (only one per URL is allowed per account)."
  type        = bool
  default     = true
}

variable "oidc_thumbprints" {
  description = "Root CA thumbprints for the GitHub OIDC endpoint. AWS ignores these for the well-known GitHub IdP, but the argument is still accepted."
  type        = list(string)
  default = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fca",
  ]
}

variable "tags" {
  description = "Tags applied to CI/CD resources"
  type        = map(string)
  default     = {}
}
