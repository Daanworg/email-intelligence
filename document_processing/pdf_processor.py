"""
Enhanced PDF processor for the Email Intelligence System.
Uses Google Cloud Vision OCR API to extract text from PDF documents.
"""

import os
import json
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional

from google.cloud import storage, vision
from google.cloud.vision_v1 import types

class PDFProcessor:
    """Processes PDF documents using Google Cloud Vision OCR API."""
    
    def __init__(self, project_id: str, output_bucket: str):
        """Initialize the PDF processor.
        
        Args:
            project_id: Google Cloud project ID
            output_bucket: GCS bucket to store processed results
        """
        self.project_id = project_id
        self.output_bucket = output_bucket
        self.storage_client = storage.Client(project=project_id)
        self.vision_client = vision.ImageAnnotatorClient()
    
    def process_pdf(self, input_bucket: str, filename: str, event_id: str) -> Dict[str, Any]:
        """Process a PDF file using Cloud Vision API.
        
        Args:
            input_bucket: Name of the GCS bucket containing the PDF
            filename: Name of the PDF file to process
            event_id: ID of the event that triggered processing
            
        Returns:
            Dictionary containing extracted text and metadata
        """
        print(f"Processing PDF: {filename} from {input_bucket}")
        
        # Get the file from GCS
        bucket = self.storage_client.bucket(input_bucket)
        blob = bucket.blob(filename)
        
        # Create a temporary local file
        local_path = f"/tmp/{uuid.uuid4().hex}-{os.path.basename(filename)}"
        blob.download_to_filename(local_path)
        
        # Extract text from PDF using Cloud Vision
        extracted_text = self._extract_text_from_pdf(local_path)
        
        # Clean up temporary file
        if os.path.exists(local_path):
            os.remove(local_path)
        
        # Create result with metadata
        result = {
            "filename": filename,
            "source_bucket": input_bucket,
            "event_id": event_id,
            "processing_time": datetime.now().isoformat(),
            "document_type": "pdf",
            "text_content": extracted_text,
            "page_count": len(extracted_text) if isinstance(extracted_text, list) else 1,
            "status": "success"
        }
        
        # Save result to output bucket
        self._save_result(result, filename)
        
        return result
    
    def _extract_text_from_pdf(self, pdf_path: str) -> List[str]:
        """Extract text from PDF file pages using Cloud Vision OCR.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            List of strings with text content for each page
        """
        try:
            from pdf2image import convert_from_path
            
            # Convert PDF to images
            images = convert_from_path(pdf_path)
            
            extracted_text = []
            for i, image in enumerate(images):
                print(f"Processing page {i+1}/{len(images)}")
                
                # Save page as temporary image
                image_path = f"{pdf_path}-page{i}.jpg"
                image.save(image_path, "JPEG")
                
                # Perform OCR with Cloud Vision
                with open(image_path, "rb") as image_file:
                    content = image_file.read()
                
                image = types.Image(content=content)
                response = self.vision_client.document_text_detection(image=image)
                text = response.full_text_annotation.text
                
                extracted_text.append(text)
                
                # Clean up temporary image
                if os.path.exists(image_path):
                    os.remove(image_path)
            
            return extracted_text
            
        except Exception as e:
            print(f"Error extracting text from PDF: {e}")
            return ["Error extracting text: " + str(e)]
    
    def _save_result(self, result: Dict[str, Any], original_filename: str) -> None:
        """Save processing result to GCS.
        
        Args:
            result: Dictionary with processing results
            original_filename: Name of the original file
        """
        try:
            # Create output bucket if it doesn't exist
            bucket = self.storage_client.bucket(self.output_bucket)
            if not bucket.exists():
                bucket = self.storage_client.create_bucket(self.output_bucket)
            
            # Create JSON blob
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            result_filename = f"{os.path.splitext(original_filename)[0]}-{timestamp}.json"
            blob = bucket.blob(f"processed/{result_filename}")
            
            # Upload JSON result
            blob.upload_from_string(
                json.dumps(result, indent=2),
                content_type="application/json"
            )
            
            print(f"Saved processing result to gs://{self.output_bucket}/processed/{result_filename}")
            
        except Exception as e:
            print(f"Error saving result to GCS: {e}")


def process_pdf_document(event: Dict[str, Any], context) -> Optional[Dict[str, Any]]:
    """Cloud Function entry point for PDF processing.
    
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
        
        # Only process PDF files
        if not filename.lower().endswith(".pdf"):
            print(f"Skipping non-PDF file: {filename}")
            return None
        
        # Get project ID from environment or default
        project_id = os.environ.get("PROJECT_ID")
        if not project_id:
            # Try to get from context
            project_id = context.resource.get("projects", None)
            if not project_id:
                raise ValueError("PROJECT_ID environment variable not set")
        
        # Get output bucket
        output_bucket = os.environ.get("OUTPUT_BUCKET", f"{bucket_name}-processed")
        
        # Process the PDF
        processor = PDFProcessor(project_id, output_bucket)
        result = processor.process_pdf(bucket_name, filename, event_id)
        
        return result
        
    except Exception as e:
        print(f"Error in PDF processing function: {e}")
        return None


if __name__ == "__main__":
    # For local testing
    import argparse
    
    parser = argparse.ArgumentParser(description="Process a PDF file")
    parser.add_argument("--bucket", required=True, help="Source GCS bucket")
    parser.add_argument("--file", required=True, help="PDF filename")
    parser.add_argument("--project", required=True, help="Google Cloud project ID")
    parser.add_argument("--output-bucket", help="Output GCS bucket")
    
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
    
    # Process the document
    result = process_pdf_document(mock_event, mock_context)
    
    if result:
        print(f"Successfully processed PDF: {result['filename']}")
        print(f"Extracted {result['page_count']} pages of text")
    else:
        print("Failed to process PDF")