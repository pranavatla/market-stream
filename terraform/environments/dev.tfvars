# =============================================================================
# DEV ENVIRONMENT                                  Estimated: ~$42/month
# =============================================================================
# terraform plan -var-file="environments/dev.tfvars"

environment = "dev"
region      = "ap-south-1"
azs         = ["ap-south-1a", "ap-south-1b"]
nat_type    = "instance" # fck-nat t4g.nano — $3 vs $32

domain_config = {
  root_domain = "atla.in"
  subdomain   = "stream-dev"
  create_cert = true
}

database = {
  enabled        = true
  instance_class = "db.t4g.micro" # Cheapest: $12/month
  engine_version = "16.14"
  multi_az       = false # Single AZ for dev
  storage_gb     = 20    # Minimum
  max_storage_gb = 50
  backup_days    = 3 # Shorter retention for dev
}

db_credentials = {
  username = "marketstream"
  password = "dev-REPLACE-this-password-123"
}

container = {
  cpu           = 256 # 0.25 vCPU — smallest Fargate tier
  memory        = 512 # 0.5 GB
  desired_count = 1   # Single task
  min_count     = 1
  max_count     = 2 # Scale to 2 max in dev
  image_tag     = "latest"
}

app_environment = {
  FEED_INTERVAL_MS = "1000"                     # Slower ticks in dev (saves CPU)
  SYMBOLS          = "NIFTY50,SENSEX,BANKNIFTY" # Fewer symbols
}

autoscaling_thresholds = {
  cpu_target         = 80 # More tolerant in dev
  memory_target      = 85
  scale_in_cooldown  = 120 # Faster scale-down in dev
  scale_out_cooldown = 60
}

extra_tags = {
  CostCenter = "personal"
  Temporary  = "true"
}
