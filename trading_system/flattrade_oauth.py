#!/usr/bin/env python3
"""
Flattrade OAuth Authentication
Provides OAuth flow for getting access token from Flattrade
"""

from flask import Flask, request, redirect, jsonify, session
import requests
import json
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.urandom(24)  # For session management

# Flattrade OAuth Configuration
FLATTRADE_CLIENT_ID = "flattrade"  # Usually provided by Flattrade
FLATTRADE_REDIRECT_URI = "http://localhost:5000/oauth/callback"
FLATTRADE_AUTH_URL = "https://piconnect.flattrade.in/PiConnectAPI/oauth/authorize"
FLATTRADE_TOKEN_URL = "https://piconnect.flattrade.in/PiConnectAPI/oauth/token"

# Token storage file
TOKEN_FILE = "/opt/nifty_monitor/flattrade_token.json"

# Global token storage for the monitoring system
_access_token = None
_user_id = None


def save_token(token: str, user_id: str = None):
    """Save token to file and memory"""
    global _access_token, _user_id
    _access_token = token
    _user_id = user_id
    
    # Save to file
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, 'w') as f:
        json.dump({
            'token': token,
            'user_id': user_id
        }, f)
    logger.info(f"Token saved for user: {user_id}")


def load_token():
    """Load token from file"""
    global _access_token, _user_id
    
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r') as f:
                data = json.load(f)
                _access_token = data.get('token')
                _user_id = data.get('user_id')
                return _access_token, _user_id
        except:
            pass
    return None, None


def get_token() -> tuple:
    """Get current token and user_id"""
    if _access_token:
        return _access_token, _user_id
    return load_token()


@app.route('/')
def index():
    """Show OAuth login link"""
    return """
    <html>
    <head><title>Flattrade OAuth Login</title></head>
    <body style="font-family: Arial; padding: 40px; text-align: center;">
        <h1>🔐 Flattrade OAuth Login</h1>
        <p>Click the button below to login to Flattrade:</p>
        <br>
        <a href="/login" style="background: #4CAF50; color: white; padding: 15px 30px; 
           text-decoration: none; border-radius: 5px; font-size: 18px;">
            🔗 Login with Flattrade
        </a>
        <br><br><hr>
        <h3>After login, you'll be redirected back with your token.</h3>
        <p>Then you can start the monitor with: /monitorstart</p>
    </body>
    </html>
    """


@app.route('/login')
def login():
    """Redirect to Flattrade OAuth login page"""
    # For Flattrade, they use a session-based auth
    # This creates a special login URL
    
    # Build authorization URL - Flattrade uses a form-based OAuth
    auth_url = f"https://piconnect.flattrade.in/PiConnectAPI/api/login"
    
    # Store return URL in session
    session['oauth_state'] = "authorized"
    
    # Redirect to Flattrade login
    return redirect(auth_url)


@app.route('/oauth/callback')
def oauth_callback():
    """Handle OAuth callback with authorization code"""
    # Check for authorization code or token
    code = request.args.get('code')
    token = request.args.get('access_token')
    error = request.args.get('error')
    
    if error:
        return f"""
        <html><body style="font-family: Arial; padding: 40px; text-align: center;">
            <h2 style="color: red;">❌ Error: {error}</h2>
            <p>{request.args.get('error_description', '')}</p>
            <br><a href="/">Try Again</a>
        </body></html>
        """
    
    if token:
        # Direct token in URL
        save_token(token, request.args.get('user_id'))
        return redirect('/success')
    
    if code:
        # Exchange code for token
        try:
            resp = requests.post(FLATTRADE_TOKEN_URL, data={
                'grant_type': 'authorization_code',
                'code': code,
                'client_id': FLATTRADE_CLIENT_ID,
                'redirect_uri': FLATTRADE_REDIRECT_URI
            })
            
            if resp.status_code == 200:
                token_data = resp.json()
                access_token = token_data.get('access_token')
                if access_token:
                    save_token(access_token, token_data.get('user_id'))
                    return redirect('/success')
        except Exception as e:
            logger.error(f"Token exchange failed: {e}")
    
    # If no direct token, show login form
    return f"""
    <html>
    <head><title>Enter Flattrade Credentials</title></head>
    <body style="font-family: Arial; padding: 40px; text-align: center;">
        <h1>🔐 Enter Flattrade Credentials</h1>
        <p>Enter your Flattrade Pi credentials to get session token:</p>
        <form action="/submit_credentials" method="POST" style="display: inline-block; text-align: left;">
            <label>User ID:<br>
            <input type="text" name="user_id" required style="padding: 10px; width: 200px;"></label><br><br>
            <label>Password:<br>
            <input type="password" name="password" required style="padding: 10px; width: 200px;"></label><br><br>
            <button type="submit" style="background: #4CAF50; color: white; padding: 10px 20px; 
                    border: none; border-radius: 5px; cursor: pointer;">
                Login
            </button>
        </form>
    </body>
    </html>
    """


