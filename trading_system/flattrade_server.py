#!/usr/bin/env python3
"""
FlatTrade Pi API v2 Webhook Server
Based on official FlatTrade Pi documentation
"""

from flask import Flask, request, jsonify, redirect
import requests
import hashlib
import os
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN_FILE = "/opt/nifty_monitor/flattrade_token.txt"
API_KEY = "ea2b11bbfbce4ad88a7d4285a1647794"
API_SECRET = "2026.f5c5fed60d4b4a81bc1c4a42900de23f21a44f51a61c391f"
REDIRECT_URI = "http://175.29.21.65:9000/callback"


def load_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'r') as f:
            return f.read().strip()
    return None


def save_token(token):
    with open(TOKEN_FILE, 'w') as f:
        f.write(token)
    logger.info("Token saved successfully")


def compute_hash(api_key, request_code, api_secret):
    raw = f"{api_key}{request_code}{api_secret}"
    return hashlib.sha256(raw.encode()).hexdigest()


@app.route('/')
def index():
    return '<h1>FlatTrade Pi API Server</h1><p><a href="/auth">/auth</a> - Start login</p>'


@app.route('/auth')
def start_auth():
    auth_url = f"https://auth.flattrade.in/?app_key={API_KEY}&redirect_uri={REDIRECT_URI}"
    return redirect(auth_url)


@app.route('/callback')
def callback():
    # FlatTrade uses 'code' parameter
    code = request.args.get('code') or request.args.get('request_code')
    if not code:
        return "<h1>Error</h1><p>No code in redirect</p>"

    try:
        hash_value = compute_hash(API_KEY, code, API_SECRET)
        token_url = "https://authapi.flattrade.in/trade/apitoken"
        payload = {
            "api_key": API_KEY,
            "request_code": code,
            "api_secret": hash_value
        }

        logger.info(f"Exchanging code for token...")
        response = requests.post(token_url, json=payload, timeout=30)
        result = response.json()
        logger.info(f"Response: {result}")

        if result.get('stat') == 'Ok' and result.get('token'):
            token = result.get('token')
            save_token(token)
            return f"<h1>✅ Success!</h1><p>Token: {token[:30]}...</p>"

        return f"<h1>Error</h1><p>{result}</p>"
    except Exception as e:
        logger.error(f"Error: {e}")
        return f"<h1>Error</h1><p>{e}</p>"


@app.route('/status')
def status():
    token = load_token()
    return jsonify({"stat": "Ok", "token_set": token is not None, "token": token[:20] + "..." if token else None})


@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        logger.info(f"Order update: {data}")
        return jsonify({"stat": "Ok"})
    except Exception as e:
        return jsonify({"stat": "Not_Ok", "emsg": str(e)})


if __name__ == '__main__':
    print("="*50)
    print("FlatTrade Pi API Server")
    print("="*50)
    app.run(host='0.0.0.0', port=9000, debug=False)
