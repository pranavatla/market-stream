output "ecr_repo_url" { value = aws_ecr_repository.app.repository_url }
output "ecr_repo_arn" { value = aws_ecr_repository.app.arn }
output "frontend_bucket" { value = aws_s3_bucket.frontend.bucket }
output "frontend_bucket_arn" { value = aws_s3_bucket.frontend.arn }
