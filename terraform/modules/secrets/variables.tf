variable "name_prefix" {
  description = "Resource name prefix — secret is created at {name_prefix}/app-secrets"
  type        = string
}

variable "db_password" {
  description = "RDS master password"
  type        = string
  sensitive   = true
}

variable "angelone_client_id" {
  description = "Angel One SmartAPI client / user ID"
  type        = string
  sensitive   = true
}

variable "angelone_api_key" {
  description = "Angel One SmartAPI key"
  type        = string
  sensitive   = true
}

variable "angelone_totp_secret" {
  description = "Angel One TOTP seed used to generate 2FA codes at login"
  type        = string
  sensitive   = true
}

variable "angelone_pin" {
  description = "Angel One account PIN/MPIN — required by SmartConnect.generateSession() alongside the TOTP code"
  type        = string
  sensitive   = true
}

variable "recovery_window_days" {
  description = "Days Secrets Manager retains the secret after destroy. 0 = immediate delete (dev-friendly; the name is reusable right away)."
  type        = number
  default     = 0

  validation {
    condition     = var.recovery_window_days == 0 || (var.recovery_window_days >= 7 && var.recovery_window_days <= 30)
    error_message = "recovery_window_days must be 0, or between 7 and 30."
  }
}

variable "tags" {
  description = "Tags applied to the secret"
  type        = map(string)
  default     = {}
}
