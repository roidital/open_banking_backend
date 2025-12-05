from flask import Flask, request, jsonify, redirect, session
from flask_cors import CORS
import jwt
import time
import random
import string
import requests
from datetime import datetime, timedelta
import json
import os
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your-secret-key-change-in-production')
CORS(app)

# Temporary in-memory storage for POC (use Redis/database in production)
auth_states = {}  # {state: {user_id, nonce, timestamp}}
user_tokens = {}  # {user_id: {access_token, refresh_token, ...}}

# Moneyhub Configuration - SET THESE IN ENVIRONMENT VARIABLES
MONEYHUB_CLIENT_ID = os.environ.get('MONEYHUB_CLIENT_ID', 'your-client-id')
MONEYHUB_REDIRECT_URI = os.environ.get('MONEYHUB_REDIRECT_URI', 'https://your-backend.koyeb.app/callback')
MONEYHUB_IDENTITY_SERVER = os.environ.get('MONEYHUB_IDENTITY_SERVER', 'https://identity.moneyhub.co.uk')
MONEYHUB_API_SERVER = os.environ.get('MONEYHUB_API_SERVER', 'https://api.moneyhub.co.uk')

# Load your private key (store this securely - use environment variable or secret management)
# Generate keys: https://mkjwk.org/ or use ssh-keygen
PRIVATE_KEY_PEM = os.environ.get('MONEYHUB_PRIVATE_KEY', '''-----BEGIN PRIVATE KEY-----
YOUR_PRIVATE_KEY_HERE
-----END PRIVATE KEY-----''')

def generate_jti():
    """Generate unique JWT ID"""
    return ''.join(random.choice(string.ascii_lowercase) for i in range(32))

def generate_jwt(client_id, audience):
    """Generate JWT for client authentication"""
    iat = datetime.utcnow()
    exp = iat + timedelta(hours=1)
    
    payload = {
        "iss": client_id,
        "sub": client_id,
        "aud": audience,
        "iat": int(iat.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": generate_jti()
    }
    
    # Load private key
    private_key = serialization.load_pem_private_key(
        PRIVATE_KEY_PEM.encode(),
        password=None,
        backend=default_backend()
    )
    
    return jwt.encode(payload, private_key, algorithm="RS256")

def get_client_credentials_token(scope="accounts:read transactions:read:all"):
    """Get client credentials token for API access"""
    token_url = f"{MONEYHUB_IDENTITY_SERVER}/oidc/token"
    
    client_assertion = generate_jwt(MONEYHUB_CLIENT_ID, token_url)
    
    data = {
        "grant_type": "client_credentials",
        "client_id": MONEYHUB_CLIENT_ID,
        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
        "client_assertion": client_assertion,
        "scope": scope
    }
    
    response = requests.post(token_url, data=data)
    response.raise_for_status()
    return response.json()

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "service": "moneyhub-backend"})

