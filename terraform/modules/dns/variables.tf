variable "name_prefix" { type = string }
variable "root_domain" { type = string }
variable "subdomain" { type = string }
variable "create_cert" {
  type    = bool
  default = true
}
variable "alb_dns" { type = string }
variable "alb_zone_id" { type = string }
variable "tags" { type = map(string) }