@app.route('/submit_credentials', methods=['POST'])
def submit_credentials():
    """Process login form and get session token"""
    user_id = request.form.get('user_id')
    password = request.form.get('password')
    
    # Call Flattrade login API
    try:
        url = "https://piconnect.flattrade.in/PiConnectAPI/api/login"
        data = {
            "uid": user_id,
            "pwd": password,
            "factor2": "",
            "du": "192.168.1.1",
            "appkey": "",  # App key if available
            "imei": "",
            "ip": "192.168.1.1",
            "os": "WINDOWS",
            "lang": "en"
        }
        
        resp = requests.post(url, json=data, timeout=15)
        
        if resp.status_code == 200:
            result = resp.json()
            if result.get('stat') == 'Ok':
                # Get session token
                sess_token = result.get('sess')
                if sess_token:
                    save_token(sess_token, user_id)
                    return redirect('/success')
            elif result.get('stat') == 'NotOk':
                error_msg = result.get('emsg', 'Login failed')
                return f"""
                <html><body style="font-family: Arial; padding: 40px; text-align: center;">
                    <h2 style="color: red;">❌ Login Failed</h2>
                    <p>{error_msg}</p>
                    <br><a href="/">Try Again</a>
                </body></html>
                """
    except Exception as e:
        return f"""
        <html><body style="font-family: Arial; padding: 40px; text-align: center;">
            <h2 style="color: red;">❌ Error: {str(e)}</h2>
            <br><a href="/">Try Again</a>
        </body></html>
        """
    
    return """
    <html><body style="font-family: Arial; padding: 40px; text-align: center;">
        <h2>❌ Login Failed</h2>
        <p>Please check your credentials and try again.</p>
        <br><a href="/">Try Again</a>
    </body></html>
    """


@app.route('/success')
def success():
    """Show success page after login"""
    token, user_id = get_token()
    return f"""
    <html>
    <head><title>Login Successful</title></head>
    <body style="font-family: Arial; padding: 40px; text-align: center;">
        <h1 style="color: green;">✅ Login Successful!</h1>
        <p>User ID: {user_id}</p>
        <p>Token saved: {token[:20] if token else 'None'}...</p>
        <br><hr>
        <h2>Now start your Telegram bot:</h2>
        <pre style="background: #f0f0f0; padding: 20px; border-radius: 5px;">
/token {user_id} {token}
/monitorstart
        </pre>
        <br>
        <p>Or restart your bot to use the new token.</p>
    </body>
    </html>
    """


@app.route('/status')
def status():
    """Check if token is available"""
    token, user_id = get_token()
    if token:
        return jsonify({
            'status': 'connected',
            'user_id': user_id,
            'token_prefix': token[:10] + '...' if len(token) > 10 else token
        })
    return jsonify({'status': 'not_connected'})


@app.route('/token')
def get_current_token():
    """API endpoint to get current token"""
    token, user_id = get_token()
    if token:
        return jsonify({'token': token, 'user_id': user_id})
    return jsonify({'error': 'No token available'}), 401


# Standalone OAuth server
if __name__ == '__main__':
    # Check if token already exists
    load_token()
    
    print("=" * 50)
    print("🌐 Flattrade OAuth Server")
    print("=" * 50)
    print("\n1. Open this URL in your browser:")
    print("   http://localhost:5000")
    print("\n2. Login with your Flattrade credentials")
    print("\n3. After login, copy the token and use in Telegram:")
    print("   /token USER_ID TOKEN")
    print("\n" + "=" * 50)
    
    app.run(host='0.0.0.0', port=5000, debug=True)