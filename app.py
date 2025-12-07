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
import base64
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

# Normalize the private key format (handle both single-line and multi-line)
def normalize_private_key(key_str):
    """Normalize private key to proper PEM format"""
    # Remove any extra whitespace
    key_str = key_str.strip()
    
    # If it's single-line with \n, replace \n with actual newlines
    if '\\n' in key_str:
        key_str = key_str.replace('\\n', '\n')
    
    # Ensure proper PEM format
    if not key_str.startswith('-----BEGIN'):
        # Key might be just the base64 content
        key_str = f"-----BEGIN PRIVATE KEY-----\n{key_str}\n-----END PRIVATE KEY-----"
    
    return key_str

PRIVATE_KEY_PEM = normalize_private_key(PRIVATE_KEY_PEM)

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
    try:
        private_key = serialization.load_pem_private_key(
            PRIVATE_KEY_PEM.encode(),
            password=None,
            backend=default_backend()
        )
    except Exception as e:
        print(f"Error loading private key: {str(e)}")
        print(f"Key format (first 100 chars): {PRIVATE_KEY_PEM[:100]}")
        raise Exception(f"Failed to load private key: {str(e)}")
    
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

@app.route('/api/connections', methods=['GET'])
def get_connections():
    """
    Get list of available bank connections
    This returns all banks/financial institutions that can be connected
    """
    try:
        # Get client credentials token
        token_response = get_client_credentials_token(scope="connections:read")
        access_token = token_response.get('access_token')
        
        # Get connections list from Moneyhub
        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        
        response = requests.get(
            f"{MONEYHUB_API_SERVER}/v2.0/connections",
            headers=headers
        )
        response.raise_for_status()
        
        connections = response.json()
        
        # Filter to show only relevant info
        banks = []
        for conn in connections.get('data', []):
            banks.append({
                "id": conn.get('id'),
                "name": conn.get('name'),
                "country": conn.get('country'),
                "available": conn.get('available')
            })
        
        return jsonify({
            "total": len(banks),
            "banks": banks
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "service": "moneyhub-backend"})

