"""
Microsoft Graph API connector for the Email Intelligence System.
Handles authentication and retrieval of emails from Microsoft 365.
"""

import os
import json
import uuid
import time
import base64
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import requests
import msal


class MSGraphConnector:
    """Connector for Microsoft Graph API."""
    
    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        scopes: List[str] = None,
        user_email: str = None
    ):
        """Initialize the MS Graph connector.
        
        Args:
            tenant_id: Azure AD tenant ID
            client_id: Application client ID
            client_secret: Application client secret
            scopes: List of Microsoft Graph API scopes
            user_email: Target user email (for delegate access)
        """
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.scopes = scopes or ["https://graph.microsoft.com/.default"]
        self.user_email = user_email
        self.token = None
        self.token_expiry = 0
        
        # Create the MSAL app
        self.app = msal.ConfidentialClientApplication(
            client_id=self.client_id,
            client_credential=self.client_secret,
            authority=f"https://login.microsoftonline.com/{self.tenant_id}"
        )
    
    def get_token(self) -> Optional[str]:
        """Get an access token for Microsoft Graph API.
        
        Returns:
            Access token or None if error
        """
        # Check if we have a valid token
        current_time = time.time()
        if self.token and current_time < self.token_expiry - 300:  # 5 minute buffer
            return self.token
        
        # Acquire a new token
        try:
            result = self.app.acquire_token_for_client(scopes=self.scopes)
            
            if "access_token" in result:
                self.token = result["access_token"]
                self.token_expiry = current_time + result.get("expires_in", 3600)
                return self.token
            else:
                print(f"Error getting token: {result.get('error_description', 'Unknown error')}")
                return None
                
        except Exception as e:
            print(f"Exception getting token: {e}")
            return None
    
    def get_messages(
        self,
        folder: str = "inbox",
        filter_query: str = None,
        top: int = 50,
        skip: int = 0,
        order_by: str = "receivedDateTime desc",
        select: List[str] = None,
        expand: List[str] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """Get messages from a folder.
        
        Args:
            folder: Folder to get messages from (inbox, sentitems, etc.)
            filter_query: OData filter query
            top: Number of messages to return
            skip: Number of messages to skip
            order_by: OData order by clause
            select: Properties to select
            expand: Properties to expand
            
        Returns:
            List of message dictionaries or None if error
        """
        token = self.get_token()
        if not token:
            return None
        
        # Build the URL
        user_part = f"users/{self.user_email}" if self.user_email else "me"
        url = f"https://graph.microsoft.com/v1.0/{user_part}/mailFolders/{folder}/messages"
        
        # Build query parameters
        params = {
            "$top": top,
            "$skip": skip,
            "$orderby": order_by
        }
        
        if filter_query:
            params["$filter"] = filter_query
        
        if select:
            params["$select"] = ",".join(select)
        
        if expand:
            params["$expand"] = ",".join(expand)
        
        # Make the request
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            
            data = response.json()
            return data.get("value", [])
            
        except Exception as e:
            print(f"Error getting messages: {e}")
            return None
    
    def get_recent_messages(
        self,
        days: int = 7,
        folder: str = "inbox",
        top: int = 100
    ) -> Optional[List[Dict[str, Any]]]:
        """Get recent messages from a folder.
        
        Args:
            days: Number of days to look back
            folder: Folder to get messages from
            top: Maximum number of messages to return
            
        Returns:
            List of message dictionaries or None if error
        """
        # Calculate the date filter
        date_from = (datetime.now() - timedelta(days=days)).isoformat()
        filter_query = f"receivedDateTime ge {date_from}"
        
        # Properties to retrieve
        select = [
            "id", "subject", "receivedDateTime", "sender", "from", "toRecipients",
            "bodyPreview", "conversationId", "importance", "hasAttachments"
        ]
        
        return self.get_messages(
            folder=folder,
            filter_query=filter_query,
            top=top,
            select=select
        )
    
    def get_message_content(self, message_id: str) -> Optional[Dict[str, Any]]:
        """Get the full content of a message.
        
        Args:
            message_id: ID of the message to retrieve
            
        Returns:
            Message dictionary or None if error
        """
        token = self.get_token()
        if not token:
            return None
        
        # Build the URL
        user_part = f"users/{self.user_email}" if self.user_email else "me"
        url = f"https://graph.microsoft.com/v1.0/{user_part}/messages/{message_id}"
        
        # Add parameters to get the full message
        params = {
            "$select": "id,subject,receivedDateTime,sender,from,toRecipients,ccRecipients,"
                     "body,conversationId,importance,hasAttachments,attachments"
        }
        
        # Make the request
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            
            return response.json()
            
        except Exception as e:
            print(f"Error getting message content: {e}")
            return None
    
    def get_conversation_thread(self, conversation_id: str) -> Optional[List[Dict[str, Any]]]:
        """Get all messages in a conversation thread.
        
        Args:
            conversation_id: ID of the conversation
            
        Returns:
            List of message dictionaries or None if error
        """
        token = self.get_token()
        if not token:
            return None
        
        # Build the URL
        user_part = f"users/{self.user_email}" if self.user_email else "me"
        url = f"https://graph.microsoft.com/v1.0/{user_part}/messages"
        
        # Add parameters to filter by conversation and get needed properties
        params = {
            "$filter": f"conversationId eq '{conversation_id}'",
            "$orderby": "receivedDateTime asc",
            "$select": "id,subject,receivedDateTime,sender,from,bodyPreview,conversationId",
            "$top": 100
        }
        
        # Make the request
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            
            data = response.json()
            return data.get("value", [])
            
        except Exception as e:
            print(f"Error getting conversation thread: {e}")
            return None
    
    def search_messages(self, query: str, folder: str = "inbox", top: int = 50) -> Optional[List[Dict[str, Any]]]:
        """Search for messages using KQL query.
        
        Args:
            query: KQL search query
            folder: Folder to search in
            top: Maximum number of results
            
        Returns:
            List of message dictionaries or None if error
        """
        token = self.get_token()
        if not token:
            return None
        
        # Build the URL
        user_part = f"users/{self.user_email}" if self.user_email else "me"
        url = f"https://graph.microsoft.com/v1.0/{user_part}/messages"
        
        # Add search parameter and other filters
        params = {
            "$search": query,
            "$top": top,
            "$select": "id,subject,receivedDateTime,sender,from,bodyPreview,conversationId"
        }
        
        if folder != "allitems":
            folder_url = f"https://graph.microsoft.com/v1.0/{user_part}/mailFolders/{folder}"
            try:
                folder_response = requests.get(
                    folder_url,
                    headers={"Authorization": f"Bearer {token}"},
                )
                folder_response.raise_for_status()
                folder_data = folder_response.json()
                
                if "id" in folder_data:
                    url = f"https://graph.microsoft.com/v1.0/{user_part}/mailFolders/{folder_data['id']}/messages"
            except Exception as e:
                print(f"Error getting folder info: {e}")
        
        # Make the request
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "ConsistencyLevel": "eventual"  # Required for $search
        }
        
        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            
            data = response.json()
            return data.get("value", [])
            
        except Exception as e:
            print(f"Error searching messages: {e}")
            return None


