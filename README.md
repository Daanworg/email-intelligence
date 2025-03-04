# Email Intelligence System

A comprehensive system that integrates document processing, knowledge extraction, and email prioritization using Google Cloud Platform.

## System Architecture

The system consists of four main components:

### 1. Document Processing

Enhanced document processor that extracts text and structured data from:
- PDF files (OCR using Cloud Vision API)
- Excel spreadsheets (structured data extraction)
- Plain text files

Files are processed, chunked, and stored in BigQuery for semantic search capabilities.

### 2. Knowledge Base

Processes documents to extract:
- Entities (people, projects, technical terms)
- Relationships between entities
- Context and relevance information

Stores vector embeddings and provides a REST API for querying the knowledge base.

### 3. Email Connector

Connects with Microsoft 365 via Microsoft Graph API to:
- Retrieve emails and conversation threads
- Process email content using the knowledge base
- Prioritize messages based on relevance, urgency, and context
- Provide a unified API for email intelligence

### 4. Dashboard

Interactive web dashboard for visualizing prioritized emails:
- View email priority scores and distribution
- Filter by time period and minimum priority
- See email details including entity extraction
- Track priority reasons for each message
- Perform common actions like document processing and email syncing

## Deployment

### Prerequisites

1. Google Cloud Platform account with billing enabled
2. Google Cloud CLI installed and configured
3. Microsoft 365 account with appropriate permissions
4. Microsoft Graph API application registered in Azure

### Microsoft Graph API Setup

1. Register an application in Azure Active Directory
2. Grant appropriate permissions:
   - Mail.Read
   - Mail.ReadBasic
   - User.Read
3. Create a client secret

### Environment Setup

Set the following environment variables for Microsoft Graph API authentication:

```bash
export MS_TENANT_ID="your-tenant-id"
export MS_CLIENT_ID="your-client-id"
export MS_CLIENT_SECRET="your-client-secret"
export MS_USER_EMAIL="target-user@example.com"  # Optional, for delegate access
```

### Full System Deployment

```bash
./deploy_all.sh --project YOUR_PROJECT_ID --region REGION
```

### Component-Specific Deployment

You can deploy individual components as needed:

```bash
# Document Processor
./deploy_document_processor.sh --project YOUR_PROJECT_ID --region REGION

# Knowledge Base
./deploy_knowledge_base.sh --project YOUR_PROJECT_ID --region REGION

# Email Connector
./deploy_email_connector.sh --project YOUR_PROJECT_ID --region REGION

# Dashboard
./deploy_dashboard.sh --project YOUR_PROJECT_ID --region REGION
```

## Usage

### Document Processing

Upload files to the appropriate Google Cloud Storage bucket:

```bash
# PDF files
gsutil cp your-file.pdf gs://email-intelligence-input/pdf/

# Excel files
gsutil cp your-file.xlsx gs://email-intelligence-input/excel/

# Text files
gsutil cp your-file.txt gs://email-intelligence-input/text/
```

### Knowledge Base

Process all documents in the processed bucket:

```bash
curl -X POST https://REGION-YOUR_PROJECT_ID.cloudfunctions.net/knowledge-batch-processor \
  -H "Content-Type: application/json" \
  -d '{"prefix":"processed/"}'
```

### Email Intelligence

Query prioritized emails:

```bash
curl -X POST https://REGION-YOUR_PROJECT_ID.cloudfunctions.net/email-processor \
  -H "Content-Type: application/json" \
  -d '{
    "days": 7, 
    "folder": "inbox", 
    "top": 20, 
    "min_priority": 0.5
  }'
```

Search emails with prioritization:

```bash
curl -X POST https://REGION-YOUR_PROJECT_ID.cloudfunctions.net/email-processor \
  -H "Content-Type: application/json" \
  -d '{
    "search": "project status", 
    "folder": "inbox", 
    "top": 10, 
    "min_priority": 0
  }'
```

### Dashboard

Access the dashboard through the Cloud Run URL:

```bash
# Get the dashboard URL
gcloud run services describe email-intelligence-dashboard --platform managed --region REGION --format="value(status.url)"
```

The dashboard provides:
- Real-time visualization of priority metrics
- Email timeline view showing priority over time
- Detailed view of each email with priority reasons
- Knowledge context with extracted entities
- Action buttons for common tasks

## Development

### Local Testing

Test components locally before deployment:

```bash
# Document Processing
python document_processing/pdf_processor.py --bucket INPUT_BUCKET --file pdf/your-file.pdf --project PROJECT_ID

# Knowledge Base
python knowledge_base/knowledge_processor.py --project PROJECT_ID --input-bucket PROCESSED_BUCKET --output-bucket KNOWLEDGE_BUCKET --batch

# Email Connector
python email_connector/email_processor.py --project PROJECT_ID --knowledge-bucket KNOWLEDGE_BUCKET --days 7 --count 10

# Dashboard
cd dashboard
pip install -r requirements.txt
streamlit run app.py
```

### Required Python Packages

Each component has its own `requirements.txt` file with appropriate dependencies.

## Hugging Face Deployment

For deploying on Hugging Face:

1. Create a new Hugging Face Space with Docker SDK
2. Enable Dev Mode for VS Code access
3. Clone the repository
4. Set up environment variables in Space secrets for:
   - MS_TENANT_ID
   - MS_CLIENT_ID
   - MS_CLIENT_SECRET
   - PROJECT_ID (for Google Cloud)
   - GOOGLE_APPLICATION_CREDENTIALS (content of JSON key file)
5. Configure Space to always stay running (persistent execution)
6. Point to the dashboard app in your Space configuration

## License

This project is licensed under the Apache License 2.0 - see the LICENSE file for details.