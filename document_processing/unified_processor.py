"""
Unified document processor for the Email Intelligence System.
Handles multiple document types (PDF, Excel, Text) and integrates with the RAG system.
"""

import os
import json
import uuid
import mimetypes
from datetime import datetime
from typing import Dict, Any, Optional, List

from google.cloud import storage, bigquery
import vertexai
from vertexai.preview.language_models import TextEmbeddingModel

# Import document type processors
try:
    from pdf_processor import PDFProcessor
    from excel_processor import ExcelProcessor
except ImportError:
    # Adjust path for Cloud Functions
    from document_processing.pdf_processor import PDFProcessor
    from document_processing.excel_processor import ExcelProcessor


class UnifiedDocumentProcessor:
    """Processes various document types and prepares them for RAG."""
    
    def __init__(
        self, 
        project_id: str, 
        output_bucket: str,
        bq_dataset: str = None,
        bq_table: str = None,
        embedding_model_name: str = "text-embedding-004",
        vertex_location: str = "us-central1"
    ):
        """Initialize the unified document processor.
        
        Args:
            project_id: Google Cloud project ID
            output_bucket: GCS bucket to store processed results
            bq_dataset: BigQuery dataset for RAG chunks
            bq_table: BigQuery table for RAG chunks
            embedding_model_name: Vertex AI embedding model name
            vertex_location: Vertex AI location
        """
        self.project_id = project_id
        self.output_bucket = output_bucket
        self.bq_dataset = bq_dataset
        self.bq_table = bq_table
        self.embedding_model_name = embedding_model_name
        
        # Initialize clients
        self.storage_client = storage.Client(project=project_id)
        
        # Initialize BigQuery client if dataset and table are provided
        self.bq_client = None
        if bq_dataset and bq_table:
            self.bq_client = bigquery.Client(project=project_id)
        
        # Initialize Vertex AI
        vertexai.init(project=project_id, location=vertex_location)
        
        # Initialize document processors
        self.pdf_processor = PDFProcessor(project_id, output_bucket)
        self.excel_processor = ExcelProcessor(project_id, output_bucket)
    
    def process_document(self, bucket_name: str, filename: str, event_id: str) -> Dict[str, Any]:
        """Process a document based on its file type.
        
        Args:
            bucket_name: Name of the GCS bucket containing the document
            filename: Name of the document file to process
            event_id: ID of the event that triggered processing
            
        Returns:
            Dictionary containing processing results and metadata
        """
        print(f"Processing document: {filename}")
        
        # Determine file type
        file_ext = os.path.splitext(filename)[1].lower()
        mime_type, _ = mimetypes.guess_type(filename)
        
        # Process based on file type
        if file_ext == '.pdf' or (mime_type and mime_type == 'application/pdf'):
            result = self.pdf_processor.process_pdf(bucket_name, filename, event_id)
            text_content = self._extract_text_from_pdf_result(result)
        
        elif file_ext in ['.xlsx', '.xls'] or (mime_type and mime_type in ['application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet']):
            result = self.excel_processor.process_excel(bucket_name, filename, event_id)
            text_content = self._extract_text_from_excel_result(result)
        
        else:
            # Default to text file processing
            text_content = self._process_text_file(bucket_name, filename)
            result = {
                "filename": filename,
                "source_bucket": bucket_name,
                "event_id": event_id,
                "processing_time": datetime.now().isoformat(),
                "document_type": "text",
                "text_content": text_content,
                "status": "success"
            }
        
        # Update processing status in result
        result["rag_processing"] = False
        
        # Process for RAG if BigQuery information is available
        if self.bq_client and self.bq_dataset and self.bq_table:
            try:
                # Process for RAG
                rag_results = self._process_for_rag(text_content, filename, event_id)
                
                # Update result with RAG processing status
                result["rag_processing"] = True
                result["rag_chunk_count"] = len(rag_results)
                
                # Save RAG results to output bucket
                self._save_rag_results(rag_results, filename)
            
            except Exception as e:
                print(f"Error processing for RAG: {e}")
                result["rag_processing_error"] = str(e)
        
        return result
    
    def _extract_text_from_pdf_result(self, pdf_result: Dict[str, Any]) -> str:
        """Extract plain text from PDF processing result.
        
        Args:
            pdf_result: Result from PDF processor
            
        Returns:
            Concatenated text content
        """
        text_content = pdf_result.get("text_content", [])
        
        if isinstance(text_content, list):
            return "\n\n".join(text_content)
        elif isinstance(text_content, str):
            return text_content
        else:
            return ""
    
    def _extract_text_from_excel_result(self, excel_result: Dict[str, Any]) -> str:
        """Extract plain text representation from Excel processing result.
        
        Args:
            excel_result: Result from Excel processor
            
        Returns:
            Textual representation of Excel data
        """
        texts = []
        
        # Process each sheet
        for sheet in excel_result.get("sheets", []):
            sheet_name = sheet.get("name", "Unknown Sheet")
            texts.append(f"Sheet: {sheet_name}")
            
            # Add column headers
            if sheet.get("columns"):
                texts.append("Columns: " + ", ".join(sheet.get("columns")))
            
            # Add data summaries for each column
            for column, info in sheet.get("column_info", {}).items():
                col_summary = f"Column: {column}, Type: {info.get('type', 'unknown')}"
                
                if "min" in info and "max" in info and info["min"] is not None and info["max"] is not None:
                    col_summary += f", Range: {info['min']} to {info['max']}"
                
                if "unique_count" in info:
                    col_summary += f", Unique values: {info['unique_count']}"
                
                texts.append(col_summary)
            
            # Add sample data (first 10 rows)
            texts.append("Sample Data:")
            
            for i, record in enumerate(sheet.get("data", [])[:10]):
                record_str = ", ".join([f"{k}: {v}" for k, v in record.items()])
                texts.append(f"Row {i+1}: {record_str}")
            
            texts.append("")  # Empty line between sheets
        
        return "\n".join(texts)
    
    def _process_text_file(self, bucket_name: str, filename: str) -> str:
        """Process a plain text file.
        
        Args:
            bucket_name: Name of the GCS bucket containing the text file
            filename: Name of the text file to process
            
        Returns:
            Text content of the file
        """
        try:
            bucket = self.storage_client.bucket(bucket_name)
            blob = bucket.blob(filename)
            return blob.download_as_text()
        except Exception as e:
            print(f"Error reading text file: {e}")
            return f"Error: {e}"
    
    def _process_for_rag(self, text_content: str, filename: str, event_id: str) -> List[Dict[str, Any]]:
        """Process document text for RAG system.
        
        Args:
            text_content: Extracted text content
            filename: Original filename
            event_id: Processing event ID
            
        Returns:
            List of RAG chunk dictionaries
        """
        # Import here to avoid circular imports
        try:
            from process_text import chunk_text, extract_keywords, determine_category, generate_qa_pairs
        except ImportError:
            # Adjust for Cloud Functions
            from cloud_rag_webhook.process_text import chunk_text, extract_keywords, determine_category, generate_qa_pairs
        
        # Chunk the text
        chunks = chunk_text(text_content)
        print(f"Created {len(chunks)} chunks for RAG processing")
        
        # Get embedding model
        embedding_model = TextEmbeddingModel.from_pretrained(self.embedding_model_name)
        
        # Process each chunk
        rag_chunks = []
        document_path = f"gs://{self.output_bucket}/{filename}"
        
        for i, chunk in enumerate(chunks):
            print(f"Processing RAG chunk {i+1}/{len(chunks)}")
            
            # Generate embeddings
            embedding = embedding_model.get_embeddings([chunk])[0].values
            
            # Generate questions and answers
            qa_pairs = generate_qa_pairs(chunk)
            
            # Extract keywords
            keywords = extract_keywords(chunk)
            
            # Determine category
            category = determine_category(chunk)
            
            # Create a unique ID for this chunk
            chunk_id = str(uuid.uuid4())
            
            # Create RAG chunk entry
            rag_chunk = {
                "chunk_id": chunk_id,
                "document_path": document_path,
                "event_id": event_id,
                "time_processed": datetime.now(),
                "text_chunk": chunk,
                "vector_embedding": embedding,
                "metadata": {"source": filename, "chunk_number": i, "chunk_total": len(chunks)},
                "questions": [qa["question"] for qa in qa_pairs],
                "answers": [qa["answer"] for qa in qa_pairs],
                "category": category,
                "keywords": keywords
            }
            
            rag_chunks.append(rag_chunk)
            
            # Write to BigQuery (if we have more than 5 chunks, write in batches)
            if len(rag_chunks) >= 5:
                self._write_rag_to_bigquery(rag_chunks)
                rag_chunks = []
        
        # Write any remaining chunks
        if rag_chunks:
            self._write_rag_to_bigquery(rag_chunks)
        
        return rag_chunks
    
    def _write_rag_to_bigquery(self, chunks: List[Dict[str, Any]]) -> None:
        """Write RAG chunks to BigQuery.
        
        Args:
            chunks: List of RAG chunk dictionaries
        """
        try:
            from process_text import write_rag_to_bigquery
        except ImportError:
            # Adjust for Cloud Functions
            from cloud_rag_webhook.process_text import write_rag_to_bigquery
        
        write_rag_to_bigquery(chunks, self.bq_dataset, self.bq_table, self.project_id)
    
    def _save_rag_results(self, rag_results: List[Dict[str, Any]], original_filename: str) -> None:
        """Save RAG processing results to GCS.
        
        Args:
            rag_results: List of RAG chunk dictionaries
            original_filename: Name of the original file
        """
        try:
            # Create a dictionary to hold all RAG chunks
            result = {
                "filename": original_filename,
                "processing_time": datetime.now().isoformat(),
                "chunk_count": len(rag_results),
                "rag_chunks": [
                    {
                        "chunk_id": chunk["chunk_id"],
                        "text_chunk": chunk["text_chunk"],
                        "category": chunk["category"],
                        "keywords": chunk["keywords"],
                        "questions": chunk["questions"],
                        "answers": chunk["answers"]
                    }
                    for chunk in rag_results
                ]
            }
            
            # Create JSON blob
            bucket = self.storage_client.bucket(self.output_bucket)
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            result_filename = f"{os.path.splitext(original_filename)[0]}-rag-{timestamp}.json"
            blob = bucket.blob(f"processed/{result_filename}")
            
            # Upload JSON result (without embeddings to save space)
            blob.upload_from_string(
                json.dumps(result, indent=2),
                content_type="application/json"
            )
            
            print(f"Saved RAG results to gs://{self.output_bucket}/processed/{result_filename}")
            
        except Exception as e:
            print(f"Error saving RAG results to GCS: {e}")


