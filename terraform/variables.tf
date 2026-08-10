# =============================================================================
# GENERAL
# =============================================================================

variable "project" {
  description = "Project name — prefixed to all resource names for namespacing"
  type        = string
  default     = "market-stream"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,20}$", var.project))
    error_message = "Project name must be 3-21 chars, lowercase alphanumeric + hyphens, start with letter."
  }
}

variable "environment" {
  description = "Deployment environment — controls sizing, replicas, and cost guardrails"
  type        = string

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be one of: dev, staging, prod."
  }
}

variable "region" {
  description = "AWS region for all resources"
  type        = string
  default     = "ap-south-1"

  validation {
    condition     = can(regex("^[a-z]{2}-[a-z]+-[0-9]$", var.region))
    error_message = "Must be a valid AWS region format (e.g. ap-south-1)."
  }
}

variable "azs" {
  description = "Availability zones — ALB requires ≥2"
  type        = list(string)
  default     = ["ap-south-1a", "ap-south-1b"]

  validation {
    condition     = length(var.azs) >= 2
    error_message = "At least 2 availability zones required for ALB."
  }
}

# =============================================================================
# NETWORKING
# =============================================================================

variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string
  default     = "10.0.0.0/16"

  validation {
    condition     = can(cidrhost(var.vpc_cidr, 0))
    error_message = "Must be a valid CIDR block."
  }
}

variable "nat_type" {
  description = "NAT implementation: 'instance' (fck-nat, ~$3/mo) or 'gateway' (managed, ~$32/mo)"
  type        = string
  default     = "instance"

  validation {
    condition     = contains(["instance", "gateway"], var.nat_type)
    error_message = "nat_type must be 'instance' or 'gateway'."
  }
}

# =============================================================================
# DOMAIN
# =============================================================================

variable "domain_config" {
  description = "DNS configuration — root domain must have an existing Route 53 hosted zone"
  type = object({
    root_domain = string
    subdomain   = string
    create_cert = bool
  })
  default = {
    root_domain = "atla.in"
    subdomain   = "stream"
    create_cert = true
  }
}

# =============================================================================
# DATABASE
# =============================================================================

variable "database" {
  description = "RDS configuration. Set enabled=false to skip RDS and use SQLite."
  type = object({
    enabled        = bool
    instance_class = string
    engine_version = string
    multi_az       = bool
    storage_gb     = number
    max_storage_gb = number
    backup_days    = number
  })
  default = {
    enabled        = true
    instance_class = "db.t4g.micro"
    engine_version = "16.3"
    multi_az       = false
    storage_gb     = 20
    max_storage_gb = 50
    backup_days    = 7
  }

  validation {
    condition     = var.database.storage_gb >= 20
    error_message = "Minimum RDS storage is 20 GB for gp3."
  }

  validation {
    condition     = var.database.max_storage_gb >= var.database.storage_gb
    error_message = "max_storage_gb must be >= storage_gb."
  }
}

variable "db_credentials" {
  description = "Database credentials — never commit to version control"
  type = object({
    username = string
    password = string
  })
  sensitive = true

  validation {
    condition     = length(var.db_credentials.password) >= 12
    error_message = "Database password must be at least 12 characters."
  }
}

# =============================================================================
# ANGEL ONE (LIVE MARKET FEED)
# =============================================================================

variable "angelone_credentials" {
  description = <<-EOT
    Angel One SmartAPI credentials, written to Secrets Manager and injected
    into the container as secrets. Only used when FEED_TYPE=angelone.
    Never commit to version control — the TOTP secret is a 2FA seed and
    grants account access on its own.
  EOT
  type = object({
    client_id   = string
    api_key     = string
    totp_secret = string
    pin         = string
  })
  sensitive = true

  default = {
    client_id   = ""
    api_key     = ""
    totp_secret = ""
    pin         = ""
  }
}

# =============================================================================
# CONTAINER / ECS
# =============================================================================

variable "container" {
  description = "ECS task sizing and scaling configuration"
  type = object({
    cpu           = number
    memory        = number
    desired_count = number
    min_count     = number
    max_count     = number
    image_tag     = string
  })

  validation {
    condition     = contains([256, 512, 1024, 2048, 4096], var.container.cpu)
    error_message = "Fargate CPU must be one of: 256, 512, 1024, 2048, 4096."
  }

  validation {
    condition     = var.container.min_count <= var.container.desired_count
    error_message = "min_count must be <= desired_count."
  }

  validation {
    condition     = var.container.max_count >= var.container.desired_count
    error_message = "max_count must be >= desired_count."
  }
}

variable "app_environment" {
  description = "Environment variables injected into the container (non-sensitive)"
  type        = map(string)
  default = {
    FEED_INTERVAL_MS = "500"
    SYMBOLS          = "NIFTY50,SENSEX,BANKNIFTY,RELIANCE,TCS"
  }
}

variable "autoscaling_thresholds" {
  description = "CPU and memory targets for auto-scaling policies"
  type = object({
    cpu_target         = number
    memory_target      = number
    scale_in_cooldown  = number
    scale_out_cooldown = number
  })
  default = {
    cpu_target         = 70
    memory_target      = 80
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

# =============================================================================
# TAGS
# =============================================================================

variable "extra_tags" {
  description = "Additional tags merged with computed common tags"
  type        = map(string)
  default     = {}
}
