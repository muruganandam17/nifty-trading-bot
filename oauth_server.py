#!/usr/bin/env python3
from flask import Flask, request, redirect
import requests
import hashlib
import os

app = Flask(__name__)

APP_KEY = "ea2b11bbfbce4ad88a7d4285a1647794"
APP_SECRET = "2026.f5c5fed60d4b4a81bc1c4a42900de23f21a44f51a61c391f"
TOKEN_URL = "https://authapi.flattrade.in/trade/apitoken"
TOKEN_FILE = "/opt/nifty_monitor/ft_token.txt"

@app.route('/')
def oauth_callback():
    """Handle OAuth redirect with request token"""
    request_token = request.args.get('request_token')
    
    if not request_token:
        return "Error: No request_token in redirect URL"
    
    print(f"Received request_token: {request_token[:20]}...")
    
    # Exchange request_token for access token
    # Note: Based on FlatTrade API, we use the hash method to get token
    # The request_token approach may differ - let's try both
    
    # Method 1: Use request_token with hash
    hash_value = hashlib.sha256((APP_KEY + request_token + APP_SECRET).encode()).hexdigest()
    payload = {"api_key": APP_KEY, "hash_value": hash_value, "request_token": request_token}
    
    # Method 2: Just use app_key + app_secret hash (like before)
    hash_value2 = hashlib.sha256((APP_KEY + APP_SECRET).encode()).hexdigest()
    payload2 = {"api_key": APP_KEY, "hash_value": hash_value2}
    
    try:
        # Try method 1 first
        r = requests.post(TOKEN_URL, json=payload, timeout=30)
        if r.status_code == 200:
            data = r.json()
            if "token" in data:
                token = data["token"]
                expires_at = os.path.getmtime(TOKEN_FILE) + 82800 if os.path.exists(TOKEN_FILE) else 0
                with open(TOKEN_FILE, "w") as f:
                    f.write(f"{token},{expires_at}")
                return f"✅ Token saved! You can close this page.<br>Token: {token[:30]}..."
        
        # Try method 2
        r2 = requests.post(TOKEN_URL, json=payload2, timeout=30)
        if r2.status_code == 200:
            data2 = r2.json()
            if "token" in data2:
                token = data2["token"]
                with open(TOKEN_FILE, "w") as f:
                    f.write(f"{token},{os.path.getmtime(TOKEN_FILE) + 82800}")
                return f"✅ Token saved! You can close this page.<br>Token: {token[:30]}..."
                
        return f"Error getting token: {r.text}<br>Try again with new login"
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == '__main__':
    print("OAuth callback server running on port 9999")
    app.run(host='0.0.0.0', port=9999, debug=False)