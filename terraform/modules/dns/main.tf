locals {
  fqdn = "${var.subdomain}.${var.root_domain}"
}

data "aws_route53_zone" "main" {
  name = var.root_domain
}

# =============================================================================
# ACM CERTIFICATE (conditional)
# =============================================================================

resource "aws_acm_certificate" "main" {
  count             = var.create_cert ? 1 : 0
  domain_name       = local.fqdn
  validation_method = "DNS"

  lifecycle { create_before_destroy = true }
  tags = merge(var.tags, { Name = "${var.name_prefix}-cert" })
}

resource "aws_route53_record" "cert_validation" {
  for_each = var.create_cert ? {
    for dvo in aws_acm_certificate.main[0].domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  } : {}

  zone_id = data.aws_route53_zone.main.zone_id
  name    = each.value.name
  type    = each.value.type
  ttl     = 300
  records = [each.value.record]
}

resource "aws_acm_certificate_validation" "main" {
  count                   = var.create_cert ? 1 : 0
  certificate_arn         = aws_acm_certificate.main[0].arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation : r.fqdn]
}

# =============================================================================
# DNS A RECORD → ALB
# =============================================================================

resource "aws_route53_record" "app" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = local.fqdn
  type    = "A"

  alias {
    name                   = var.alb_dns
    zone_id                = var.alb_zone_id
    evaluate_target_health = true
  }
}
