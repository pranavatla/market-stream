variable "name_prefix" { type = string }
variable "vpc_id" { type = string }
variable "public_subnets" { type = list(string) }
variable "certificate_arn" { type = string }
variable "health_check_path" {
  type    = string
  default = "/api/symbols"
}
variable "tags" { type = map(string) }