variable "name_prefix" { type = string }
variable "region" { type = string }
variable "vpc_id" { type = string }
variable "private_subnets" { type = list(string) }
variable "alb_sg_id" { type = string }
variable "target_group_arn" { type = string }
variable "ecr_repo_url" { type = string }
variable "image_tag" { type = string }
variable "cpu" { type = number }
variable "memory" { type = number }
variable "desired_count" { type = number }
variable "container_port" {
  type    = number
  default = 8000
}
variable "min_count" { type = number }
variable "max_count" { type = number }
variable "tags" { type = map(string) }

variable "environment_variables" {
  description = "Non-sensitive env vars injected into the container"
  type        = map(string)
  default     = {}
}

variable "secret_variables" {
  description = <<-EOT
    Sensitive env vars. Only the KEYS are used here — each becomes a `secrets`
    entry resolved from Secrets Manager at task start via
    `{secret_arn}:{KEY}::`. The values are written to the secret by the
    secrets module, never into the task definition.
  EOT
  type        = map(string)
  default     = {}
  sensitive   = true
}

variable "secret_arn" {
  description = "ARN of the Secrets Manager secret holding the JSON keys named in secret_variables"
  type        = string
  default     = ""
}

variable "enable_secrets" {
  description = "Whether to source sensitive env vars from Secrets Manager. Static (not derived from secret_arn) because count must be known at plan time."
  type        = bool
  default     = false
}

variable "scaling" {
  type = object({
    cpu_target         = number
    memory_target      = number
    scale_in_cooldown  = number
    scale_out_cooldown = number
  })
}