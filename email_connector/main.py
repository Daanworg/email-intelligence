"""
Main Cloud Function entry points for email connector operations.
"""

import functions_framework
from email_processor import process_emails

@functions_framework.http
def process_email_request(request):
    """HTTP-triggered function to process and prioritize emails.
    
    Args:
        request: HTTP request
        
    Returns:
        JSON response with processed emails
    """
    return process_emails(request)