def get_credentials_from_env() -> Dict[str, str]:
    """Get Microsoft Graph credentials from environment variables.
    
    Returns:
        Dictionary of credentials
    """
    return {
        "tenant_id": os.environ.get("MS_TENANT_ID", ""),
        "client_id": os.environ.get("MS_CLIENT_ID", ""),
        "client_secret": os.environ.get("MS_CLIENT_SECRET", ""),
        "user_email": os.environ.get("MS_USER_EMAIL", "")
    }


# Example usage
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Microsoft Graph API connector")
    parser.add_argument("--tenant-id", help="Azure AD tenant ID")
    parser.add_argument("--client-id", help="Application client ID")
    parser.add_argument("--client-secret", help="Application client secret")
    parser.add_argument("--user-email", help="Target user email (for delegate access)")
    parser.add_argument("--days", type=int, default=7, help="Number of days to look back")
    parser.add_argument("--folder", default="inbox", help="Folder to get messages from")
    parser.add_argument("--count", type=int, default=10, help="Number of messages to return")
    parser.add_argument("--search", help="Search query for messages")
    
    args = parser.parse_args()
    
    # Get credentials from args or environment
    tenant_id = args.tenant_id or os.environ.get("MS_TENANT_ID")
    client_id = args.client_id or os.environ.get("MS_CLIENT_ID")
    client_secret = args.client_secret or os.environ.get("MS_CLIENT_SECRET")
    user_email = args.user_email or os.environ.get("MS_USER_EMAIL")
    
    if not tenant_id or not client_id or not client_secret:
        print("Error: Missing required credentials")
        print("Please provide credentials via arguments or environment variables:")
        print("  MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET")
        exit(1)
    
    # Initialize connector
    connector = MSGraphConnector(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
        user_email=user_email
    )
    
    # Get token test
    token = connector.get_token()
    if not token:
        print("Error: Failed to get access token")
        exit(1)
    
    print(f"Successfully authenticated with Microsoft Graph API")
    
    # Perform requested operation
    if args.search:
        print(f"Searching for: {args.search}")
        messages = connector.search_messages(args.search, args.folder, args.count)
    else:
        print(f"Getting {args.count} recent messages from {args.folder} (last {args.days} days)")
        messages = connector.get_recent_messages(args.days, args.folder, args.count)
    
    if messages:
        print(f"Found {len(messages)} messages")
        for msg in messages:
            sender = msg.get("sender", {}).get("emailAddress", {}).get("name", "Unknown")
            subject = msg.get("subject", "No subject")
            received = msg.get("receivedDateTime", "")
            print(f"{received} - {sender}: {subject}")
    else:
        print("No messages found or error occurred")