#!/bin/bash
# Deployment script for Email Intelligence Dashboard

# Exit on error
set -e

# Default variables
PROJECT_ID=$(gcloud config get-value project)
REGION="us-central1"
SERVICE_NAME="email-intelligence-dashboard"
MIN_INSTANCES=1
MAX_INSTANCES=3
MEMORY="1Gi"

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
    --service-name)
      SERVICE_NAME="$2"
      shift 2
      ;;
    --min-instances)
      MIN_INSTANCES="$2"
      shift 2
      ;;
    --max-instances)
      MAX_INSTANCES="$2"
      shift 2
      ;;
    --memory)
      MEMORY="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

echo "🌟 Deploying Email Intelligence Dashboard..."
echo "Project ID: $PROJECT_ID"
echo "Region: $REGION"
echo "Service Name: $SERVICE_NAME"
echo "Min Instances: $MIN_INSTANCES"
echo "Max Instances: $MAX_INSTANCES"
echo "Memory: $MEMORY"

# Move to dashboard directory
cd "$(dirname "$0")/dashboard"

# Copy test script to dashboard directory
cp ../test_email_intelligence.py .

# Enable required services
echo "🔧 Enabling required services..."
gcloud services enable cloudbuild.googleapis.com --project=$PROJECT_ID
gcloud services enable run.googleapis.com --project=$PROJECT_ID

# Build and deploy to Cloud Run
echo "🔧 Building and deploying to Cloud Run..."
gcloud builds submit --tag gcr.io/$PROJECT_ID/$SERVICE_NAME

gcloud run deploy $SERVICE_NAME \
  --image gcr.io/$PROJECT_ID/$SERVICE_NAME \
  --platform managed \
  --region $REGION \
  --memory $MEMORY \
  --min-instances $MIN_INSTANCES \
  --max-instances $MAX_INSTANCES \
  --allow-unauthenticated \
  --project $PROJECT_ID

# Clean up
rm -f test_email_intelligence.py

# Get the deployed URL
DASHBOARD_URL=$(gcloud run services describe $SERVICE_NAME --platform managed --region $REGION --format="value(status.url)" --project $PROJECT_ID)

echo ""
echo "✅ Email Intelligence Dashboard deployed successfully!"
echo "Dashboard URL: $DASHBOARD_URL"
echo ""
echo "To update API connection URL:"
echo "1. Open the dashboard at $DASHBOARD_URL"
echo "2. Update the API URL in the sidebar with the URL of your email-processor API"