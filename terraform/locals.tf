# =============================================================================
# LOCALS — computed values derived from variables
# =============================================================================
# Centralises naming, tagging, and environment-specific logic.
# Modules receive these as inputs — they never read var.* directly.
# This keeps modules reusable and the root config as the single source of truth.

locals {
  # Naming convention: {project}-{environment}-{resource}
  name_prefix = "${var.project}-${var.environment}"

  # Merge default tags with environment context and user-supplied extras
  common_tags = merge(
    {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
      Owner       = "pranav"
    },
    var.extra_tags,
  )

  # FQDN computed from domain config
  fqdn = "${var.domain_config.subdomain}.${var.domain_config.root_domain}"

  # Environment-specific sizing overrides
  # Even though tfvars sets these explicitly, having guardrails here
  # catches misconfigurations early.
  is_prod = var.environment == "prod"

  # Database connection string components (used by ECS task definition)
  db_config = var.database.enabled ? {
    type     = "postgres"
    host     = module.database[0].endpoint
    port     = "5432"
    name     = module.database[0].db_name
    username = var.db_credentials.username
    password = var.db_credentials.password
    } : {
    type     = "sqlite"
    host     = ""
    port     = ""
    name     = ""
    username = ""
    password = ""
  }

  # Container environment — merge app vars with DB config
  container_environment = merge(
    var.app_environment,
    {
      DB_TYPE = local.db_config.type
      DB_HOST = local.db_config.host
      DB_PORT = local.db_config.port
      DB_NAME = local.db_config.name
      DB_USER = local.db_config.username
    },
  )

  # Sensitive env vars — separated so they can use ECS secrets in prod
  container_secrets = var.database.enabled ? {
    DB_PASSWORD = local.db_config.password
  } : {}
}
