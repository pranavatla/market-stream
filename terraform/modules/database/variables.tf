variable "name_prefix" { type = string }
variable "vpc_id" { type = string }
variable "vpc_cidr" { type = string }
variable "subnet_ids" { type = list(string) }
variable "instance_class" { type = string }
variable "engine_version" { type = string }
variable "multi_az" { type = bool }
variable "storage_gb" { type = number }
variable "max_storage_gb" { type = number }
variable "backup_days" { type = number }
variable "db_username" {
  type      = string
  sensitive = true
}
variable "db_password" {
  type      = string
  sensitive = true
}
variable "tags" { type = map(string) }