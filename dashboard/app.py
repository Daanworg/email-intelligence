"""
Email Intelligence Dashboard with Microsoft Graph Authentication
Visualizes prioritized emails from your mailbox
"""

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import json
import sys
import os
import requests

# Add parent directory to path so we can import the test script
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
import test_email_intelligence

# Import authentication helper
try:
    from auth_helper import streamlit_auth_flow, load_credentials, is_token_valid, get_user_profile
except ImportError:
    st.error("Authentication module not found. Please ensure auth_helper.py exists.")
    st.stop()

# Set up page configuration
st.set_page_config(page_title="Email Intelligence Dashboard", layout="wide")

# Check for authentication in sidebar
st.sidebar.title("Email Intelligence")

# Add auth pages
with st.sidebar:
    auth_tab, help_tab = st.tabs(["Authentication", "Help"])
    
    with auth_tab:
        # Check for existing credentials
        credentials = load_credentials()
        if credentials and is_token_valid(credentials):
            user_profile = get_user_profile(credentials.get("access_token"))
            if user_profile:
                st.success(f"Authenticated as {user_profile.get('displayName')}")
                
                if st.button("Logout", key="logout_button"):
                    os.remove(os.path.expanduser("~/.email_intelligence/ms_graph_credentials.json"))
                    st.experimental_rerun()
        else:
            st.warning("Not authenticated with Microsoft Graph")
            if st.button("Authenticate Now"):
                st.session_state.show_auth = True
                # Auto-launch authentication immediately
                webbrowser.open("http://localhost:8501/")
    
    with help_tab:
        st.markdown("""
        ## Help
        
        This dashboard connects to Microsoft 365 to intelligently prioritize your emails.
        
        ### First-time setup:
        1. Click the "Authenticate Now" button
        2. Sign in with your Microsoft account
        3. Copy the callback URL and paste it back in the app
        
        ### Using the dashboard:
        - Adjust filters in the sidebar
        - View prioritized emails
        - Check knowledge context
        - Use action buttons for common tasks
        """)
        
    # Configuration section (only if authenticated)
    if credentials and is_token_valid(credentials):
        st.header("Filters")
        days = st.slider("Days to look back", 1, 30, 7)
        min_priority = st.slider("Minimum priority", 0.0, 1.0, 0.3, 0.1)
        folder = st.selectbox("Email folder", ["inbox", "sent", "archive", "drafts"])
        data_source = st.radio("Data Source", ["Demo Data", "Microsoft Graph API"])
        
        # API connection (for when using real data)
        if data_source == "Microsoft Graph API":
            st.subheader("API Connection")
            api_url = st.text_input("Email Processor API URL", 
                                    value=os.environ.get("EMAIL_PROCESSOR_API", ""))
            kb_api_url = st.text_input("Knowledge Base API URL",
                                       value=os.environ.get("KB_API_URL", ""))

# Check if auth flow should be shown
if hasattr(st.session_state, 'show_auth') and st.session_state.show_auth:
    with st.expander("Microsoft Graph Authentication", expanded=True):
        credentials = streamlit_auth_flow()
        if credentials:
            st.session_state.show_auth = False
            st.experimental_rerun()

# Main dashboard
st.title("Email Intelligence Dashboard")

# Check if we're authenticated before showing main content
credentials = load_credentials()
if not credentials or not is_token_valid(credentials):
    if not hasattr(st.session_state, 'show_auth') or not st.session_state.show_auth:
        st.warning("Please authenticate with Microsoft Graph to use this dashboard")
        if st.button("Authenticate Now", key="main_auth_button"):
            st.session_state.show_auth = True
            # Auto-launch authentication immediately
            webbrowser.open("http://localhost:8501/")
            st.experimental_rerun()
    
    # Show demo mode option
    if st.checkbox("Continue in Demo Mode"):
        st.caption("DEMO MODE - Using simulated data")
    else:
        # If not authenticated and not in demo mode, stop here
        if not hasattr(st.session_state, 'show_auth') or not st.session_state.show_auth:
            st.stop()
