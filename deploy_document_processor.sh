#!/bin/bash
# Deploy script for the Document Processing component of the Email Intelligence System

# Exit on error
set -e

# Default variables
PROJECT_ID=$(gcloud config get-value project)
REGION="us-central1"
SERVICE_ACCOUNT=""
INPUT_BUCKET="email-intelligence-input"
OUTPUT_BUCKET="email-intelligence-processed"
BQ_DATASET="email_intelligence"
BQ_RAG_TABLE="rag_chunks"

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
    --dataset)
      BQ_DATASET="$2"
      shift 2
      ;;
    --rag-table)
      BQ_RAG_TABLE="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

echo "🚀 Deploying Document Processing components..."
echo "Project ID: $PROJECT_ID"
echo "Region: $REGION"
echo "Input Bucket: $INPUT_BUCKET"
echo "Output Bucket: $OUTPUT_BUCKET"
echo "BigQuery Dataset: $BQ_DATASET"
echo "RAG Table: $BQ_RAG_TABLE"

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

# Create necessary folders in the input bucket
echo "Creating directory structure in input bucket..."
touch /tmp/empty_file
gsutil cp /tmp/empty_file gs://${INPUT_BUCKET}/pdf/.keep
gsutil cp /tmp/empty_file gs://${INPUT_BUCKET}/excel/.keep
gsutil cp /tmp/empty_file gs://${INPUT_BUCKET}/text/.keep

# Create necessary folders in the output bucket
echo "Creating directory structure in output bucket..."
gsutil cp /tmp/empty_file gs://${OUTPUT_BUCKET}/processed/.keep
gsutil cp /tmp/empty_file gs://${OUTPUT_BUCKET}/failed/.keep
rm /tmp/empty_file

# Make sure BigQuery dataset exists
echo "🗂️ Checking BigQuery dataset..."
if ! bq ls --project_id=$PROJECT_ID "$BQ_DATASET" &>/dev/null; then
  echo "Creating dataset $BQ_DATASET"
  bq --location=$REGION mk \
    --dataset \
    --description="Dataset for Email Intelligence System" \
    "${PROJECT_ID}:${BQ_DATASET}"
else
  echo "Dataset $BQ_DATASET already exists"
fi

# Create or update the RAG table schema
echo "📊 Setting up RAG table schema..."
# Using a temporary JSON schema file
cat > /tmp/rag_schema.json << EOF
[
  {
    "name": "chunk_id",
    "type": "STRING",
    "mode": "REQUIRED",
    "description": "Unique identifier for the chunk"
  },
  {
    "name": "document_path",
    "type": "STRING",
    "mode": "REQUIRED",
    "description": "Path to the source document in Cloud Storage"
  },
  {
    "name": "event_id",
    "type": "STRING",
    "mode": "REQUIRED",
    "description": "ID of the event that triggered processing"
  },
  {
    "name": "time_processed",
    "type": "TIMESTAMP",
    "mode": "REQUIRED",
    "description": "When the chunk was processed"
  },
  {
    "name": "text_chunk",
    "type": "STRING",
    "mode": "REQUIRED",
    "description": "The actual text content of the chunk"
  },
  {
    "name": "vector_embedding",
    "type": "FLOAT64",
    "mode": "REPEATED",
    "description": "Vector embedding of the text chunk"
  },
  {
    "name": "metadata",
    "type": "JSON",
    "mode": "NULLABLE",
    "description": "Additional metadata about the chunk"
  },
  {
    "name": "questions",
    "type": "STRING",
    "mode": "REPEATED",
    "description": "Sample questions this chunk can answer"
  },
  {
    "name": "answers",
    "type": "STRING",
    "mode": "REPEATED",
    "description": "Answers to the sample questions"
  },
  {
    "name": "category",
    "type": "STRING",
    "mode": "NULLABLE",
    "description": "Category or topic of the chunk"
  },
  {
    "name": "keywords",
    "type": "STRING",
    "mode": "REPEATED",
    "description": "Important keywords from the chunk"
  }
]
EOF

# Check if table exists, create it if it doesn't
if ! bq ls --project_id=$PROJECT_ID "${BQ_DATASET}.${BQ_RAG_TABLE}" &>/dev/null; then
  echo "Creating table ${BQ_RAG_TABLE}"
  bq mk \
    --table \
    --clustering_fields="category" \
    --description="RAG chunks for document search and retrieval" \
    "${PROJECT_ID}:${BQ_DATASET}.${BQ_RAG_TABLE}" \
    /tmp/rag_schema.json
else
  echo "Table ${BQ_RAG_TABLE} already exists, updating schema"
  bq update \
    --clustering_fields="category" \
    "${PROJECT_ID}:${BQ_DATASET}.${BQ_RAG_TABLE}" \
    /tmp/rag_schema.json
fi

# Clean up temp file
rm /tmp/rag_schema.json

# Deploy the Cloud Function for document processing
echo "☁️ Deploying Cloud Function for document processing..."
gcloud functions deploy document-processor \
  --gen2 \
  --runtime=python311 \
  --region=$REGION \
  --source=./document_processing \
  --entry-point=process_document \
  --trigger-event-filters="type=google.cloud.storage.object.v1.finalized" \
  --trigger-event-filters="bucket=${INPUT_BUCKET}" \
  --service-account=$SERVICE_ACCOUNT \
  --timeout=540s \
  --memory=2048MB \
  --set-env-vars="PROJECT_ID=${PROJECT_ID},OUTPUT_BUCKET=${OUTPUT_BUCKET},BQ_DATASET=${BQ_DATASET},BQ_RAG_TABLE=${BQ_RAG_TABLE}"

echo "✅ Document Processing deployment complete!"
echo ""
echo "To use the document processing system:"
echo "1. Upload files to the input bucket:"
echo "   - PDF files: gs://${INPUT_BUCKET}/pdf/"
echo "   - Excel files: gs://${INPUT_BUCKET}/excel/"
echo "   - Text files: gs://${INPUT_BUCKET}/text/"
echo ""
echo "2. Processed results will be available in:"
echo "   gs://${OUTPUT_BUCKET}/processed/"
echo ""
echo "3. To manually test PDF processing:"
echo "   python document_processing/pdf_processor.py --bucket ${INPUT_BUCKET} --file pdf/your_document.pdf --project ${PROJECT_ID} --output-bucket ${OUTPUT_BUCKET}"
echo ""
echo "4. To manually test Excel processing:"
echo "   python document_processing/excel_processor.py --bucket ${INPUT_BUCKET} --file excel/your_spreadsheet.xlsx --project ${PROJECT_ID} --output-bucket ${OUTPUT_BUCKET}"