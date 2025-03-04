#!/bin/bash
# Master deployment script for the Email Intelligence System

# Exit on error
set -e

# Default variables
PROJECT_ID=$(gcloud config get-value project)
REGION="us-central1"
SERVICE_ACCOUNT=""
INPUT_BUCKET="email-intelligence-input"
PROCESSED_BUCKET="email-intelligence-processed"
KNOWLEDGE_BUCKET="email-intelligence-knowledge"
BQ_DATASET="email_intelligence"
BQ_RAG_TABLE="rag_chunks"
SERVICE_NAME="email-intelligence-dashboard"

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
    --input-bucket)
      INPUT_BUCKET="$2"
      shift 2
      ;;
    --processed-bucket)
      PROCESSED_BUCKET="$2"
      shift 2
      ;;
    --knowledge-bucket)
      KNOWLEDGE_BUCKET="$2"
      shift 2
      ;;
    --dataset)
      BQ_DATASET="$2"
      shift 2
      ;;
    --rag-table)
      BQ_RAG_TABLE="$2"
      shift 2
      ;;
    --dashboard-name)
      SERVICE_NAME="$2"
      shift 2
      ;;
    --skip-document-processor)
      SKIP_DOCUMENT_PROCESSOR=true
      shift
      ;;
    --skip-knowledge-base)
      SKIP_KNOWLEDGE_BASE=true
      shift
      ;;
    --skip-email-connector)
      SKIP_EMAIL_CONNECTOR=true
      shift
      ;;
    --skip-dashboard)
      SKIP_DASHBOARD=true
      shift
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

echo "🌟 Deploying Email Intelligence System..."
echo "Project ID: $PROJECT_ID"
echo "Region: $REGION"
echo "Input Bucket: $INPUT_BUCKET"
echo "Processed Bucket: $PROCESSED_BUCKET"
echo "Knowledge Bucket: $KNOWLEDGE_BUCKET"
echo "BigQuery Dataset: $BQ_DATASET"
echo "RAG Table: $BQ_RAG_TABLE"
echo "Dashboard Name: $SERVICE_NAME"

# Check if service account is provided
if [ -z "$SERVICE_ACCOUNT" ]; then
  echo "⚠️ No service account provided, using default compute service account"
  SERVICE_ACCOUNT="$(gcloud iam service-accounts list --filter="name:compute" --format="value(email)" --limit=1)"
fi
echo "Service Account: $SERVICE_ACCOUNT"

# Check for Microsoft Graph API credentials if email connector is not skipped
if [ -z "$SKIP_EMAIL_CONNECTOR" ]; then
  if [ -z "$MS_TENANT_ID" ] || [ -z "$MS_CLIENT_ID" ] || [ -z "$MS_CLIENT_SECRET" ]; then
    echo "⚠️ Microsoft Graph API credentials not found in environment variables"
    echo "Email connector deployment will be skipped"
    SKIP_EMAIL_CONNECTOR=true
  fi
fi

# Make scripts executable
chmod +x ./deploy_document_processor.sh
chmod +x ./deploy_knowledge_base.sh
chmod +x ./deploy_email_connector.sh
chmod +x ./deploy_dashboard.sh

# Step 1: Deploy the document processor component
if [ -z "$SKIP_DOCUMENT_PROCESSOR" ]; then
  echo ""
  echo "🔧 Deploying Document Processor component..."
  ./deploy_document_processor.sh \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --service-account "$SERVICE_ACCOUNT" \
    --input-bucket "$INPUT_BUCKET" \
    --output-bucket "$PROCESSED_BUCKET" \
    --dataset "$BQ_DATASET" \
    --rag-table "$BQ_RAG_TABLE"
else
  echo "ℹ️ Skipping Document Processor deployment"
fi

# Step 2: Deploy the knowledge base component
if [ -z "$SKIP_KNOWLEDGE_BASE" ]; then
  echo ""
  echo "🔧 Deploying Knowledge Base component..."
  ./deploy_knowledge_base.sh \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --service-account "$SERVICE_ACCOUNT" \
    --input-bucket "$PROCESSED_BUCKET" \
    --output-bucket "$KNOWLEDGE_BUCKET"
  
  # Get the knowledge base API URL for the email connector
  KB_API_URL=$(gcloud functions describe knowledge-document-processor --region=$REGION --format="value(serviceConfig.uri)" 2>/dev/null || echo "")
