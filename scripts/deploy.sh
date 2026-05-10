#!/bin/bash
set -e

# ==============================================================================
# IAN Knowledge Management Framework — Cloud Deployment Script
# ==============================================================================
#
# Cloud Resources:
#   GCP Project:       nyu-cloud-computing-project
#   Azure RG:          nyu-cc
#   AWS Region:        us-east-1
#
# Usage:
#   ./scripts/deploy.sh [all|gcp|azure|aws]
#
# Prerequisites:
#   - gcloud CLI authenticated
#   - az CLI authenticated
#   - aws CLI authenticated
#   - Docker running
# ==============================================================================

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STAGE_DIR="$ROOT_DIR/.deploy-staging"

# --- Cloud Config ---
GCP_PROJECT="nyu-cloud-computing-project"
GCP_REGION="us-east1"

AZURE_RG="nyu-cc"
AZURE_ACR="ianknowledgemgmt"
AZURE_LLM_CONTAINER="ian-llm-worker"

AWS_REGION="us-east-1"
AWS_ACCOUNT_ID=""  # filled dynamically
AWS_CLUSTER="ian-cluster"
AWS_SG=""          # filled dynamically

# --- Helpers ---
log() { echo -e "\n\033[1;34m==>\033[0m \033[1m$1\033[0m"; }
ok()  { echo -e "\033[1;32m    ✓ $1\033[0m"; }
err() { echo -e "\033[1;31m    ✗ $1\033[0m"; exit 1; }

authorize_sg_ingress() {
    local sg_id=$1 protocol=$2 port=$3 cidr=$4

    aws ec2 authorize-security-group-ingress \
        --group-id "$sg_id" \
        --protocol "$protocol" \
        --port "$port" \
        --cidr "$cidr" \
        --region "$AWS_REGION" > /dev/null 2>&1 || true
}

stage_service() {
    local svc=$1
    log "Staging $svc"
    rm -rf "$STAGE_DIR/$svc"
    mkdir -p "$STAGE_DIR/$svc"
    cp -r "$ROOT_DIR/$svc/"* "$STAGE_DIR/$svc/"
    cp -r "$ROOT_DIR/common" "$STAGE_DIR/$svc/common"
    # Copy service account if it exists (for Azure/AWS Firestore access)
    if [ -f "$ROOT_DIR/service-account.json" ]; then
        cp "$ROOT_DIR/service-account.json" "$STAGE_DIR/$svc/service-account.json"
    fi
    ok "Staged $svc -> $STAGE_DIR/$svc"
}

# ==============================================================================
# GCP: Deploy API Server to App Engine Flex
# ==============================================================================
deploy_gcp() {
    log "Deploying API Server to GCP App Engine"

    gcloud config set project "$GCP_PROJECT" 2>/dev/null

    stage_service "api-server"

    cd "$STAGE_DIR/api-server"
    gcloud app deploy app.yaml --project="$GCP_PROJECT" --quiet

    local url="https://$GCP_PROJECT.ue.r.appspot.com"
    ok "API Server deployed: $url"
    echo "  Health check: $url/health"
}

