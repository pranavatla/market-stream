# =============================================================================
# MODULE COMPOSITION
# =============================================================================
# Each module is a self-contained unit with its own variables and outputs.
# This file wires them together — outputs from one become inputs to another.
# The dependency graph:
#
#   networking ─┬─► loadbalancer ─► dns
#               ├─► database
#               └─► ecs (depends on loadbalancer, database, storage)
#   storage (independent)

data "aws_caller_identity" "current" {}

# =============================================================================
# NETWORKING
# =============================================================================
module "networking" {
  source = "./modules/networking"

  name_prefix = local.name_prefix
  vpc_cidr    = var.vpc_cidr
  azs         = var.azs
  nat_type    = var.nat_type
  tags        = local.common_tags
}

# =============================================================================
# STORAGE (ECR + S3)
# =============================================================================
module "storage" {
  source = "./modules/storage"

  name_prefix = local.name_prefix
  account_id  = data.aws_caller_identity.current.account_id
  tags        = local.common_tags
}

# =============================================================================
# SECRETS (Secrets Manager)
# =============================================================================
# Holds DB and Angel One credentials as one JSON document. ECS pulls
# individual keys at container start, so no plaintext lands in the task
# definition.
module "secrets" {
  source = "./modules/secrets"

  name_prefix          = local.name_prefix
  db_password          = var.db_credentials.password
  angelone_client_id   = var.angelone_credentials.client_id
  angelone_api_key     = var.angelone_credentials.api_key
  angelone_totp_secret = var.angelone_credentials.totp_secret
  angelone_pin         = var.angelone_credentials.pin
  tags                 = local.common_tags
}

# =============================================================================
# DATABASE (conditional — skipped if database.enabled = false)
# =============================================================================
module "database" {
  source = "./modules/database"
  count  = var.database.enabled ? 1 : 0 # Conditional module creation

  name_prefix    = local.name_prefix
  vpc_id         = module.networking.vpc_id
  vpc_cidr       = var.vpc_cidr
  subnet_ids     = module.networking.private_subnet_ids
  instance_class = var.database.instance_class
  engine_version = var.database.engine_version
  multi_az       = local.is_prod ? true : var.database.multi_az # Force multi-AZ in prod
  storage_gb     = var.database.storage_gb
  max_storage_gb = var.database.max_storage_gb
  backup_days    = var.database.backup_days
  db_username    = var.db_credentials.username
  db_password    = var.db_credentials.password
  tags           = local.common_tags
}

# =============================================================================
# LOAD BALANCER
# =============================================================================
module "loadbalancer" {
  source = "./modules/loadbalancer"

  name_prefix       = local.name_prefix
  vpc_id            = module.networking.vpc_id
  public_subnets    = module.networking.public_subnet_ids
  certificate_arn   = module.dns.certificate_arn
  health_check_path = "/api/symbols"
  tags              = local.common_tags
}

# =============================================================================
# ECS
# =============================================================================
module "ecs" {
  source = "./modules/ecs"

  name_prefix      = local.name_prefix
  region           = var.region
  vpc_id           = module.networking.vpc_id
  private_subnets  = module.networking.private_subnet_ids
  alb_sg_id        = module.loadbalancer.alb_security_group_id
  target_group_arn = module.loadbalancer.target_group_arn

  # Container config
  ecr_repo_url   = module.storage.ecr_repo_url
  image_tag      = var.container.image_tag
  cpu            = var.container.cpu
  memory         = var.container.memory
  desired_count  = var.container.desired_count
  container_port = 8000

  # Environment
  environment_variables = local.container_environment
  secret_variables      = local.container_secrets
  secret_arn            = module.secrets.secret_arn
  enable_secrets        = true

  # Auto-scaling
  min_count = var.container.min_count
  max_count = var.container.max_count
  scaling   = var.autoscaling_thresholds

  tags = local.common_tags
}

# =============================================================================
# DNS
# =============================================================================
module "dns" {
  source = "./modules/dns"

  name_prefix = local.name_prefix
  root_domain = var.domain_config.root_domain
  subdomain   = var.domain_config.subdomain
  create_cert = var.domain_config.create_cert
  alb_dns     = module.loadbalancer.alb_dns_name
  alb_zone_id = module.loadbalancer.alb_zone_id
  tags        = local.common_tags
}
