#!/bin/bash
set -euo pipefail

# =============================================================================
# Usage:
#   ./deploy.sh dev     # Deploy dev environment
#   ./deploy.sh prod    # Deploy prod environment
# =============================================================================

ENV="${1:?Usage: ./deploy.sh <dev|prod>}"
REGION="ap-south-1"

if [[ "$ENV" != "dev" && "$ENV" != "prod" ]]; then
  echo "Error: environment must be 'dev' or 'prod'"
  exit 1
fi

echo "Deploying: $ENV"

# Step 1: Terraform
cd terraform
terraform init
terraform plan -var-file="environments/${ENV}.tfvars" -out=tfplan
echo "Review plan above. Enter to apply, Ctrl+C to abort."
read
terraform apply tfplan

# Step 2: Build & push Docker image
cd ..
ECR_REPO=$(terraform -chdir=terraform output -raw ecr_repo_url)
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ECR_REPO"
docker build --platform linux/amd64 -t "${ECR_REPO}:latest" .
docker push "${ECR_REPO}:latest"

# Step 3: Upload frontend
BUCKET=$(terraform -chdir=terraform output -raw frontend_bucket)
aws s3 sync frontend/ "s3://${BUCKET}/" --delete

# Step 4: Force new deployment
eval "$(terraform -chdir=terraform output -json commands | jq -r '.force_deploy')"

echo ""
echo "Done! URL: $(terraform -chdir=terraform output -raw app_url)"