# ==============================================================================
# Azure: Deploy LLM Worker to Azure Container Instances
# ==============================================================================
deploy_azure() {
    log "Deploying LLM Worker to Azure Container Instances"

    # Create ACR if not exists
    if ! az acr show --name "$AZURE_ACR" --resource-group "$AZURE_RG" &>/dev/null; then
        log "Creating Azure Container Registry: $AZURE_ACR"
        az acr create --resource-group "$AZURE_RG" --name "$AZURE_ACR" --sku Basic --admin-enabled true
    fi
    ok "ACR: $AZURE_ACR.azurecr.io"

    # Login to ACR
    az acr login --name "$AZURE_ACR"

    # Build and push image
    stage_service "llm-worker"
    log "Building and pushing Docker image"
    docker build --platform linux/amd64 -t "$AZURE_ACR.azurecr.io/ian-llm-worker:latest" "$STAGE_DIR/llm-worker"
    docker push "$AZURE_ACR.azurecr.io/ian-llm-worker:latest"
    ok "Image pushed: $AZURE_ACR.azurecr.io/ian-llm-worker:latest"

    # Read Azure OpenAI creds from .env
    local aoai_endpoint aoai_key aoai_deployment
    aoai_endpoint=$(grep AZURE_OPENAI_ENDPOINT "$ROOT_DIR/.env" | cut -d= -f2-)
    aoai_key=$(grep AZURE_OPENAI_KEY "$ROOT_DIR/.env" | cut -d= -f2-)
    aoai_deployment=$(grep AZURE_OPENAI_DEPLOYMENT "$ROOT_DIR/.env" | cut -d= -f2-)

    # Get ACR credentials
    local acr_password
    acr_password=$(az acr credential show --name "$AZURE_ACR" --query "passwords[0].value" -o tsv)

    # Delete existing container if it exists
    az container delete --resource-group "$AZURE_RG" --name "$AZURE_LLM_CONTAINER" --yes 2>/dev/null || true

    # Create Container Instance
    log "Creating Container Instance: $AZURE_LLM_CONTAINER"
    az container create \
        --resource-group "$AZURE_RG" \
        --name "$AZURE_LLM_CONTAINER" \
        --image "$AZURE_ACR.azurecr.io/ian-llm-worker:latest" \
        --registry-login-server "$AZURE_ACR.azurecr.io" \
        --registry-username "$AZURE_ACR" \
        --registry-password "$acr_password" \
        --cpu 1 \
        --memory 2.0 \
        --ports 8080 4001 \
        --ip-address Public \
        --os-type Linux \
        --environment-variables \
            GCP_PROJECT_ID="$GCP_PROJECT" \
            GOOGLE_APPLICATION_CREDENTIALS="/app/service-account.json" \
            AZURE_OPENAI_ENDPOINT="$aoai_endpoint" \
            AZURE_OPENAI_KEY="$aoai_key" \
            AZURE_OPENAI_DEPLOYMENT="$aoai_deployment" \
            AZURE_OPENAI_API_VERSION="2024-12-01-preview" \
            IPFS_API_URL="http://127.0.0.1:5001/api/v0" \
            IPFS_GATEWAY_URL="https://ipfs.io/ipfs/" \
            POLL_INTERVAL_SECONDS="10"

    local ip
    ip=$(az container show --resource-group "$AZURE_RG" --name "$AZURE_LLM_CONTAINER" --query 'ipAddress.ip' -o tsv)
    ok "LLM Worker deployed: http://$ip:8080"
    echo "  Health check: http://$ip:8080/health"
}

