# =============================================================================
# SECRETS MANAGER
# =============================================================================
# One secret holding every sensitive value the container needs, stored as a
# JSON document. ECS references individual keys via the
# `{secret_arn}:{JSON_KEY}::` valueFrom syntax, so the task definition never
# carries plaintext and the values never appear in `terraform show` output
# of the ECS module.

resource "aws_secretsmanager_secret" "app" {
  name        = "${var.name_prefix}/app-secrets"
  description = "Application secrets for ${var.name_prefix} (DB + Angel One credentials)"

  # 0 = delete immediately on destroy. Secrets Manager otherwise reserves the
  # name for the recovery window, which blocks re-creating the same stack.
  recovery_window_in_days = var.recovery_window_days

  tags = merge(var.tags, { Name = "${var.name_prefix}-app-secrets" })
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id

  secret_string = jsonencode({
    DB_PASSWORD          = var.db_password
    ANGELONE_CLIENT_ID   = var.angelone_client_id
    ANGELONE_API_KEY     = var.angelone_api_key
    ANGELONE_TOTP_SECRET = var.angelone_totp_secret
    ANGELONE_PIN         = var.angelone_pin
  })
}
