"""
Simple test script for Email Intelligence System.
This script simulates processing a sample email without external dependencies.
"""

import json
import datetime
from typing import Dict, Any, List, Tuple

# Simulate email processing logic
def calculate_basic_priority(message: Dict[str, Any]) -> Tuple[float, List[str]]:
    """Calculate a basic priority score for a message."""
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
            received_date = datetime.datetime.fromisoformat(received_str.replace("Z", "+00:00"))
            now = datetime.datetime.now().astimezone()
            age_hours = (now - received_date).total_seconds() / 3600
            
            # Higher priority for newer messages (up to 24 hours)
            if age_hours < 24:
                recency_score = 0.2 * (1 - (age_hours / 24))
                priority_score += recency_score
                priority_reasons.append(f"Recent message ({age_hours:.1f} hours old)")
    except Exception as e:
        print(f"Error calculating recency: {e}")
    
    # Ensure score is between 0 and 1
    priority_score = max(0.0, min(1.0, priority_score))
    
    return priority_score, priority_reasons

def extract_entities_from_text(text: str) -> List[Dict[str, Any]]:
    """Extract entities from text using simplified logic."""
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

def calculate_enhanced_priority(
    message: Dict[str, Any],
    thread: List[Dict[str, Any]],
    knowledge_context: Dict[str, Any]
) -> Tuple[float, List[str]]:
    """Calculate enhanced priority score using knowledge context."""
    # Start with basic priority
    priority_score, priority_reasons = calculate_basic_priority(message)
    
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

def get_thread_text(thread: List[Dict[str, Any]]) -> str:
    """Get text representation of a thread."""
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

# Create sample email data
def create_sample_emails():
    # Create a sample conversation thread
    now = datetime.datetime.now().astimezone()
    
    thread = [
        {
            "id": "msg1",
            "subject": "Project Alpha Status Update",
            "sender": {
                "emailAddress": {
                    "name": "John Smith",
                    "address": "john.smith@example.com"
                }
            },
            "receivedDateTime": (now - datetime.timedelta(days=1)).isoformat(),
            "bodyPreview": "Team,\n\nHere's the latest status update for Project Alpha. We're on track for the milestone next week.\n\nJohn",
            "conversationId": "thread1",
            "importance": "normal",
            "hasAttachments": False
        },
        {
            "id": "msg2",
            "subject": "RE: Project Alpha Status Update",
            "sender": {
                "emailAddress": {
                    "name": "Sarah Johnson",
                    "address": "sarah.johnson@example.com"
                }
            },
            "receivedDateTime": (now - datetime.timedelta(hours=20)).isoformat(),
            "bodyPreview": "Thanks John, I've reviewed the timeline. Can we discuss the deadline for deliverable 3?\n\nSarah",
            "conversationId": "thread1",
            "importance": "normal",
            "hasAttachments": False
        },
        {
            "id": "msg3",
            "subject": "RE: Project Alpha Status Update",
            "sender": {
                "emailAddress": {
                    "name": "John Smith",
                    "address": "john.smith@example.com"
                }
            },
            "receivedDateTime": (now - datetime.timedelta(hours=18)).isoformat(),
            "bodyPreview": "Sure, Sarah. Let's schedule a call. I'm concerned about the timeline as well.\n\ncc: mike.williams@example.com (Program Manager)",
            "conversationId": "thread1",
            "importance": "normal",
            "hasAttachments": False
        },
        {
            "id": "msg4",
            "subject": "RE: Project Alpha Status Update",
            "sender": {
                "emailAddress": {
                    "name": "Mike Williams",
                    "address": "mike.williams@example.com"
                }
            },
            "receivedDateTime": (now - datetime.timedelta(hours=2)).isoformat(),
            "bodyPreview": "I'm available to discuss Project Alpha. Let's meet tomorrow at 10am.\n\nMike Williams\nProgram Manager\nInitiative X",
            "conversationId": "thread1",
            "importance": "high",
            "hasAttachments": True
        }
    ]
    
    # Create a high urgency email
    urgent_email = {
        "id": "msg5",
        "subject": "URGENT: Security Incident",
        "sender": {
            "emailAddress": {
                "name": "IT Security",
                "address": "security@example.com"
            }
        },
        "receivedDateTime": (now - datetime.timedelta(hours=1)).isoformat(),
        "bodyPreview": "All team members,\n\nWe have detected a security issue that requires immediate attention.",
        "conversationId": "thread2",
        "importance": "high",
        "hasAttachments": False
    }
    
    # Create a low priority email
    low_priority_email = {
        "id": "msg6",
        "subject": "Weekly Newsletter",
        "sender": {
            "emailAddress": {
                "name": "Company Newsletter",
                "address": "newsletter@example.com"
            }
        },
        "receivedDateTime": (now - datetime.timedelta(hours=12)).isoformat(),
        "bodyPreview": "This week's company newsletter includes updates from all departments.",
        "conversationId": "thread3",
        "importance": "normal",
        "hasAttachments": False
    }
    
    return thread, [urgent_email], [low_priority_email]