# ==============================================================================
# AWS: Deploy Orchestrator + Library Worker to ECS Fargate
# ==============================================================================
deploy_aws() {
    log "Deploying Orchestrator + Library Worker to AWS ECS Fargate"

    AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    local ecr_base="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

    # Login to ECR
    aws ecr get-login-password --region "$AWS_REGION" | \
        docker login --username AWS --password-stdin "$ecr_base"

    # --- Create ECR repos ---
    for repo in ian-orchestrator ian-library-worker; do
        aws ecr describe-repositories --repository-names "$repo" --region "$AWS_REGION" &>/dev/null || \
            aws ecr create-repository --repository-name "$repo" --region "$AWS_REGION" > /dev/null
        ok "ECR repo: $repo"
    done

    # --- Build and push Orchestrator ---
    stage_service "orchestrator"
    log "Building Orchestrator"
    docker build --platform linux/amd64 -t "$ecr_base/ian-orchestrator:latest" "$STAGE_DIR/orchestrator"
    docker push "$ecr_base/ian-orchestrator:latest"
    ok "Image pushed: $ecr_base/ian-orchestrator:latest"

    # --- Build and push Library Worker ---
    stage_service "library-worker"
    log "Building Library Worker"
    docker build --platform linux/amd64 -t "$ecr_base/ian-library-worker:latest" "$STAGE_DIR/library-worker"
    docker push "$ecr_base/ian-library-worker:latest"
    ok "Image pushed: $ecr_base/ian-library-worker:latest"

    # --- ECS Cluster ---
    aws ecs describe-clusters --clusters "$AWS_CLUSTER" --region "$AWS_REGION" --query 'clusters[0].status' --output text 2>/dev/null | grep -q ACTIVE || \
        aws ecs create-cluster --cluster-name "$AWS_CLUSTER" --region "$AWS_REGION" > /dev/null
    ok "ECS Cluster: $AWS_CLUSTER"

    # --- IAM Role ---
    if ! aws iam get-role --role-name ecsTaskExecutionRole &>/dev/null; then
        log "Creating ecsTaskExecutionRole"
        aws iam create-role \
            --role-name ecsTaskExecutionRole \
            --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]}' > /dev/null
        aws iam attach-role-policy \
            --role-name ecsTaskExecutionRole \
            --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
    fi
    ok "IAM Role: ecsTaskExecutionRole"

    # --- VPC / Security Group ---
    local vpc_id
    vpc_id=$(aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" --region "$AWS_REGION" --query 'Vpcs[0].VpcId' --output text)
    local subnets
    subnets=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$vpc_id" --region "$AWS_REGION" --query 'Subnets[0:2].SubnetId' --output text | tr '\t' ',')

    # Create or find security group
    AWS_SG=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=ian-ecs-sg" "Name=vpc-id,Values=$vpc_id" --region "$AWS_REGION" --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null)
    if [ "$AWS_SG" = "None" ] || [ -z "$AWS_SG" ]; then
        AWS_SG=$(aws ec2 create-security-group --group-name ian-ecs-sg --description "IAN ECS services" --vpc-id "$vpc_id" --region "$AWS_REGION" --query 'GroupId' --output text)
    fi
    authorize_sg_ingress "$AWS_SG" tcp 8080 0.0.0.0/0
    authorize_sg_ingress "$AWS_SG" tcp 4001 0.0.0.0/0
    authorize_sg_ingress "$AWS_SG" udp 4001 0.0.0.0/0
    ok "Security Group: $AWS_SG"

    # --- CloudWatch Log Groups ---
    aws logs create-log-group --log-group-name /ecs/ian-orchestrator --region "$AWS_REGION" 2>/dev/null || true
    aws logs create-log-group --log-group-name /ecs/ian-library-worker --region "$AWS_REGION" 2>/dev/null || true

    # --- Deploy each service ---
    _deploy_ecs "ian-orchestrator" "$ecr_base/ian-orchestrator:latest" 256 512 "$subnets" "" "false"
    _deploy_ecs "ian-library-worker" "$ecr_base/ian-library-worker:latest" 512 2048 "$subnets" "http://127.0.0.1:5001/api/v0" "true"

    ok "All AWS services deployed to ECS Fargate"
}

