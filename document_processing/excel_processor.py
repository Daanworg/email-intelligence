"""
Excel file processor for the Email Intelligence System.
Extracts structured data from Excel spreadsheets.
"""

import os
import json
import uuid
import io
import pandas as pd
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from google.cloud import storage

class ExcelProcessor:
    """Processes Excel files and extracts structured data."""
    
    def __init__(self, project_id: str, output_bucket: str):
        """Initialize the Excel processor.
        
        Args:
            project_id: Google Cloud project ID
            output_bucket: GCS bucket to store processed results
        """
        self.project_id = project_id
        self.output_bucket = output_bucket
        self.storage_client = storage.Client(project=project_id)
    
    def process_excel(self, input_bucket: str, filename: str, event_id: str) -> Dict[str, Any]:
        """Process an Excel file and extract structured data.
        
        Args:
            input_bucket: Name of the GCS bucket containing the Excel file
            filename: Name of the Excel file to process
            event_id: ID of the event that triggered processing
            
        Returns:
            Dictionary containing extracted data and metadata
        """
        print(f"Processing Excel file: {filename} from {input_bucket}")
        
        # Download Excel file to memory
        bucket = self.storage_client.bucket(input_bucket)
        blob = bucket.blob(filename)
        content = blob.download_as_bytes()
        
        # Extract data from Excel file
        sheets_data, metadata = self._extract_data_from_excel(content)
        
        # Create result with metadata
        result = {
            "filename": filename,
            "source_bucket": input_bucket,
            "event_id": event_id,
            "processing_time": datetime.now().isoformat(),
            "document_type": "excel",
            "sheets": sheets_data,
            "metadata": metadata,
            "status": "success"
        }
        
        # Save result to output bucket
        self._save_result(result, filename)
        
        return result
    
    def _extract_data_from_excel(self, content: bytes) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Extract structured data from an Excel file.
        
        Args:
            content: Excel file content as bytes
            
        Returns:
            Tuple containing sheet data and file metadata
        """
        try:
            # Load Excel file
            excel_file = pd.ExcelFile(io.BytesIO(content))
            
            sheets_data = []
            total_rows = 0
            total_cols = 0
            
            # Process each sheet
            for sheet_name in excel_file.sheet_names:
                # Read sheet into DataFrame
                df = pd.read_excel(excel_file, sheet_name=sheet_name)
                
                # Convert DataFrame to records (list of dicts)
                records = df.to_dict(orient='records')
                
                # Get column types and basic stats
                column_info = {}
                for column in df.columns:
                    column_type = str(df[column].dtype)
                    column_info[str(column)] = {
                        "type": column_type,
                        "null_count": int(df[column].isna().sum()),
                        "unique_count": int(df[column].nunique())
                    }
                    
                    # Add basic statistics for numeric columns
                    if df[column].dtype.kind in 'ifc':  # integer, float, complex
                        column_info[str(column)].update({
                            "min": float(df[column].min()) if not pd.isna(df[column].min()) else None,
                            "max": float(df[column].max()) if not pd.isna(df[column].max()) else None,
                            "mean": float(df[column].mean()) if not pd.isna(df[column].mean()) else None
                        })
                
                # Add sheet data
                sheet_data = {
                    "name": sheet_name,
                    "row_count": len(df),
                    "column_count": len(df.columns),
                    "columns": list(df.columns.astype(str)),
                    "column_info": column_info,
                    "data": records,
                    "data_types": {col: str(dtype) for col, dtype in df.dtypes.items()}
                }
                
                sheets_data.append(sheet_data)
                total_rows += len(df)
                total_cols += len(df.columns)
            
            # Create metadata
            metadata = {
                "sheet_count": len(excel_file.sheet_names),
                "sheet_names": excel_file.sheet_names,
                "total_rows": total_rows,
                "total_columns": total_cols,
                "file_size_bytes": len(content)
            }
            
            return sheets_data, metadata
            
        except Exception as e:
            print(f"Error extracting data from Excel file: {e}")
            return [], {"error": str(e)}
    
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


def process_excel_document(event: Dict[str, Any], context) -> Optional[Dict[str, Any]]:
    """Cloud Function entry point for Excel processing.
    
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
        
        # Only process Excel files
        if not filename.lower().endswith((".xlsx", ".xls")):
            print(f"Skipping non-Excel file: {filename}")
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
        
        # Process the Excel file
        processor = ExcelProcessor(project_id, output_bucket)
        result = processor.process_excel(bucket_name, filename, event_id)
        
        return result
        
    except Exception as e:
        print(f"Error in Excel processing function: {e}")
        return None


if __name__ == "__main__":
    # For local testing
    import argparse
    
    parser = argparse.ArgumentParser(description="Process an Excel file")
    parser.add_argument("--bucket", required=True, help="Source GCS bucket")
    parser.add_argument("--file", required=True, help="Excel filename")
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
    result = process_excel_document(mock_event, mock_context)
    
    if result:
        print(f"Successfully processed Excel file: {result['filename']}")
        print(f"Processed {result['metadata']['sheet_count']} sheets with {result['metadata']['total_rows']} total rows")
    else:
        print("Failed to process Excel file")