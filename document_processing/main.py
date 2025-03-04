"""
Main Cloud Function entry point for document processing in the Email Intelligence System.
"""

import functions_framework
from unified_processor import process_document_entry

@functions_framework.cloud_event
def process_document(cloud_event):
    """Cloud Function for processing documents triggered by Cloud Storage events.
    
    Args:
        cloud_event: The Cloud Event that triggered the function
        
    Returns:
        Processing result
    """
    # Extract storage event data
    event = {
        "bucket": cloud_event.data["bucket"],
        "name": cloud_event.data["name"],
    }
    
    # Pass to the processor
    result = process_document_entry(event, cloud_event.context)
    
    return result