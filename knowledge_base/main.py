"""
Main Cloud Function entry points for knowledge base operations.
"""

import functions_framework
from knowledge_processor import cloud_function_handler, cloud_function_batch_handler

@functions_framework.http
def process_document(request):
    """HTTP-triggered function to process a document for knowledge extraction.
    
    Args:
        request: HTTP request
        
    Returns:
        Processing result
    """
    request_json = request.get_json(silent=True)
    
    if not request_json:
        return {"error": "No JSON payload provided"}, 400
    
    result = cloud_function_handler(request_json, None)
    
    if "error" in result:
        return result, 400
    
    return result

@functions_framework.http
def process_documents_batch(request):
    """HTTP-triggered function to process multiple documents for knowledge extraction.
    
    Args:
        request: HTTP request
        
    Returns:
        Processing summary
    """
    request_json = request.get_json(silent=True) or {}
    
    result = cloud_function_batch_handler(request_json, None)
    
    if "error" in result:
        return result, 400
    
    return result

@functions_framework.cloud_event
def process_document_event(cloud_event):
    """Pub/Sub-triggered function to process a document for knowledge extraction.
    
    Args:
        cloud_event: Cloud event
        
    Returns:
        Processing result
    """
    # Extract data from cloud event
    event_data = cloud_event.data
    
    if not event_data:
        return {"error": "No event data provided"}
    
    return cloud_function_handler(event_data, cloud_event.context)