_deploy_ecs() {
    local name=$1 image=$2 cpu=$3 memory=$4 subnets=$5 ipfs_api=$6 expose_ipfs=${7:-false}
    local port_mappings='[{"containerPort": 8080, "protocol": "tcp"}]'

    if [ "$expose_ipfs" = "true" ]; then
        port_mappings='[
                {"containerPort": 8080, "protocol": "tcp"},
                {"containerPort": 4001, "protocol": "tcp"},
                {"containerPort": 4001, "protocol": "udp"}
            ]'
    fi

    log "Deploying $name"

    # Register task definition
    aws ecs register-task-definition \
        --family "$name" \
        --network-mode awsvpc \
        --requires-compatibilities FARGATE \
        --cpu "$cpu" \
        --memory "$memory" \
        --execution-role-arn "arn:aws:iam::${AWS_ACCOUNT_ID}:role/ecsTaskExecutionRole" \
        --container-definitions "[{
            \"name\": \"$name\",
            \"image\": \"$image\",
            \"portMappings\": $port_mappings,
            \"environment\": [
                {\"name\": \"GCP_PROJECT_ID\", \"value\": \"$GCP_PROJECT\"},
                {\"name\": \"GOOGLE_APPLICATION_CREDENTIALS\", \"value\": \"/app/service-account.json\"},
                {\"name\": \"IPFS_API_URL\", \"value\": \"$ipfs_api\"},
                {\"name\": \"IPFS_GATEWAY_URL\", \"value\": \"https://ipfs.io/ipfs/\"},
                {\"name\": \"POLL_INTERVAL_SECONDS\", \"value\": \"10\"}
            ],
            \"logConfiguration\": {
                \"logDriver\": \"awslogs\",
                \"options\": {
                    \"awslogs-group\": \"/ecs/$name\",
                    \"awslogs-region\": \"$AWS_REGION\",
                    \"awslogs-stream-prefix\": \"ecs\"
                }
            }
        }]" \
        --region "$AWS_REGION" > /dev/null
    ok "Task definition: $name"

    # Create or update service
    if aws ecs describe-services --cluster "$AWS_CLUSTER" --services "$name" --region "$AWS_REGION" --query 'services[0].status' --output text 2>/dev/null | grep -q ACTIVE; then
        aws ecs update-service \
            --cluster "$AWS_CLUSTER" \
            --service "$name" \
            --task-definition "$name" \
            --force-new-deployment \
            --region "$AWS_REGION" > /dev/null
    else
        aws ecs create-service \
            --cluster "$AWS_CLUSTER" \
            --service-name "$name" \
            --task-definition "$name" \
            --desired-count 1 \
            --launch-type FARGATE \
            --network-configuration "{
                \"awsvpcConfiguration\": {
                    \"subnets\": [$(echo "$subnets" | sed 's/,/","/g' | sed 's/^/"/;s/$/"/')],
                    \"securityGroups\": [\"$AWS_SG\"],
                    \"assignPublicIp\": \"ENABLED\"
                }
            }" \
            --region "$AWS_REGION" > /dev/null
    fi
    ok "Service deployed: $name"
}

# ==============================================================================
# Main
# ==============================================================================
main() {
    local target="${1:-all}"

    log "IAN Knowledge Management — Cloud Deployment"
    echo "  GCP Project: $GCP_PROJECT"
    echo "  Azure RG:    $AZURE_RG"
    echo "  AWS Region:  $AWS_REGION"
    echo "  Target:      $target"

    mkdir -p "$STAGE_DIR"

    case "$target" in
        gcp)   deploy_gcp ;;
        azure) deploy_azure ;;
        aws)   deploy_aws ;;
        all)
            deploy_gcp
            deploy_azure
            deploy_aws
            ;;
        *)
            echo "Usage: $0 [all|gcp|azure|aws]"
            exit 1
            ;;
    esac

    log "Deployment complete!"
    echo ""
    echo "Cloud Resource IDs:"
    echo "  GCP App Engine:          $GCP_PROJECT.ue.r.appspot.com"
    echo "  GCP Firestore:           projects/$GCP_PROJECT/databases/(default)"
    echo "  Azure Container Reg:     $AZURE_ACR.azurecr.io"
    echo "  Azure Container Inst:    $AZURE_LLM_CONTAINER (RG: $AZURE_RG)"
    echo "  AWS ECR:                 ${AWS_ACCOUNT_ID}.dkr.ecr.$AWS_REGION.amazonaws.com"
    echo "  AWS ECS Cluster:         $AWS_CLUSTER"
    echo "  AWS ECS Services:        ian-orchestrator, ian-library-worker"
    echo ""

    # Cleanup staging
    rm -rf "$STAGE_DIR"
}

main "$@"
