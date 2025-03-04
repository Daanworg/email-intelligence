"""
Knowledge processor for the Email Intelligence System.
Processes documents and builds the knowledge base.
"""

import os
import json
import uuid
import argparse
from datetime import datetime
from typing import List, Dict, Any, Optional

from google.cloud import storage
import vertexai

from entity_extractor import EntityExtractor
from knowledge_store import KnowledgeStore


class KnowledgeProcessor:
    """Processes documents and constructs the knowledge base."""
    
    def __init__(
        self,
        project_id: str,
        input_bucket: str,
        output_bucket: str,
        vertex_location: str = "us-central1"
    ):
        """Initialize the knowledge processor.
        
        Args:
            project_id: Google Cloud project ID
            input_bucket: GCS bucket for processed documents
            output_bucket: GCS bucket for knowledge store
            vertex_location: Vertex AI location
        """
        self.project_id = project_id
        self.input_bucket = input_bucket
        self.output_bucket = output_bucket
        
        # Initialize clients
        self.storage_client = storage.Client(project=project_id)
        
        # Initialize Vertex AI
        vertexai.init(project=project_id, location=vertex_location)
        
        # Initialize components
        self.entity_extractor = EntityExtractor(project_id, output_bucket)
        self.knowledge_store = KnowledgeStore(project_id, output_bucket)
    
    def process_document(self, document_path: str) -> Dict[str, Any]:
        """Process a document to extract knowledge.
        
        Args:
            document_path: GCS path to the document
            
        Returns:
            Dictionary with processing results
        """
        print(f"Processing document: {document_path}")
        
        # Load document content
        document_content = self._load_document(document_path)
        
        if not document_content:
            return {"error": f"Failed to load document: {document_path}"}
        
        # Extract entities
        entities = self.entity_extractor.extract_entities_from_document(
            document_content, document_path
        )
        
        # Extract relationships
        relationships = self.entity_extractor.extract_relationships(entities, document_content)
        
        # Add to knowledge store
        entity_ids = self.knowledge_store.add_entities(entities)
        relationship_ids = self.knowledge_store.add_relationships(relationships)
        
        # Create results
        result = {
            "document_path": document_path,
            "processing_time": datetime.now().isoformat(),
            "entity_count": len(entities),
            "relationship_count": len(relationships),
            "entity_types": self._count_entity_types(entities),
            "relationship_types": self._count_relationship_types(relationships)
        }
        
        # Save results
        self._save_processing_result(document_path, result)
        
        return result
    
    def process_all_documents(self, prefix: str = "processed/") -> Dict[str, Any]:
        """Process all documents in the input bucket.
        
        Args:
            prefix: Prefix for documents to process
            
        Returns:
            Dictionary with processing summary
        """
        bucket = self.storage_client.bucket(self.input_bucket)
        blobs = list(bucket.list_blobs(prefix=prefix))
        
        print(f"Found {len(blobs)} documents to process")
        
        processed_count = 0
        entity_count = 0
        relationship_count = 0
        errors = []
        
        for blob in blobs:
            if blob.name.endswith(".json"):
                try:
                    document_path = f"gs://{self.input_bucket}/{blob.name}"
                    result = self.process_document(document_path)
                    
                    processed_count += 1
                    entity_count += result.get("entity_count", 0)
                    relationship_count += result.get("relationship_count", 0)
                    
                except Exception as e:
                    error_msg = f"Error processing {blob.name}: {str(e)}"
                    print(error_msg)
                    errors.append(error_msg)
        
        # Create summary
        summary = {
            "processing_time": datetime.now().isoformat(),
            "documents_processed": processed_count,
            "entity_count": entity_count,
            "relationship_count": relationship_count,
            "errors": errors
        }
        
        # Save summary
        summary_path = f"knowledge/processing_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        bucket = self.storage_client.bucket(self.output_bucket)
        blob = bucket.blob(summary_path)
        blob.upload_from_string(
            json.dumps(summary, indent=2),
            content_type="application/json"
        )
        
        return summary
    
    def _load_document(self, document_path: str) -> Optional[str]:
        """Load document content from GCS.
        
        Args:
            document_path: GCS path to the document
            
        Returns:
            Document content or None if error
        """
        try:
            # Parse bucket and blob path
            gcs_path = document_path.replace("gs://", "")
            bucket_name, blob_path = gcs_path.split("/", 1)
            
            # Get the content
            bucket = self.storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_path)
            
            if blob.name.endswith(".json"):
                # For JSON files, extract text content
                content = json.loads(blob.download_as_string())
                
                # Handle different types of processed documents
                if "text_content" in content:
                    # Direct text content
                    if isinstance(content["text_content"], list):
                        return "\n\n".join(content["text_content"])
                    else:
                        return content["text_content"]
                elif "sheets" in content and isinstance(content["sheets"], list):
                    # Excel data
                    texts = []
                    for sheet in content["sheets"]:
                        sheet_name = sheet.get("name", "Unknown Sheet")
                        texts.append(f"Sheet: {sheet_name}")
                        
                        # Add data
                        for record in sheet.get("data", []):
                            texts.append(str(record))
                    
                    return "\n".join(texts)
                else:
                    # Unknown JSON format, convert to string
                    return json.dumps(content, indent=2)
            else:
                # For other files, read as text
                return blob.download_as_text()
        
        except Exception as e:
            print(f"Error loading document {document_path}: {e}")
            return None
    
    def _count_entity_types(self, entities: List[Dict[str, Any]]) -> Dict[str, int]:
        """Count entities by type.
        
        Args:
            entities: List of entity dictionaries
            
        Returns:
            Dictionary with counts by entity type
        """
        counts = {}
        for entity in entities:
            entity_type = entity["type"]
            counts[entity_type] = counts.get(entity_type, 0) + 1
        
        return counts
    
    def _count_relationship_types(self, relationships: List[Dict[str, Any]]) -> Dict[str, int]:
        """Count relationships by type.
        
        Args:
            relationships: List of relationship dictionaries
            
        Returns:
            Dictionary with counts by relationship type
        """
        counts = {}
        for rel in relationships:
            rel_type = rel["relationship_type"]
            counts[rel_type] = counts.get(rel_type, 0) + 1
        
        return counts
    
    def _save_processing_result(self, document_path: str, result: Dict[str, Any]) -> None:
        """Save processing result to Cloud Storage.
        
        Args:
            document_path: Path to the processed document
            result: Processing result dictionary
        """
        # Generate a filename based on the document path
        filename = document_path.replace("gs://", "").replace("/", "_")
        result_path = f"knowledge/processing_results/{filename}_result.json"
        
        # Save to GCS
        bucket = self.storage_client.bucket(self.output_bucket)
        blob = bucket.blob(result_path)
        blob.upload_from_string(
            json.dumps(result, indent=2),
            content_type="application/json"
        )
        
        print(f"Saved processing result to gs://{self.output_bucket}/{result_path}")


