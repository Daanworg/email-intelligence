#!/bin/bash
# Deploy script for the Email Connector component of the Email Intelligence System

# Exit on error
set -e

# Default variables
PROJECT_ID=$(gcloud config get-value project)
REGION="us-central1"
SERVICE_ACCOUNT=""
KNOWLEDGE_BUCKET="email-intelligence-knowledge"
KB_API_URL=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --project)
      PROJECT_ID="$2"
      shift 2
      ;;
    --region)
      REGION="$2"
      shift 2
      ;;
    --service-account)
      SERVICE_ACCOUNT="$2"
      shift 2
      ;;
    --knowledge-bucket)
      KNOWLEDGE_BUCKET="$2"
      shift 2
      ;;
    --kb-api-url)
      KB_API_URL="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

echo "🚀 Deploying Email Connector components..."
echo "Project ID: $PROJECT_ID"
echo "Region: $REGION"
echo "Knowledge Bucket: $KNOWLEDGE_BUCKET"

# Check if service account is provided
if [ -z "$SERVICE_ACCOUNT" ]; then
  echo "⚠️ No service account provided, using default compute service account"
  SERVICE_ACCOUNT="$(gcloud iam service-accounts list --filter="name:compute" --format="value(email)" --limit=1)"
fi
echo "Service Account: $SERVICE_ACCOUNT"

# Check for Microsoft Graph API credentials
if [ -z "$MS_TENANT_ID" ] || [ -z "$MS_CLIENT_ID" ] || [ -z "$MS_CLIENT_SECRET" ]; then
  echo "⚠️ Microsoft Graph API credentials not found in environment variables"
  echo "Please set MS_TENANT_ID, MS_CLIENT_ID, and MS_CLIENT_SECRET before deploying"
  exit 1
fi

# Check for knowledge base API URL
if [ -z "$KB_API_URL" ]; then
  # Try to get the URL for the knowledge base API
  echo "Checking for knowledge base API URL..."
  KB_API_URL=$(gcloud functions describe knowledge-document-processor --region=$REGION --format="value(serviceConfig.uri)" 2>/dev/null || echo "")
  if [ -z "$KB_API_URL" ]; then
    echo "⚠️ No knowledge base API URL provided or found"
    echo "Email intelligence will operate with reduced functionality"
  else
    echo "Found knowledge base API: $KB_API_URL"
  fi
fi

# Deploy the Cloud Function for email processing
echo "☁️ Deploying Cloud Function for email processing..."
gcloud functions deploy email-processor \
  --gen2 \
  --runtime=python311 \
  --region=$REGION \
  --source=./email_connector \
  --entry-point=process_email_request \
  --trigger-http \
  --allow-unauthenticated \
  --timeout=60s \
  --memory=512MB \
  --service-account=$SERVICE_ACCOUNT \
  --set-env-vars="PROJECT_ID=${PROJECT_ID},KNOWLEDGE_BUCKET=${KNOWLEDGE_BUCKET},KB_API_URL=${KB_API_URL},MS_TENANT_ID=${MS_TENANT_ID},MS_CLIENT_ID=${MS_CLIENT_ID},MS_CLIENT_SECRET=${MS_CLIENT_SECRET}"

echo "✅ Email Connector deployment complete!"
echo ""
echo "To use the email processor API:"
echo "curl -X POST $(gcloud functions describe email-processor --region=${REGION} --format='value(serviceConfig.uri)') -H \"Content-Type: application/json\" -d '{\"days\": 7, \"folder\": \"inbox\", \"top\": 10, \"min_priority\": 0.5}'"
echo ""
echo "To test locally:"
echo "python email_connector/email_processor.py --project ${PROJECT_ID} --knowledge-bucket ${KNOWLEDGE_BUCKET} --kb-api-url \"${KB_API_URL}\" --days 7 --count 10 --min-priority 0.5"