@app.route('/auth/start', methods=['POST'])
def start_auth():
    """
    Start the authentication flow
    Android app calls this to get the authorization URL
    """
    try:
        # Get user_id from request (your app's internal user identifier)
        data = request.get_json()
        user_id = data.get('user_id')
        
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400
        
        # Generate state and nonce for security
        state = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
        nonce = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
        
        # Store in memory (in production, use Redis or database)
        auth_states[state] = {
            'user_id': user_id,
            'nonce': nonce,
            'timestamp': time.time()
        }
        
        # Build authorization URL
        from urllib.parse import urlencode
        
        # Get bank_id from request (optional, defaults to 'test' for test banks)
        bank_id = data.get('bank_id', 'test')
        
        auth_params = {
            "client_id": MONEYHUB_CLIENT_ID,
            "redirect_uri": MONEYHUB_REDIRECT_URI,
            "response_type": "code",
            "scope": f"openid id:{bank_id}",
            "state": state,
            "nonce": nonce
        }
        
        auth_url = f"{MONEYHUB_IDENTITY_SERVER}/oidc/auth"
        query_string = urlencode(auth_params)
        full_auth_url = f"{auth_url}?{query_string}"
        
        return jsonify({
            "authorization_url": full_auth_url,
            "state": state
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/callback', methods=['GET'])
def callback():
    """
    OAuth callback endpoint - Moneyhub redirects here after user authentication
    """
    try:
        code = request.args.get('code')
        state = request.args.get('state')
        
        if not code or not state:
            return "Missing authorization code or state", 400
        
        # Verify state
        session_data = auth_states.get(state)
        if not session_data:
            return f"Invalid state parameter. State: {state}, Available states: {list(auth_states.keys())}", 400
        
        user_id = session_data['user_id']
        nonce = session_data['nonce']
        
        # Exchange code for tokens
        token_url = f"{MONEYHUB_IDENTITY_SERVER}/oidc/token"
        client_assertion = generate_jwt(MONEYHUB_CLIENT_ID, token_url)
        
        token_data = {
            "grant_type": "authorization_code",
            "client_id": MONEYHUB_CLIENT_ID,
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": client_assertion,
            "code": code,
            "redirect_uri": MONEYHUB_REDIRECT_URI,
            "nonce": nonce
        }
        
        response = requests.post(token_url, data=token_data)
        response.raise_for_status()
        tokens = response.json()
        
        # Store tokens (in production, use secure database)
        user_tokens[user_id] = {
            'access_token': tokens.get('access_token'),
            'refresh_token': tokens.get('refresh_token'),
            'id_token': tokens.get('id_token'),
            'expires_at': time.time() + tokens.get('expires_in', 3600)
        }
        
        # Clean up state
        auth_states.pop(state, None)
        
        # Redirect to success page or deep link back to app
        return """
        <html>
            <body>
                <h2>Authentication Successful!</h2>
                <p>You can now close this window and return to the app.</p>
                <script>
                    // Try to close the window (works if opened by the app)
                    window.close();
                </script>
            </body>
        </html>
        """
    
    except Exception as e:
        return f"Authentication failed: {str(e)}", 500

@app.route('/api/accounts', methods=['GET'])
def get_accounts():
    """
    Get user's connected accounts
    Requires: user_id in query parameter
    """
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400
        
        # Get tokens from memory (in production, from database)
        tokens = user_tokens.get(user_id)
        if not tokens:
            return jsonify({"error": "User not authenticated"}), 401
        
        # Check if token expired
        if time.time() > tokens['expires_at']:
            return jsonify({"error": "Token expired, re-authentication needed"}), 401
        
        # Get accounts from Moneyhub
        headers = {
            "Authorization": f"Bearer {tokens['access_token']}"
        }
        
        response = requests.get(f"{MONEYHUB_API_SERVER}/v2.0/accounts", headers=headers)
        response.raise_for_status()
        
        return jsonify(response.json())
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/transactions', methods=['GET'])
def get_transactions():
    """
    Get user's transactions
    Query parameters:
    - user_id: Your app's user identifier (required)
    - start_date: Start date in YYYY-MM-DD format (optional)
    - end_date: End date in YYYY-MM-DD format (optional)
    - account_id: Specific account ID (optional)
    """
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400
        
        # Get tokens from memory (in production, from database)
        tokens = user_tokens.get(user_id)
        if not tokens:
            return jsonify({"error": "User not authenticated"}), 401
        
        # Check if token expired
        if time.time() > tokens['expires_at']:
            return jsonify({"error": "Token expired, re-authentication needed"}), 401
        
        # Build query parameters
        params = {}
        if request.args.get('start_date'):
            params['startDate'] = request.args.get('start_date')
        if request.args.get('end_date'):
            params['endDate'] = request.args.get('end_date')
        if request.args.get('account_id'):
            params['accountId'] = request.args.get('account_id')
        
        # Get transactions from Moneyhub
        headers = {
            "Authorization": f"Bearer {tokens['access_token']}"
        }
        
        response = requests.get(
            f"{MONEYHUB_API_SERVER}/v2.0/transactions",
            headers=headers,
            params=params
        )
        response.raise_for_status()
        
        return jsonify(response.json())
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/transactions/recent', methods=['GET'])
def get_recent_transactions():
    """
    Get last week's transactions (POC endpoint)
    Query parameters:
    - user_id: Your app's user identifier (required)
    """
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400
        
        # Calculate date range (last 7 days)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        
        # Get tokens from memory (in production, from database)
        tokens = user_tokens.get(user_id)
        if not tokens:
            return jsonify({"error": "User not authenticated"}), 401
        
        # Get transactions
        headers = {
            "Authorization": f"Bearer {tokens['access_token']}"
        }
        
        params = {
            'startDate': start_date.strftime('%Y-%m-%d'),
            'endDate': end_date.strftime('%Y-%m-%d')
        }
        
        response = requests.get(
            f"{MONEYHUB_API_SERVER}/v2.0/transactions",
            headers=headers,
            params=params
        )
        response.raise_for_status()
        
        transactions = response.json()
        
        return jsonify({
            "period": "last_7_days",
            "start_date": start_date.strftime('%Y-%m-%d'),
            "end_date": end_date.strftime('%Y-%m-%d'),
            "transactions": transactions
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/auth/status', methods=['GET'])
def auth_status():
    """
    Check if user is authenticated
    Query parameters:
    - user_id: Your app's user identifier (required)
    """
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    
    tokens = user_tokens.get(user_id)
    
    if not tokens:
        return jsonify({"authenticated": False})
    
    is_expired = time.time() > tokens['expires_at']
    
    return jsonify({
        "authenticated": not is_expired,
        "expires_at": tokens['expires_at']
    })

if __name__ == '__main__':
    # For development only - use a proper WSGI server in production
    app.run(host='0.0.0.0', port=5000, debug=False)

