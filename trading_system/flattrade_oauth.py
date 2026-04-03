#!/usr/bin/env python3
"""
Flattrade OAuth Server - Run on your server, access via IP
Usage: python3 flattrade_oauth.py
Access: http://YOUR_SERVER_IP:5000
"""

from flask import Flask, request, jsonify
import requests
import json
import os
import socket

app = Flask(__name__)

TOKEN_FILE = "/opt/nifty_monitor/flattrade_token.json"

def get_local_ip():
    """Get local IP address"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return '127.0.0.1'

def save_token(token, user_id):
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, 'w') as f:
        json.dump({'token': token, 'user_id': user_id}, f)

def load_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'r') as f:
            return json.load(f)
    return None

@app.route('/')
def index():
    ip = get_local_ip()
    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>Flattrade Login</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{ font-family: -apple-system, sans-serif; padding: 20px; background: #f5f5f5; }}
        .box {{ max-width: 350px; margin: 50px auto; background: white; padding: 30px; 
               border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        input {{ width: 100%; padding: 12px; margin: 8px 0; box-sizing: border-box; 
                border: 1px solid #ddd; border-radius: 5px; }}
        button {{ width: 100%; padding: 14px; background: #4CAF50; color: white; 
                border: none; border-radius: 5px; font-size: 16px; cursor: pointer; }}
        button:hover {{ background: #45a049; }}
        .result {{ background: #d4edda; padding: 15px; border-radius: 5px; margin-top: 20px; 
                  word-break: break-all; font-family: monospace; font-size: 12px; }}
        .info {{ background: #e7f3ff; padding: 15px; border-radius: 5px; margin: 20px 0; }}
    </style>
</head>
<body>
    <div class="box">
        <h2>🔐 Flattrade Login</h2>
        <form action="/login" method="POST">
            <input type="text" name="user_id" placeholder="User ID" required>
            <input type="password" name="password" placeholder="Password" required>
            <button type="submit">Login</button>
        </form>
        <div class="info">
            <strong>Server:</strong> {ip}:5000
        </div>
    </div>
</body>
</html>
"""

@app.route('/login', methods=['POST'])
def login():
    user_id = request.form.get('user_id')
    password = request.form.get('password')
    
    try:
        resp = requests.post(
            "https://piconnect.flattrade.in/PiConnectAPI/api/login",
            json={"uid": user_id, "pwd": password, "factor2": "", 
                  "du": "192.168.1.1", "appkey": "", "imei": "", 
                  "ip": "192.168.1.1", "os": "WINDOWS", "lang": "en"},
            timeout=15
        )
        
        result = resp.json()
        
        if result.get('stat') == 'Ok':
            token = result.get('sess')
            save_token(token, user_id)
            
            return f"""
<!DOCTYPE html>
<html>
<head>
    <title>Success</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{ font-family: -apple-system, sans-serif; padding: 20px; text-align: center; }}
        .box {{ max-width: 400px; margin: 50px auto; background: white; padding: 30px; 
               border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h2 {{ color: green; }}
        .token {{ background: #f0f0f0; padding: 15px; border-radius: 5px; 
                 word-break: break-all; font-family: monospace; font-size: 11px; 
                 margin: 15px 0; }}
        button {{ padding: 10px 20px; background: #007bff; color: white; 
                border: none; border-radius: 5px; cursor: pointer; }}
    </style>
</head>
<body>
    <div class="box">
        <h2>✅ Login Successful!</h2>
        <p>Use this in Telegram:</p>
        <div class="token">/token {user_id} {token}</div>
        <button onclick="copy()">Copy Command</button>
        <br><br>
        <a href="/">← New Login</a>
    </div>
    <script>
        function copy() {{ navigator.clipboard.writeText('/token {user_id} {token}'); alert('Copied!'); }}
    </script>
</body>
</html>
            """
        
        return f"""
<!DOCTYPE html>
<html><body style="font-family: sans-serif; padding: 20px; text-align: center;">
    <h2 style="color: red;">❌ {result.get('emsg', 'Login Failed')}</h2>
    <a href="/">Try Again</a>
</body></html>
        """
        
    except Exception as e:
        return f"""
<!DOCTYPE html>
<html><body style="font-family: sans-serif; padding: 20px; text-align: center;">
    <h2 style="color: red;">Error: {str(e)}</h2>
    <a href="/">Try Again</a>
</body></html>
        """

@app.route('/status')
def status():
    data = load_token()
    if data:
        return jsonify({'status': 'connected', 'user_id': data.get('user_id')})
    return jsonify({'status': 'not_connected'})

if __name__ == '__main__':
    ip = get_local_ip()
    print("=" * 60)
    print("🌐 Flattrade OAuth Server")
    print("=" * 60)
    print(f"\n📱 Open in browser: http://{ip}:5000")
    print(f"\n🌍 Public access: ngrok http 5000")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000)