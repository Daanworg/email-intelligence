#!/bin/bash
# Deploy script for the Knowledge Base component of the Email Intelligence System

# Exit on error
set -e

# Default variables
PROJECT_ID=$(gcloud config get-value project)
REGION="us-central1"
SERVICE_ACCOUNT=""
INPUT_BUCKET="email-intelligence-processed"
OUTPUT_BUCKET="email-intelligence-knowledge"

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
    --output-bucket)
      OUTPUT_BUCKET="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

echo "🚀 Deploying Knowledge Base components..."
echo "Project ID: $PROJECT_ID"
echo "Region: $REGION"
echo "Input Bucket: $INPUT_BUCKET"
echo "Output Bucket: $OUTPUT_BUCKET"

# Check if service account is provided
if [ -z "$SERVICE_ACCOUNT" ]; then
  echo "⚠️ No service account provided, using default compute service account"
  SERVICE_ACCOUNT="$(gcloud iam service-accounts list --filter="name:compute" --format="value(email)" --limit=1)"
fi
echo "Service Account: $SERVICE_ACCOUNT"

# Create the buckets if they don't exist
echo "🗂️ Checking Cloud Storage buckets..."

# Create input bucket if it doesn't exist
if ! gsutil ls -b gs://${INPUT_BUCKET} &>/dev/null; then
  echo "Creating input bucket ${INPUT_BUCKET}"
  gsutil mb -p ${PROJECT_ID} -l ${REGION} gs://${INPUT_BUCKET}
else
  echo "Input bucket ${INPUT_BUCKET} already exists"
fi

# Create output bucket if it doesn't exist
if ! gsutil ls -b gs://${OUTPUT_BUCKET} &>/dev/null; then
  echo "Creating output bucket ${OUTPUT_BUCKET}"
  gsutil mb -p ${PROJECT_ID} -l ${REGION} gs://${OUTPUT_BUCKET}
else
  echo "Output bucket ${OUTPUT_BUCKET} already exists"
fi

# Create necessary folders in the output bucket
echo "Creating directory structure in output bucket..."
touch /tmp/empty_file
gsutil cp /tmp/empty_file gs://${OUTPUT_BUCKET}/knowledge/entities/.keep
gsutil cp /tmp/empty_file gs://${OUTPUT_BUCKET}/knowledge/relationships/.keep
gsutil cp /tmp/empty_file gs://${OUTPUT_BUCKET}/knowledge/processing_results/.keep
rm /tmp/empty_file

# Deploy the Cloud Functions for knowledge processing
echo "☁️ Deploying Cloud Functions for knowledge processing..."

# Deploy document processor function
echo "Deploying document processor function..."
gcloud functions deploy knowledge-document-processor \
  --gen2 \
  --runtime=python311 \
  --region=${REGION} \
  --source=./knowledge_base \
  --entry-point=process_document \
  --trigger-http \
  --allow-unauthenticated \
  --timeout=540s \
  --memory=2048MB \
  --service-account=${SERVICE_ACCOUNT} \
  --set-env-vars="PROJECT_ID=${PROJECT_ID},INPUT_BUCKET=${INPUT_BUCKET},OUTPUT_BUCKET=${OUTPUT_BUCKET}"

# Deploy batch processor function
echo "Deploying batch processor function..."
gcloud functions deploy knowledge-batch-processor \
  --gen2 \
  --runtime=python311 \
  --region=${REGION} \
  --source=./knowledge_base \
  --entry-point=process_documents_batch \
  --trigger-http \
  --allow-unauthenticated \
  --timeout=540s \
  --memory=2048MB \
  --service-account=${SERVICE_ACCOUNT} \
  --set-env-vars="PROJECT_ID=${PROJECT_ID},INPUT_BUCKET=${INPUT_BUCKET},OUTPUT_BUCKET=${OUTPUT_BUCKET}"

# Set up a Cloud Scheduler job for daily batch processing
echo "📅 Setting up Cloud Scheduler job for daily batch processing..."
JOB_NAME="daily-knowledge-processing"

# Check if job already exists
if gcloud scheduler jobs describe ${JOB_NAME} --location=${REGION} &>/dev/null; then
  echo "Updating existing scheduler job ${JOB_NAME}"
  gcloud scheduler jobs update http ${JOB_NAME} \
    --location=${REGION} \
    --schedule="0 2 * * *" \
    --uri="$(gcloud functions describe knowledge-batch-processor --region=${REGION} --format='value(serviceConfig.uri)')" \
    --http-method=POST \
    --message-body='{"prefix":"processed/"}' \
    --headers="Content-Type=application/json" \
    --time-zone="UTC"
else
  echo "Creating new scheduler job ${JOB_NAME}"
  gcloud scheduler jobs create http ${JOB_NAME} \
    --location=${REGION} \
    --schedule="0 2 * * *" \
    --uri="$(gcloud functions describe knowledge-batch-processor --region=${REGION} --format='value(serviceConfig.uri)')" \
    --http-method=POST \
    --message-body='{"prefix":"processed/"}' \
    --headers="Content-Type=application/json" \
    --time-zone="UTC"
fi

echo "✅ Knowledge Base deployment complete!"
echo ""
echo "To process a document manually:"
echo "curl -X POST $(gcloud functions describe knowledge-document-processor --region=${REGION} --format='value(serviceConfig.uri)') -H \"Content-Type: application/json\" -d '{\"document_path\":\"gs://${INPUT_BUCKET}/your_document.json\"}'"
echo ""
echo "To trigger batch processing manually:"
echo "curl -X POST $(gcloud functions describe knowledge-batch-processor --region=${REGION} --format='value(serviceConfig.uri)') -H \"Content-Type: application/json\" -d '{\"prefix\":\"processed/\"}'"