def cloud_function_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """Cloud Function entry point for knowledge processing.
    
    Args:
        event: Cloud Functions event payload
        context: Event context
        
    Returns:
        Processing result
    """
    try:
        # Get document path from event
        document_path = event.get("document_path")
        
        if not document_path:
            return {"error": "No document_path provided in event"}
        
        # Get configuration from environment
        project_id = os.environ.get("PROJECT_ID")
        input_bucket = os.environ.get("INPUT_BUCKET")
        output_bucket = os.environ.get("OUTPUT_BUCKET")
        
        if not project_id or not input_bucket or not output_bucket:
            return {"error": "Missing required environment variables"}
        
        # Process the document
        processor = KnowledgeProcessor(
            project_id=project_id,
            input_bucket=input_bucket,
            output_bucket=output_bucket
        )
        
        result = processor.process_document(document_path)
        
        return result
        
    except Exception as e:
        return {"error": f"Error in knowledge processing: {str(e)}"}


# For batch processing
def cloud_function_batch_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """Cloud Function entry point for batch knowledge processing.
    
    Args:
        event: Cloud Functions event payload
        context: Event context
        
    Returns:
        Processing summary
    """
    try:
        # Get configuration from environment
        project_id = os.environ.get("PROJECT_ID")
        input_bucket = os.environ.get("INPUT_BUCKET")
        output_bucket = os.environ.get("OUTPUT_BUCKET")
        
        if not project_id or not input_bucket or not output_bucket:
            return {"error": "Missing required environment variables"}
        
        # Get optional prefix from event
        prefix = event.get("prefix", "processed/")
        
        # Process all documents
        processor = KnowledgeProcessor(
            project_id=project_id,
            input_bucket=input_bucket,
            output_bucket=output_bucket
        )
        
        summary = processor.process_all_documents(prefix)
        
        return summary
        
    except Exception as e:
        return {"error": f"Error in batch knowledge processing: {str(e)}"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process documents for knowledge extraction")
    parser.add_argument("--project", required=True, help="Google Cloud project ID")
    parser.add_argument("--input-bucket", required=True, help="GCS bucket for input documents")
    parser.add_argument("--output-bucket", required=True, help="GCS bucket for knowledge store")
    parser.add_argument("--document", help="GCS path to a specific document to process")
    parser.add_argument("--batch", action="store_true", help="Process all documents in the bucket")
    parser.add_argument("--prefix", default="processed/", help="Prefix for documents to process in batch mode")
    
    args = parser.parse_args()
    
    # Initialize processor
    processor = KnowledgeProcessor(
        project_id=args.project,
        input_bucket=args.input_bucket,
        output_bucket=args.output_bucket
    )
    
    if args.document:
        # Process a single document
        result = processor.process_document(args.document)
        print(f"Processed document: {args.document}")
        print(f"Extracted {result.get('entity_count', 0)} entities and {result.get('relationship_count', 0)} relationships")
    
    elif args.batch:
        # Process all documents
        summary = processor.process_all_documents(args.prefix)
        print("Batch processing complete:")
        print(f"Processed {summary.get('documents_processed', 0)} documents")
        print(f"Extracted {summary.get('entity_count', 0)} entities and {summary.get('relationship_count', 0)} relationships")
        if summary.get("errors"):
            print(f"Encountered {len(summary.get('errors', []))} errors")
    
    else:
        print("Please specify either --document or --batch")