@app.route('/test-flow', methods=['GET'])
def test_flow():
    """Test the full auth flow in browser"""
    user_id = "browser_test_user"
    
    # Generate state and nonce
    state_data = {
        'user_id': user_id,
        'random': ''.join(random.choices(string.ascii_letters + string.digits, k=16))
    }
    state = base64.urlsafe_b64encode(json.dumps(state_data).encode()).decode()
    nonce = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    
    # Store nonce
    auth_states[state] = {
        'nonce': nonce,
        'timestamp': time.time()
    }
    
    # Get bank_id (defaults to showing all banks)
    bank_id = None
    
    # Build auth URL
    from urllib.parse import urlencode
    
    if bank_id:
        scope = f"openid id:{bank_id}"
    else:
        scope = "openid"
    auth_params = {
        "client_id": MONEYHUB_CLIENT_ID,
        "redirect_uri": MONEYHUB_REDIRECT_URI,
        "response_type": "code id_token",  # Changed for production
        "scope": scope,
        "state": state,
        "nonce": nonce
    }
    
    auth_url = f"{MONEYHUB_IDENTITY_SERVER}/oidc/auth"
    query_string = urlencode(auth_params)
    full_auth_url = f"{auth_url}?{query_string}"
    
    # Show debug page
    return f"""
    <html>
        <head><title>Moneyhub Auth Test</title></head>
        <body>
            <h2>Debug Info:</h2>
            <p><strong>State created:</strong> {state}</p>
            <p><strong>States in memory:</strong> {list(auth_states.keys())}</p>
            <p><strong>User ID:</strong> {user_id}</p>
            <br>
            <a href="{full_auth_url}" style="padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px;">
                Click here to authenticate with Moneyhub
            </a>
            <br><br>
            <p><small>This keeps everything in the same browser session</small></p>
        </body>
    </html>
    """

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
        # Encode user_id into the state to survive server restarts
        state_data = {
            'user_id': user_id,
            'random': ''.join(random.choices(string.ascii_letters + string.digits, k=16))
        }
        state = base64.urlsafe_b64encode(json.dumps(state_data).encode()).decode()
        nonce = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
        
        # Store nonce separately (still needed for OAuth validation)
        auth_states[state] = {
            'nonce': nonce,
            'timestamp': time.time()
        }
        
        # Build authorization URL
        from urllib.parse import urlencode
        
        # Get bank_id from request
        # For production: use specific bank IDs (you'll need to get these from Moneyhub)
        # For sandbox: use 'test'
        # If not provided, show all available banks
        bank_id = data.get('bank_id', None)
        
        # Build scope based on bank_id
        if bank_id:
            scope = f"openid id:{bank_id}"
        else:
            # No bank_id = show all available banks to user
            scope = "openid"
        
        auth_params = {
            "client_id": MONEYHUB_CLIENT_ID,
            "redirect_uri": MONEYHUB_REDIRECT_URI,
            "response_type": "code id_token",  # Changed for production
            "scope": scope,
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
    For PRODUCTION: params come in hash fragment, so we need to handle that with JS
    For SANDBOX: params come in query string
    """
    try:
        # Check if we have query params (sandbox mode or after JS redirect)
        code = request.args.get('code')
        state = request.args.get('state')
        id_token = request.args.get('id_token')  # Production sends this too
        
        # If no query params, return HTML to extract from hash fragment (production mode)
        if not code or not state:
            return """
            <!DOCTYPE html>
            <html>
              <head><title>Completing authentication...</title></head>
              <body>
                <h2>Completing authentication...</h2>
                <p>Please wait...</p>
                <script>
                  function extractHash() {
                    // Check if we have hash fragment
                    if (window.location.hash) {
                      // Convert hash to query params and reload
                      var newUrl = window.location.href.split('#')[0] + '?' + window.location.hash.substring(1);
                      window.location = newUrl;
                    } else if (!window.location.search) {
                      // No hash and no query params = something went wrong
                      document.body.innerHTML = '<h2>Error</h2><p>Missing authentication parameters</p>';
                    }
                  }
                  extractHash();
                </script>
              </body>
            </html>
            """
        
        # Decode state to get user_id
        try:
            state_data = json.loads(base64.urlsafe_b64decode(state.encode()).decode())
            user_id = state_data.get('user_id')
        except Exception as e:
            return f"Invalid state encoding: {str(e)}", 400
        
        # Try to get nonce from storage, but continue even if not found
        session_data = auth_states.get(state)
        if session_data:
            nonce = session_data['nonce']
            # Clean up state
            auth_states.pop(state, None)
        else:
            # Server restarted - generate a new nonce
            # This is less secure but allows the flow to continue for POC
            nonce = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
        
        # Exchange code for tokens
        token_url = f"{MONEYHUB_IDENTITY_SERVER}/oidc/token"
        client_assertion = generate_jwt(MONEYHUB_CLIENT_ID, token_url)
        
        token_data = {
            "grant_type": "authorization_code",
            "client_id": MONEYHUB_CLIENT_ID,
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": client_assertion,
            "code": code,
            "redirect_uri": MONEYHUB_REDIRECT_URI
        }
        
        # Add id_token if present (required for production)
        if id_token:
            token_data["id_token"] = id_token
        
        # Add nonce if we have it
        if session_data:
            nonce = session_data['nonce']
            token_data["nonce"] = nonce
        
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





########################################################
@app.route('/api/keys', methods=['GET'])
def get_api_keys():
    """
    Endpoint to securely serve API keys to the mobile app
    
    Optional: Add authentication to verify requests are from your app
    """
    
    # Optional: Check for authentication token
    auth_token = request.headers.get('Authorization')
    expected_token = os.environ.get('API_SECRET_TOKEN')
    
    # Uncomment this block if you want to require authentication:
    # if expected_token and auth_token != f"Bearer {expected_token}":
    #     return jsonify({"error": "Unauthorized"}), 401
    
    # Retrieve API keys from environment variables
    google_translate_key = os.environ.get('GOOGLE_TRANSLATE_API_KEY')
    gemini_key = os.environ.get('GEMINI_API_KEY')
    
    # Check if all keys are available
    if not google_translate_key or not gemini_key:
        return jsonify({
            "error": "API keys not configured on server"
        }), 500
    
    # Return the keys
    return jsonify({
        "google_translate_key": google_translate_key,
        "gemini_key": gemini_key
    }), 200

if __name__ == '__main__':
    # For development only - use a proper WSGI server in production
    app.run(host='0.0.0.0', port=5000, debug=False)

