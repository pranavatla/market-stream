output "certificate_arn" {
  value = var.create_cert ? aws_acm_certificate.main[0].arn : ""
}

output "fqdn" {
  value = local.fqdn
}

output "zone_id" {
  value = data.aws_route53_zone.main.zone_id
}