def process_document_entry(event: Dict[str, Any], context) -> Optional[Dict[str, Any]]:
    """Cloud Function entry point for document processing.
    
    Args:
        event: Cloud Functions event payload
        context: Event context
        
    Returns:
        Processing result or None if error
    """
    try:
        # Extract information from the event
        bucket_name = event["bucket"]
        filename = event["name"]
        event_id = context.event_id
        
        # Get project ID from environment or default
        project_id = os.environ.get("PROJECT_ID")
        if not project_id:
            # Try to get from context
            project_id = context.resource.get("projects", None)
            if not project_id:
                raise ValueError("PROJECT_ID environment variable not set")
        
        # Get configuration from environment variables
        output_bucket = os.environ.get("OUTPUT_BUCKET", f"{bucket_name}-processed")
        bq_dataset = os.environ.get("BQ_DATASET")
        bq_table = os.environ.get("BQ_RAG_TABLE")
        
        # Process the document
        processor = UnifiedDocumentProcessor(
            project_id=project_id,
            output_bucket=output_bucket,
            bq_dataset=bq_dataset,
            bq_table=bq_table
        )
        
        result = processor.process_document(bucket_name, filename, event_id)
        
        return result
        
    except Exception as e:
        print(f"Error in document processing function: {e}")
        return None


