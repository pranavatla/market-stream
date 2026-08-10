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
  description = "Sensitive env vars — passed as environment for now, use Secrets Manager in prod"
  type        = map(string)
  default     = {}
  sensitive   = true
}

variable "scaling" {
  type = object({
    cpu_target         = number
    memory_target      = number
    scale_in_cooldown  = number
    scale_out_cooldown = number
  })
}