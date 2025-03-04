"""
Authentication helper for Email Intelligence Dashboard.
Provides browser-based authentication for Microsoft Graph API.
"""

import os
import webbrowser
import json
import time
import requests
from urllib.parse import urlencode, quote
import msal
import streamlit as st

def get_auth_url(client_id, redirect_uri, scopes):
    """Generate Microsoft authentication URL."""
    auth_url = f"https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": " ".join(scopes),
        "state": "12345"
    }
    return f"{auth_url}?{urlencode(params, quote_via=quote)}"

def open_auth_page(client_id, redirect_uri, scopes):
    """Open browser with Microsoft authentication URL."""
    auth_url = get_auth_url(client_id, redirect_uri, scopes)
    webbrowser.open(auth_url)
    return auth_url

def exchange_code_for_token(client_id, client_secret, redirect_uri, code):
    """Exchange authorization code for access and refresh tokens."""
    token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    payload = {
        "client_id": client_id,
        "scope": "https://graph.microsoft.com/.default",
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "client_secret": client_secret
    }
    response = requests.post(token_url, data=payload)
    return response.json()

def save_credentials(token_response, username=None):
    """Save tokens to a credentials file."""
    credentials = {
        "access_token": token_response.get("access_token"),
        "refresh_token": token_response.get("refresh_token"),
        "id_token": token_response.get("id_token"),
        "token_type": token_response.get("token_type"),
        "expires_in": token_response.get("expires_in"),
        "scope": token_response.get("scope"),
        "username": username,
        "timestamp": time.time()
    }
    
    # Get tenant ID from ID token
    if "id_token" in token_response:
        try:
            id_token_parts = token_response["id_token"].split('.')
            if len(id_token_parts) >= 2:
                import base64
                import json
                
                # Decode the payload (second part of the token)
                padding = '=' * (4 - len(id_token_parts[1]) % 4)
                payload = json.loads(base64.b64decode(id_token_parts[1] + padding).decode('utf-8'))
                
                # Extract tenant ID (tid) and preferred_username if available
                credentials["tenant_id"] = payload.get("tid")
                if not username and "preferred_username" in payload:
                    credentials["username"] = payload["preferred_username"]
        except Exception as e:
            print(f"Error parsing ID token: {e}")
    
    # Save to file
    os.makedirs(os.path.expanduser("~/.email_intelligence"), exist_ok=True)
    credentials_path = os.path.expanduser("~/.email_intelligence/ms_graph_credentials.json")
    with open(credentials_path, 'w') as f:
        json.dump(credentials, f)
        
    # Also save as environment variables for the session
    os.environ["MS_TENANT_ID"] = credentials.get("tenant_id", "")
    os.environ["MS_CLIENT_ID"] = token_response.get("client_id", "")
    if "refresh_token" in token_response:
        os.environ["MS_REFRESH_TOKEN"] = token_response["refresh_token"]
    
    return credentials

def load_credentials():
    """Load saved credentials if they exist."""
    credentials_path = os.path.expanduser("~/.email_intelligence/ms_graph_credentials.json")
    if os.path.exists(credentials_path):
        with open(credentials_path, 'r') as f:
            return json.load(f)
    return None

def refresh_token(client_id, client_secret, refresh_token):
    """Refresh access token using refresh token."""
    token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    payload = {
        "client_id": client_id,
        "scope": "https://graph.microsoft.com/.default",
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
        "client_secret": client_secret
    }
    response = requests.post(token_url, data=payload)
    return response.json()

def is_token_valid(credentials):
    """Check if the token is still valid."""
    if not credentials:
        return False
        
    # Check if the token is expired
    timestamp = credentials.get("timestamp", 0)
    expires_in = credentials.get("expires_in", 0)
    current_time = time.time()
    
    # Allow 5 minute buffer
    return current_time < (timestamp + expires_in - 300)

def get_user_profile(access_token):
    """Get user profile using Graph API."""
    headers = {
        'Authorization': f'Bearer {access_token}'
    }
    response = requests.get('https://graph.microsoft.com/v1.0/me', headers=headers)
    if response.status_code == 200:
        return response.json()
    return None

def streamlit_auth_flow():
    """Streamlit authentication flow for Microsoft Graph."""
    st.title("Microsoft Graph Authentication")
    
    # Check for existing credentials
    credentials = load_credentials()
    if credentials and is_token_valid(credentials):
        user_profile = get_user_profile(credentials.get("access_token"))
        if user_profile:
            st.success(f"Already authenticated as {user_profile.get('displayName')} ({user_profile.get('userPrincipalName')})")
            st.json(user_profile)
            
            if st.button("Logout"):
                os.remove(os.path.expanduser("~/.email_intelligence/ms_graph_credentials.json"))
                st.experimental_rerun()
                
            return credentials
    
    # Client ID and Redirect URI input
    client_id = st.text_input("Client ID", value=os.environ.get("MS_CLIENT_ID", ""))
    client_secret = st.text_input("Client Secret", type="password", value=os.environ.get("MS_CLIENT_SECRET", ""))
    redirect_uri = st.text_input("Redirect URI", value="http://localhost:8501/")
    
    # Authentication button
    if st.button("Authenticate with Microsoft") and client_id and redirect_uri:
        scopes = ["User.Read", "Mail.Read"]
        auth_url = get_auth_url(client_id, redirect_uri, scopes)
        
        st.markdown(f"""
        ### Instructions:
        1. Click the link below to open Microsoft login
        2. Login with your Microsoft account
        3. After login, you'll be redirected back with a code in the URL
        4. Copy the ENTIRE URL from your browser address bar
        5. Paste it below
        
        [Click to Login with Microsoft]({auth_url})
        """)
        
        # Get the authorization code from the redirect
        redirect_url = st.text_input("Paste the redirect URL here:")
        
        if redirect_url and "code=" in redirect_url:
            try:
                # Extract the code from the URL
                code = redirect_url.split("code=")[1].split("&")[0]
                
                # Exchange the code for tokens
                token_response = exchange_code_for_token(client_id, client_secret, redirect_uri, code)
                
                if "access_token" in token_response:
                    # Get user info
                    access_token = token_response["access_token"]
                    user_profile = get_user_profile(access_token)
                    
                    # Save the credentials
                    username = user_profile.get("userPrincipalName") if user_profile else None
                    credentials = save_credentials(token_response, username)
                    
                    st.success(f"Authentication successful! Logged in as {username}")
                    
                    # Show user profile
                    if user_profile:
                        st.json(user_profile)
                    
                    return credentials
                else:
                    st.error(f"Error getting tokens: {token_response.get('error_description', 'Unknown error')}")
            except Exception as e:
                st.error(f"Error processing authentication: {str(e)}")
    
    return None

if __name__ == "__main__":
    import streamlit.web.bootstrap
    streamlit.web.bootstrap.run("auth_helper.py", "", [], [])