# =============================================================================
# ECR
# =============================================================================

resource "aws_ecr_repository" "app" {
  name                 = "${var.name_prefix}/api"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration { scan_on_push = true }

  tags = merge(var.tags, { Name = "${var.name_prefix}-ecr" })
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

# =============================================================================
# S3
# =============================================================================

resource "aws_s3_bucket" "frontend" {
  bucket        = "${var.name_prefix}-frontend-${var.account_id}"
  force_destroy = true
  tags          = merge(var.tags, { Name = "${var.name_prefix}-frontend" })
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