if __name__ == "__main__":
    # For local testing
    import argparse
    
    parser = argparse.ArgumentParser(description="Process a document file")
    parser.add_argument("--bucket", required=True, help="Source GCS bucket")
    parser.add_argument("--file", required=True, help="Document filename")
    parser.add_argument("--project", required=True, help="Google Cloud project ID")
    parser.add_argument("--output-bucket", help="Output GCS bucket")
    parser.add_argument("--bq-dataset", help="BigQuery dataset for RAG")
    parser.add_argument("--bq-table", help="BigQuery table for RAG")
    
    args = parser.parse_args()
    
    # Create mock event and context
    mock_event = {
        "bucket": args.bucket,
        "name": args.file
    }
    
    class MockContext:
        def __init__(self, event_id):
            self.event_id = event_id
            self.resource = {"projects": args.project}
    
    mock_context = MockContext(f"local-test-{uuid.uuid4().hex}")
    
    # Set environment variables
    os.environ["PROJECT_ID"] = args.project
    if args.output_bucket:
        os.environ["OUTPUT_BUCKET"] = args.output_bucket
    if args.bq_dataset:
        os.environ["BQ_DATASET"] = args.bq_dataset
    if args.bq_table:
        os.environ["BQ_RAG_TABLE"] = args.bq_table
    
    # Process the document
    result = process_document_entry(mock_event, mock_context)
    
    if result:
        print(f"Successfully processed document: {result['filename']}")
        if result.get("rag_processing", False):
            print(f"Document processed for RAG with {result.get('rag_chunk_count', 0)} chunks")
        else:
            print("Document was not processed for RAG")
    else:
        print("Failed to process document")