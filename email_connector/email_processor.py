"""
Email processor for the Email Intelligence System.
Processes and prioritizes emails using the knowledge base.
"""

import os
import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

import requests
from google.cloud import storage

from ms_graph_connector import MSGraphConnector, get_credentials_from_env


class EmailProcessor:
    """Processes emails and applies intelligence based on the knowledge base."""
    
    def __init__(
        self,
        project_id: str,
        knowledge_bucket: str,
        graph_connector: MSGraphConnector = None,
        kb_api_url: str = None
    ):
        """Initialize the email processor.
        
        Args:
            project_id: Google Cloud project ID
            knowledge_bucket: GCS bucket for knowledge store
            graph_connector: Existing MS Graph connector (or None to create one)
            kb_api_url: API URL for the knowledge base (Cloud Function)
        """
        self.project_id = project_id
        self.knowledge_bucket = knowledge_bucket
        
        # If no connector provided, create one from environment variables
        if graph_connector:
            self.graph_connector = graph_connector
        else:
            credentials = get_credentials_from_env()
            self.graph_connector = MSGraphConnector(**credentials)
        
        # Knowledge base API URL (optional)
        self.kb_api_url = kb_api_url
        
        # Storage client
        self.storage_client = storage.Client(project=project_id)
    
    def get_recent_messages(
        self,
        days: int = 7,
        folder: str = "inbox",
        top: int = 100
    ) -> Optional[List[Dict[str, Any]]]:
        """Get recent messages with basic processing.
        
        Args:
            days: Number of days to look back
            folder: Folder to get messages from
            top: Maximum number of messages to return
            
        Returns:
            List of processed message dictionaries or None if error
        """
        # Get messages from MS Graph
        messages = self.graph_connector.get_recent_messages(days, folder, top)
        
        if not messages:
            return None
        
        # Process messages
        processed_messages = []
        
        for message in messages:
            # Extract conversation ID
            conversation_id = message.get("conversationId")
            
            # Get basic priority score
            priority_score, priority_reasons = self._calculate_basic_priority(message)
            
            # Add basic processing
            processed_message = {
                "id": message.get("id"),
                "subject": message.get("subject"),
                "sender": message.get("sender"),
                "receivedDateTime": message.get("receivedDateTime"),
                "conversationId": conversation_id,
                "bodyPreview": message.get("bodyPreview"),
                "hasAttachments": message.get("hasAttachments", False),
                "importance": message.get("importance", "normal"),
                "priority_score": priority_score,
                "priority_reasons": priority_reasons
            }
            
            processed_messages.append(processed_message)
        
        return processed_messages
    
    def get_prioritized_messages(
        self,
        days: int = 7,
        folder: str = "inbox",
        top: int = 100,
        min_priority: float = 0.0
    ) -> Optional[List[Dict[str, Any]]]:
        """Get recent messages with enhanced priority processing.
        
        Args:
            days: Number of days to look back
            folder: Folder to get messages from
            top: Maximum number of messages to return
            min_priority: Minimum priority score to include
            
        Returns:
            List of prioritized message dictionaries or None if error
        """
        # Get basic processed messages
        messages = self.get_recent_messages(days, folder, top)
        
        if not messages:
            return None
        
        # Group by conversation for context
        conversations = self._group_by_conversation(messages)
        
        # Process each conversation for enhanced priority
        prioritized_messages = []
        
        for conversation_id, thread in conversations.items():
            # Calculate priorities for this thread
            thread_with_priorities = self._prioritize_conversation(conversation_id, thread)
            prioritized_messages.extend(thread_with_priorities)
        
        # Filter by priority and sort by priority score
        result = [msg for msg in prioritized_messages if msg["priority_score"] >= min_priority]
        result.sort(key=lambda x: x["priority_score"], reverse=True)
        
        # Limit to requested number
        return result[:top]
    
    def search_prioritized_messages(
        self,
        query: str,
        folder: str = "inbox",
        top: int = 50,
        min_priority: float = 0.0
    ) -> Optional[List[Dict[str, Any]]]:
        """Search for messages and apply priority processing.
        
        Args:
            query: Search query
            folder: Folder to search in
            top: Maximum number of results
            min_priority: Minimum priority score to include
            
        Returns:
            List of prioritized message dictionaries or None if error
        """
        # Search messages using MS Graph
        messages = self.graph_connector.search_messages(query, folder, top)
        
        if not messages:
            return None
        
        # Process messages
        processed_messages = []
        
        for message in messages:
            # Extract conversation ID
            conversation_id = message.get("conversationId")
            
            # Get basic priority score
            priority_score, priority_reasons = self._calculate_basic_priority(message)
            
            # Add basic processing
            processed_message = {
                "id": message.get("id"),
                "subject": message.get("subject"),
                "sender": message.get("sender"),
                "receivedDateTime": message.get("receivedDateTime"),
                "conversationId": conversation_id,
                "bodyPreview": message.get("bodyPreview"),
                "hasAttachments": message.get("hasAttachments", False),
                "importance": message.get("importance", "normal"),
                "priority_score": priority_score,
                "priority_reasons": priority_reasons,
                "query_match": True
            }
            
            processed_messages.append(processed_message)
        
        # Get conversation threads for context
        conversation_ids = {msg["conversationId"] for msg in processed_messages if msg["conversationId"]}
        
        for conversation_id in conversation_ids:
            # Get thread
            thread = self.graph_connector.get_conversation_thread(conversation_id)
            
            if thread:
                # Add messages not in the search results
                existing_ids = {msg["id"] for msg in processed_messages}
                for msg in thread:
                    if msg["id"] not in existing_ids:
                        # Get basic priority score
                        priority_score, priority_reasons = self._calculate_basic_priority(msg)
                        
                        # Add basic processing
                        processed_message = {
                            "id": msg.get("id"),
                            "subject": msg.get("subject"),
                            "sender": msg.get("sender"),
                            "receivedDateTime": msg.get("receivedDateTime"),
                            "conversationId": conversation_id,
                            "bodyPreview": msg.get("bodyPreview"),
                            "hasAttachments": msg.get("hasAttachments", False),
                            "importance": msg.get("importance", "normal"),
                            "priority_score": priority_score,
                            "priority_reasons": priority_reasons,
                            "query_match": False
                        }
                        
                        processed_messages.append(processed_message)
        
        # Group by conversation for context
        conversations = self._group_by_conversation(processed_messages)
        
        # Process each conversation for enhanced priority
        prioritized_messages = []
        
        for conversation_id, thread in conversations.items():
            # Calculate priorities for this thread
            thread_with_priorities = self._prioritize_conversation(conversation_id, thread)
            prioritized_messages.extend(thread_with_priorities)
        
        # Filter by priority and put direct query matches first
        direct_matches = [msg for msg in prioritized_messages 
                         if msg.get("query_match", False) and msg["priority_score"] >= min_priority]
        context_msgs = [msg for msg in prioritized_messages 
                       if not msg.get("query_match", False) and msg["priority_score"] >= min_priority]
        
        # Sort each group by priority score
        direct_matches.sort(key=lambda x: x["priority_score"], reverse=True)
        context_msgs.sort(key=lambda x: x["priority_score"], reverse=True)
        
        # Combine results with direct matches first
        result = direct_matches + context_msgs
        
        # Limit to requested number
        return result[:top]
    
    def get_message_with_knowledge_context(self, message_id: str) -> Optional[Dict[str, Any]]:
        """Get full message content with knowledge context.
        
        Args:
            message_id: ID of the message to retrieve
            
        Returns:
            Message dictionary with knowledge context or None if error
        """
        # Get the full message content
        message = self.graph_connector.get_message_content(message_id)
        
        if not message:
            return None
        
        # Get the conversation thread
        conversation_id = message.get("conversationId")
        thread = None
        
        if conversation_id:
            thread = self.graph_connector.get_conversation_thread(conversation_id)
        
        # Get knowledge context
        knowledge_context = self._get_knowledge_context(message, thread)
        
        # Add to the message
        result = message.copy()
        result["knowledge_context"] = knowledge_context
        
        # Calculate priority
        priority_score, priority_reasons = self._calculate_enhanced_priority(
            message, thread, knowledge_context
        )
        
        result["priority_score"] = priority_score
        result["priority_reasons"] = priority_reasons
        
        return result
    
    def _calculate_basic_priority(self, message: Dict[str, Any]) -> Tuple[float, List[str]]:
        """Calculate a basic priority score for a message.
        
        Args:
            message: Message dictionary
            
        Returns:
            Tuple of (priority_score, priority_reasons)
        """
        priority_score = 0.0
        priority_reasons = []
        
        # Check importance flag
        importance = message.get("importance", "normal").lower()
        if importance == "high":
            priority_score += 0.3
            priority_reasons.append("Marked as high importance")
        
        # Check for attachments
        if message.get("hasAttachments", False):
            priority_score += 0.1
            priority_reasons.append("Has attachments")
        
        # Check for urgency keywords in subject
        subject = message.get("subject", "").lower()
        urgency_keywords = ["urgent", "asap", "immediately", "critical", "important", "deadline"]
        
        for keyword in urgency_keywords:
            if keyword in subject:
                priority_score += 0.2
                priority_reasons.append(f"Urgency keyword '{keyword}' in subject")
                break
        
        # Check for recency (higher priority for newer messages)
        try:
            received_str = message.get("receivedDateTime", "")
            if received_str:
                received_date = datetime.fromisoformat(received_str.replace("Z", "+00:00"))
                now = datetime.now().astimezone()
                age_hours = (now - received_date).total_seconds() / 3600
                
                # Higher priority for newer messages (up to 24 hours)
                if age_hours < 24:
                    recency_score = 0.2 * (1 - (age_hours / 24))
                    priority_score += recency_score
                    priority_reasons.append(f"Recent message ({age_hours:.1f} hours old)")
        except Exception:
            pass
        
        # Ensure score is between 0 and 1
        priority_score = max(0.0, min(1.0, priority_score))
        
        return priority_score, priority_reasons
    
    def _group_by_conversation(self, messages: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Group messages by conversation ID.
        
        Args:
            messages: List of message dictionaries
            
        Returns:
            Dictionary mapping conversation IDs to lists of messages
        """
        conversations = {}
        
        for message in messages:
            conversation_id = message.get("conversationId")
            
            if not conversation_id:
                continue
            
            if conversation_id not in conversations:
                conversations[conversation_id] = []
            
            conversations[conversation_id].append(message)
        
        # Sort each conversation by date
        for conversation_id in conversations:
            conversations[conversation_id].sort(
                key=lambda x: x.get("receivedDateTime", ""),
                reverse=False  # Oldest first
            )
        
        return conversations
    
    def _prioritize_conversation(
        self,
        conversation_id: str,
        thread: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Calculate enhanced priorities for a conversation thread.
        
        Args:
            conversation_id: Conversation ID
            thread: List of messages in the thread
            
        Returns:
            List of messages with enhanced priority scores
        """
        result = []
        
        # Get combined text from thread for context
        thread_text = self._get_thread_text(thread)
        
        # Get knowledge context for the thread
        knowledge_context = self._get_knowledge_context_for_text(thread_text)
        
        # Process each message
        for message in thread:
            # Calculate enhanced priority
            priority_score, priority_reasons = self._calculate_enhanced_priority(
                message, thread, knowledge_context
            )
            
            # Create prioritized message
            prioritized_message = message.copy()
            prioritized_message["priority_score"] = priority_score
            prioritized_message["priority_reasons"] = priority_reasons
            prioritized_message["knowledge_context"] = knowledge_context
            
            result.append(prioritized_message)
        
        return result
    
    def _get_thread_text(self, thread: List[Dict[str, Any]]) -> str:
        """Get text representation of a thread.
        
        Args:
            thread: List of messages in the thread
            
        Returns:
            Combined text from the thread
        """
        if not thread:
            return ""
        
        # Get the subject from the first message
        subject = thread[0].get("subject", "")
        
        # Combine body previews
        body_texts = []
        for message in thread:
            sender = message.get("sender", {}).get("emailAddress", {}).get("name", "Unknown")
            body = message.get("bodyPreview", "")
            
            if body:
                body_texts.append(f"{sender}: {body}")
        
        # Combine all text
        return f"Subject: {subject}\n\n" + "\n\n".join(body_texts)
    
    def _get_knowledge_context(
        self,
        message: Dict[str, Any],
        thread: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Get knowledge context for a message and its thread.
        
        Args:
            message: Message dictionary
            thread: Optional list of messages in the thread
            
        Returns:
            Knowledge context dictionary
        """
        # Get text from message
        message_text = message.get("bodyPreview", "")
        subject = message.get("subject", "")
        
        # Combine with thread text if available
        if thread:
            thread_text = self._get_thread_text(thread)
        else:
            thread_text = f"Subject: {subject}\n\n{message_text}"
        
        # Get knowledge context for the combined text
        return self._get_knowledge_context_for_text(thread_text)
    
    def _get_knowledge_context_for_text(self, text: str) -> Dict[str, Any]:
        """Get knowledge context for text.
        
        Args:
            text: Text to get context for
            
        Returns:
            Knowledge context dictionary
        """
        # Get entities from the text
        entities = self._extract_entities_from_text(text)
        
        # Get related entities from knowledge base
        related_entities = self._get_related_entities(entities)
        
        # Combine results
        return {
            "direct_entities": entities,
            "related_entities": related_entities
        }
    
    def _extract_entities_from_text(self, text: str) -> List[Dict[str, Any]]:
        """Extract entities from text.
        
        Args:
            text: Text to extract entities from
            
        Returns:
            List of entity dictionaries
        """
        # If we have a knowledge base API, use it
        if self.kb_api_url:
            try:
                response = requests.post(
                    f"{self.kb_api_url}/extract-entities",
                    json={"text": text},
                    headers={"Content-Type": "application/json"}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return result.get("entities", [])
            except Exception as e:
                print(f"Error calling knowledge base API: {e}")
        
        # Fallback to simple extraction
        entities = []
        
        # Extract people by looking for @ mentions and common name patterns
        email_mentions = set()
        for line in text.split("\n"):
            for word in line.split():
                if "@" in word and "." in word and len(word) > 5:
                    email = word.strip(",.;:()[]{}\"'")
                    email_mentions.add(email)
        
        for email in email_mentions:
            name_part = email.split("@")[0].replace(".", " ").title()
            entities.append({
                "text": name_part,
                "type": "PERSON",
                "relevance": 0.7,
                "source": "email"
            })
        
        # Extract potential project names using heuristics
        project_indicators = ["project", "p-", "prj-", "program", "initiative"]
        for line in text.split("\n"):
            for indicator in project_indicators:
                if indicator in line.lower():
                    # Get the potential project name
                    start_idx = line.lower().find(indicator)
                    end_idx = min(start_idx + 30, len(line))
                    project_text = line[start_idx:end_idx].strip()
                    
                    entities.append({
                        "text": project_text,
                        "type": "PROJECT",
                        "relevance": 0.6,
                        "source": "heuristic"
                    })
        
        return entities
    
    def _get_related_entities(self, entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Get related entities from the knowledge base.
        
        Args:
            entities: List of entities to find relations for
            
        Returns:
            List of related entity dictionaries
        """
        # If we have a knowledge base API, use it
        if self.kb_api_url:
            try:
                response = requests.post(
                    f"{self.kb_api_url}/related-entities",
                    json={"entities": entities},
                    headers={"Content-Type": "application/json"}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return result.get("related_entities", [])
            except Exception as e:
                print(f"Error calling knowledge base API: {e}")
        
        # Return empty list if no API or error
        return []
    
    def _calculate_enhanced_priority(
        self,
        message: Dict[str, Any],
        thread: Optional[List[Dict[str, Any]]],
        knowledge_context: Dict[str, Any]
    ) -> Tuple[float, List[str]]:
        """Calculate enhanced priority score using knowledge context.
        
        Args:
            message: Message dictionary
            thread: Optional list of messages in the thread
            knowledge_context: Knowledge context dictionary
            
        Returns:
            Tuple of (priority_score, priority_reasons)
        """
        # Start with basic priority
        priority_score, priority_reasons = self._calculate_basic_priority(message)
        
        # Get entities from knowledge context
        direct_entities = knowledge_context.get("direct_entities", [])
        related_entities = knowledge_context.get("related_entities", [])
        
        # Check for high priority entities
        high_priority_person_found = False
        high_priority_project_found = False
        priority_term_found = False
        
        # Check direct entities
        for entity in direct_entities:
            entity_type = entity.get("type")
            entity_text = entity.get("text", "")
            relevance = entity.get("relevance", 0.5)
            
            if entity_type == "PERSON" and relevance > 0.7:
                priority_score += 0.2
                priority_reasons.append(f"Mentions important person: {entity_text}")
                high_priority_person_found = True
            
            elif entity_type == "PROJECT" and relevance > 0.7:
                priority_score += 0.2
                priority_reasons.append(f"Discusses important project: {entity_text}")
                high_priority_project_found = True
            
            elif entity_type == "TERM" and relevance > 0.8:
                priority_score += 0.1
                priority_reasons.append(f"Contains priority term: {entity_text}")
                priority_term_found = True
        
        # Check related entities if we haven't found priority entities yet
        if not (high_priority_person_found and high_priority_project_found and priority_term_found):
            for entity in related_entities:
                entity_type = entity.get("type")
                entity_text = entity.get("text", "")
                relevance = entity.get("relevance", 0.5)
                
                if entity_type == "PERSON" and relevance > 0.8 and not high_priority_person_found:
                    priority_score += 0.15
                    priority_reasons.append(f"Related to important person: {entity_text}")
                    high_priority_person_found = True
                
                elif entity_type == "PROJECT" and relevance > 0.8 and not high_priority_project_found:
                    priority_score += 0.15
                    priority_reasons.append(f"Related to important project: {entity_text}")
                    high_priority_project_found = True
        
        # Check thread characteristics
        if thread and len(thread) > 3:
            priority_score += min(0.1, 0.02 * len(thread))
            priority_reasons.append(f"Active conversation thread with {len(thread)} messages")
        
        # Cap the priority score at 1.0
        priority_score = min(1.0, priority_score)
        
        return priority_score, priority_reasons


# Cloud Function entry point
def process_emails(request) -> Dict[str, Any]:
    """Cloud Function entry point for processing emails.
    
    Args:
        request: HTTP request
        
    Returns:
        JSON response with processed emails
    """
    try:
        # Get request parameters
        request_json = request.get_json(silent=True) or {}
        
        days = request_json.get("days", 7)
        folder = request_json.get("folder", "inbox")
        top = request_json.get("top", 100)
        min_priority = request_json.get("min_priority", 0.0)
        search_query = request_json.get("search", None)
        
        # Get configuration from environment
        project_id = os.environ.get("PROJECT_ID")
        knowledge_bucket = os.environ.get("KNOWLEDGE_BUCKET")
        kb_api_url = os.environ.get("KB_API_URL")
        
        if not project_id or not knowledge_bucket:
            return {"error": "Missing required environment variables"}, 400
        
        # Initialize email processor
        processor = EmailProcessor(
            project_id=project_id,
            knowledge_bucket=knowledge_bucket,
            kb_api_url=kb_api_url
        )
        
        # Process emails based on request type
        if search_query:
            # Search and prioritize
            messages = processor.search_prioritized_messages(
                search_query, folder, top, min_priority
            )
        else:
            # Get prioritized messages
            messages = processor.get_prioritized_messages(
                days, folder, top, min_priority
            )
        
        if messages is None:
            return {"error": "Failed to retrieve messages"}, 500
        
        # Return results
        return {
            "messages": messages,
            "count": len(messages),
            "filter": {
                "days": days,
                "folder": folder,
                "top": top,
                "min_priority": min_priority,
                "search_query": search_query
            },
            "processing_time": datetime.now().isoformat()
        }
        
    except Exception as e:
        return {"error": f"Error processing emails: {str(e)}"}, 500


# Example usage
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Email processor")
    parser.add_argument("--project", required=True, help="Google Cloud project ID")
    parser.add_argument("--knowledge-bucket", required=True, help="GCS bucket for knowledge store")
    parser.add_argument("--kb-api-url", help="Knowledge base API URL")
    parser.add_argument("--days", type=int, default=7, help="Number of days to look back")
    parser.add_argument("--folder", default="inbox", help="Folder to get messages from")
    parser.add_argument("--count", type=int, default=10, help="Number of messages to return")
    parser.add_argument("--min-priority", type=float, default=0.0, help="Minimum priority score")
    parser.add_argument("--search", help="Search query for messages")
    parser.add_argument("--message-id", help="Get a specific message with knowledge context")
    
    args = parser.parse_args()
    
    # Initialize email processor
    processor = EmailProcessor(
        project_id=args.project,
        knowledge_bucket=args.knowledge_bucket,
        kb_api_url=args.kb_api_url
    )
    
    if args.message_id:
        # Get specific message with knowledge context
        message = processor.get_message_with_knowledge_context(args.message_id)
        
        if message:
            print(f"Message: {message['subject']}")
            print(f"From: {message['sender']['emailAddress']['name']}")
            print(f"Priority: {message['priority_score']:.2f}")
            print(f"Reasons: {', '.join(message['priority_reasons'])}")
            print("\nKnowledge Context:")
            print(f"  Direct Entities: {len(message['knowledge_context']['direct_entities'])}")
            print(f"  Related Entities: {len(message['knowledge_context']['related_entities'])}")
        else:
            print(f"Error: Message not found or not accessible")
    
    elif args.search:
        # Search and prioritize
        messages = processor.search_prioritized_messages(
            args.search, args.folder, args.count, args.min_priority
        )
        
        if messages:
            print(f"Found {len(messages)} messages matching '{args.search}'")
            for i, msg in enumerate(messages):
                sender = msg.get("sender", {}).get("emailAddress", {}).get("name", "Unknown")
                subject = msg.get("subject", "No subject")
                priority = msg.get("priority_score", 0.0)
                is_match = msg.get("query_match", False)
                print(f"{i+1}. [{priority:.2f}] {sender}: {subject} {'(match)' if is_match else ''}")
        else:
            print("No messages found or error occurred")
    
    else:
        # Get prioritized messages
        messages = processor.get_prioritized_messages(
            args.days, args.folder, args.count, args.min_priority
        )
        
        if messages:
            print(f"Found {len(messages)} prioritized messages")
            for i, msg in enumerate(messages):
                sender = msg.get("sender", {}).get("emailAddress", {}).get("name", "Unknown")
                subject = msg.get("subject", "No subject")
                priority = msg.get("priority_score", 0.0)
                print(f"{i+1}. [{priority:.2f}] {sender}: {subject}")
        else:
            print("No messages found or error occurred")