else
  echo "ℹ️ Skipping Knowledge Base deployment"
  KB_API_URL=""
fi

# Step 3: Deploy the email connector component
if [ -z "$SKIP_EMAIL_CONNECTOR" ]; then
  echo ""
  echo "🔧 Deploying Email Connector component..."
  ./deploy_email_connector.sh \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --service-account "$SERVICE_ACCOUNT" \
    --knowledge-bucket "$KNOWLEDGE_BUCKET" \
    --kb-api-url "$KB_API_URL"
  
  # Get the email processor API URL for the dashboard
  EMAIL_API_URL=$(gcloud functions describe email-processor --region=$REGION --format="value(serviceConfig.uri)" 2>/dev/null || echo "")
else
  echo "ℹ️ Skipping Email Connector deployment"
  EMAIL_API_URL=""
fi

# Step 4: Deploy the dashboard component
if [ -z "$SKIP_DASHBOARD" ]; then
  echo ""
  echo "🔧 Deploying Dashboard component..."
  ./deploy_dashboard.sh \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --service-name "$SERVICE_NAME"
else
  echo "ℹ️ Skipping Dashboard deployment"
fi

# Get URLs for deployed components
DOCUMENT_PROCESSOR_URL=$(gcloud functions describe document-processor --region=$REGION --format="value(serviceConfig.uri)" 2>/dev/null || echo "Not deployed")
KNOWLEDGE_PROCESSOR_URL=$(gcloud functions describe knowledge-document-processor --region=$REGION --format="value(serviceConfig.uri)" 2>/dev/null || echo "Not deployed")
EMAIL_PROCESSOR_URL=$(gcloud functions describe email-processor --region=$REGION --format="value(serviceConfig.uri)" 2>/dev/null || echo "Not deployed")
DASHBOARD_URL=$(gcloud run services describe $SERVICE_NAME --platform managed --region $REGION --format="value(status.url)" 2>/dev/null || echo "Not deployed")

echo ""
echo "✅ Email Intelligence System deployment complete!"
echo ""
echo "System Architecture:"
echo "📝 Document Processing:"
echo "  1. Upload files to gs://$INPUT_BUCKET/"
echo "  2. Cloud Function processes and stores results in gs://$PROCESSED_BUCKET/"
echo "  3. Document chunks are stored in BigQuery: $PROJECT_ID.$BQ_DATASET.$BQ_RAG_TABLE"
echo "  4. API: $DOCUMENT_PROCESSOR_URL"
echo ""
echo "🧠 Knowledge Base:"
echo "  1. Processes documents from gs://$PROCESSED_BUCKET/"
echo "  2. Extracts entities and relationships"
echo "  3. Stores knowledge in gs://$KNOWLEDGE_BUCKET/"
echo "  4. API: $KNOWLEDGE_PROCESSOR_URL"
echo ""
echo "📧 Email Connector:"
echo "  1. Connects to Microsoft 365 via Graph API"
echo "  2. Retrieves and prioritizes emails using the knowledge base"
echo "  3. API: $EMAIL_PROCESSOR_URL"
echo ""
echo "📊 Dashboard:"
echo "  1. Visualizes prioritized emails and knowledge entities"
echo "  2. Provides a user-friendly interface for the system"
echo "  3. URL: $DASHBOARD_URL"
echo ""
echo "To get started:"
echo "1. Upload documents to gs://$INPUT_BUCKET/ to build your knowledge base"
echo "2. Process existing documents with: curl -X POST $(gcloud functions describe knowledge-batch-processor --region=$REGION --format="value(serviceConfig.uri)" 2>/dev/null || echo "API_URL") -H \"Content-Type: application/json\" -d '{\"prefix\":\"processed/\"}'"
echo "3. Query emails with: curl -X POST $EMAIL_PROCESSOR_URL -H \"Content-Type: application/json\" -d '{\"days\": 7, \"min_priority\": 0.5}'"
echo "4. Access the dashboard at: $DASHBOARD_URL"