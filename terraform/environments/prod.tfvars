# =============================================================================
# PROD ENVIRONMENT                                 Estimated: ~$105/month
# =============================================================================
# terraform plan -var-file="environments/prod.tfvars"

environment = "prod"
region      = "ap-south-1"
azs         = ["ap-south-1a", "ap-south-1b"]
nat_type    = "gateway" # Managed NAT — HA, no maintenance

domain_config = {
  root_domain = "atla.in"
  subdomain   = "stream"
  create_cert = true
}

database = {
  enabled        = true
  instance_class = "db.t4g.micro"
  engine_version = "16.14"
  multi_az       = true # HA — auto-failover
  storage_gb     = 20
  max_storage_gb = 100
  backup_days    = 14 # 2 weeks retention
}

db_credentials = {
  username = "marketstream"
  password = "prod-REPLACE-this-password-456"
}

container = {
  cpu           = 512  # 0.5 vCPU — more headroom
  memory        = 1024 # 1 GB
  desired_count = 2    # 2 tasks for availability
  min_count     = 2
  max_count     = 6
  image_tag     = "v1.0.0" # Pinned tag, never :latest in prod
}

app_environment = {
  FEED_INTERVAL_MS = "500"
  SYMBOLS          = "NIFTY50,SENSEX,BANKNIFTY,RELIANCE,TCS"
}

autoscaling_thresholds = {
  cpu_target         = 70
  memory_target      = 80
  scale_in_cooldown  = 300 # Conservative scale-down
  scale_out_cooldown = 60
}

extra_tags = {
  CostCenter = "infrastructure"
}