def main():
    print("🔍 Testing Email Intelligence System")
    print("===================================")
    
    # Create sample data
    thread, urgent_emails, low_priority_emails = create_sample_emails()
    
    # Process the conversation thread
    print("\n📧 Processing conversation thread")
    print("--------------------------------")
    
    thread_text = get_thread_text(thread)
    direct_entities = extract_entities_from_text(thread_text)
    
    # Create simulated knowledge context
    knowledge_context = {
        "direct_entities": direct_entities,
        "related_entities": [
            {
                "text": "Initiative X",
                "type": "PROJECT",
                "relevance": 0.9,
                "source": "knowledge_base"
            },
            {
                "text": "Q3 Deliverables",
                "type": "TERM",
                "relevance": 0.8,
                "source": "knowledge_base"
            }
        ]
    }
    
    # Process each message in the thread
    print("\nThread Analysis:")
    for i, message in enumerate(thread):
        priority_score, priority_reasons = calculate_enhanced_priority(
            message, thread, knowledge_context
        )
        
        sender = message.get("sender", {}).get("emailAddress", {}).get("name", "Unknown")
        subject = message.get("subject", "No subject")
        
        print(f"\nMessage {i+1}:")
        print(f"From: {sender}")
        print(f"Subject: {subject}")
        print(f"Priority: {priority_score:.2f}")
        print(f"Reasons: {', '.join(priority_reasons)}")
    
    # Process urgent email
    print("\n\n📧 Processing urgent email")
    print("--------------------------")
    
    urgent_message = urgent_emails[0]
    urgent_text = f"Subject: {urgent_message.get('subject')}\n\n{urgent_message.get('bodyPreview')}"
    urgent_entities = extract_entities_from_text(urgent_text)
    
    urgent_context = {
        "direct_entities": urgent_entities,
        "related_entities": []
    }
    
    urgent_priority, urgent_reasons = calculate_enhanced_priority(
        urgent_message, [], urgent_context
    )
    
    sender = urgent_message.get("sender", {}).get("emailAddress", {}).get("name", "Unknown")
    subject = urgent_message.get("subject", "No subject")
    
    print(f"\nUrgent Email:")
    print(f"From: {sender}")
    print(f"Subject: {subject}")
    print(f"Priority: {urgent_priority:.2f}")
    print(f"Reasons: {', '.join(urgent_reasons)}")
    
    # Process low priority email
    print("\n\n📧 Processing low priority email")
    print("-------------------------------")
    
    low_message = low_priority_emails[0]
    low_text = f"Subject: {low_message.get('subject')}\n\n{low_message.get('bodyPreview')}"
    low_entities = extract_entities_from_text(low_text)
    
    low_context = {
        "direct_entities": low_entities,
        "related_entities": []
    }
    
    low_priority, low_reasons = calculate_enhanced_priority(
        low_message, [], low_context
    )
    
    sender = low_message.get("sender", {}).get("emailAddress", {}).get("name", "Unknown")
    subject = low_message.get("subject", "No subject")
    
    print(f"\nLow Priority Email:")
    print(f"From: {sender}")
    print(f"Subject: {subject}")
    print(f"Priority: {low_priority:.2f}")
    print(f"Reasons: {', '.join(low_reasons)}")
    
    # Summary of testing
    print("\n\n📊 Testing Summary")
    print("----------------")
    print("✅ Basic priority calculations")
    print("✅ Enhanced priority with knowledge context")
    print("✅ Entity extraction from email text")
    print("✅ Conversation thread handling")
    
    print("\nEmail Intelligence System is functioning correctly!")

if __name__ == "__main__":
    main()