else:
    user_profile = get_user_profile(credentials.get("access_token"))
    if user_profile:
        st.caption(f"Connected to Microsoft 365 as {user_profile.get('displayName')} ({user_profile.get('userPrincipalName')})")
    
    # Check if we want to use real data
    use_real_data = 'data_source' in locals() and data_source == "Microsoft Graph API" and 'api_url' in locals() and api_url

# Get real data from API if authenticated and configured
def get_real_emails(api_url, access_token, days, folder, min_priority):
    """Get real emails from Microsoft Graph API via our processor."""
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {access_token}'
    }
    
    data = {
        "days": days,
        "folder": folder,
        "min_priority": min_priority,
        "top": 100
    }
    
    try:
        response = requests.post(api_url, headers=headers, json=data)
        if response.status_code == 200:
            return response.json().get("messages", [])
        else:
            st.error(f"API Error: {response.status_code} - {response.text}")
            return []
    except Exception as e:
        st.error(f"Connection Error: {str(e)}")
        return []

# Generate sample data for demo
def get_sample_emails(min_priority):
    """Generate sample data for demo purposes."""
    # Get sample data from our test script
    thread, urgent_emails, low_priority_emails = test_email_intelligence.create_sample_emails()
    
    # Process all emails with our existing functionality
    all_emails = thread + urgent_emails + low_priority_emails
    processed_emails = []
    
    for message in all_emails:
        # Get text from message
        subject = message.get("subject", "")
        body = message.get("bodyPreview", "")
        text = f"Subject: {subject}\n\n{body}"
        
        # Extract entities
        entities = test_email_intelligence.extract_entities_from_text(text)
        
        # Create knowledge context
        knowledge_context = {
            "direct_entities": entities,
            "related_entities": []
        }
        
        # For project emails, add some related entities
        if "project" in subject.lower() or "project" in body.lower():
            knowledge_context["related_entities"] = [
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
        
        # Calculate priority - for thread messages, use the thread for context
        if message.get("conversationId") == "thread1":
            priority_score, priority_reasons = test_email_intelligence.calculate_enhanced_priority(
                message, thread, knowledge_context
            )
        else:
            priority_score, priority_reasons = test_email_intelligence.calculate_enhanced_priority(
                message, [], knowledge_context
            )
        
        # Add priority info to message
        message["priority_score"] = priority_score
        message["priority_reasons"] = priority_reasons
        message["knowledge_context"] = knowledge_context
        
        processed_emails.append(message)
    
    # Generate 20 more random emails with varying priorities
    now = datetime.now().astimezone()
    import random
    for i in range(20):
        age_hours = random.uniform(0, 24*7)  # Up to 7 days old
        importance = random.choice(["normal", "normal", "normal", "high"])
        has_attachments = random.choice([True, False, False, False])
        
        # Create a message
        message = {
            "id": f"random-msg-{i}",
            "subject": random.choice([
                "Weekly Team Update", 
                "Meeting Notes", 
                "Question about timeline",
                "Status update",
                "New project proposal",
                "Budget review",
                "Client feedback",
                "System notification"
            ]),
            "sender": {
                "emailAddress": {
                    "name": random.choice([
                        "Jane Doe", 
                        "Robert Johnson", 
                        "Emma Smith", 
                        "David Wilson",
                        "Marketing Team",
                        "IT Support",
                        "Finance Department",
                        "Customer Service"
                    ]),
                    "address": "person@example.com"
                }
            },
            "receivedDateTime": (now - timedelta(hours=age_hours)).isoformat(),
            "bodyPreview": "This is a sample message body.",
            "conversationId": f"random-thread-{i//3}",
            "importance": importance,
            "hasAttachments": has_attachments
        }
        
        # Calculate basic priority
        priority_score, priority_reasons = test_email_intelligence.calculate_basic_priority(message)
        
        # Add priority info to message
        message["priority_score"] = priority_score
        message["priority_reasons"] = priority_reasons
        message["knowledge_context"] = {
            "direct_entities": [],
            "related_entities": []
        }
        
        processed_emails.append(message)
    
    # Filter by priority
    filtered_emails = [msg for msg in processed_emails if msg["priority_score"] >= min_priority]
    
    # Sort by priority
    filtered_emails.sort(key=lambda x: x["priority_score"], reverse=True)
    
    return filtered_emails

# Load data
with st.spinner("Loading email data..."):
    if credentials and is_token_valid(credentials) and 'use_real_data' in locals() and use_real_data:
        messages = get_real_emails(api_url, credentials.get("access_token"), days, folder, min_priority)
        if not messages:
            st.warning("Could not retrieve real data from API. Falling back to demo data.")
            messages = get_sample_emails(min_priority)
    else:
        messages = get_sample_emails(min_priority)

# Only continue if we have messages
if messages:
    # Summary metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Emails", len(messages))
    with col2:
        high_priority = sum(1 for msg in messages if msg["priority_score"] >= 0.7)
        st.metric("High Priority (≥0.7)", high_priority)
    with col3:
        avg_priority = sum(msg["priority_score"] for msg in messages) / len(messages) if messages else 0
        st.metric("Average Priority", f"{avg_priority:.2f}")
    
    # Create DataFrame for visualization
    emails_df = pd.DataFrame([
        {
            "id": msg.get("id"),
            "subject": msg.get("subject"),
            "sender": msg.get("sender", {}).get("emailAddress", {}).get("name", "Unknown"),
            "received": datetime.fromisoformat(msg.get("receivedDateTime").replace("Z", "+00:00")) if "Z" in msg.get("receivedDateTime", "") else datetime.fromisoformat(msg.get("receivedDateTime", datetime.now().isoformat())),
            "priority": msg.get("priority_score", 0)
        }
        for msg in messages
    ])
    
    # Visualizations
    st.subheader("Priority Distribution")
    fig = px.histogram(emails_df, x="priority", nbins=10, title="Email Priority Distribution")
    st.plotly_chart(fig)
    
    st.subheader("Email Timeline")
    timeline_fig = px.scatter(
        emails_df, 
        x="received", 
        y="priority",
        color="priority",
        hover_data=["subject", "sender"],
        size=[p+0.3 for p in emails_df["priority"]],  # Add 0.3 to make points more visible
        color_continuous_scale="RdYlGn_r",  # Red for high priority
        title="Email Priority Timeline"
    )
    st.plotly_chart(timeline_fig)
    
    # Priority email list
    st.subheader("Prioritized Emails")
    for i, msg in enumerate(messages):
        with st.expander(
            f"{i+1}. [{msg['priority_score']:.2f}] {msg['subject']} - From: {msg['sender']['emailAddress']['name']}"
        ):
            st.write(f"**From:** {msg['sender']['emailAddress']['name']} ({msg['sender']['emailAddress'].get('address', '')})")
            st.write(f"**Received:** {msg.get('receivedDateTime')}")
            st.write(f"**Priority Reasons:** {', '.join(msg.get('priority_reasons', []))}")
            st.write(f"**Preview:** {msg.get('bodyPreview', '')}")
            
            # If message has entities from knowledge base
            if "knowledge_context" in msg and (msg["knowledge_context"].get("direct_entities") or msg["knowledge_context"].get("related_entities")):
                st.write("**Knowledge Context:**")
                entities = msg["knowledge_context"].get("direct_entities", [])
                if entities:
                    st.write("- Direct Entities: " + ", ".join([f"{e['text']} ({e['type']})" for e in entities]))
                
                related = msg["knowledge_context"].get("related_entities", [])
                if related:
                    st.write("- Related Entities: " + ", ".join([f"{e['text']} ({e['type']})" for e in related]))
    
    # Add action buttons for demonstration
    st.subheader("Actions")
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Process New Documents"):
            st.success("Started processing 5 new documents")
    with col2:
        if st.button("Sync with Email"):
            st.success("Email synchronization complete")
    with col3:
        if st.button("Update Knowledge Base"):
            st.success("Knowledge base updated with new entities")
else:
    st.info("No emails found matching your criteria. Try adjusting the minimum priority or date range.")