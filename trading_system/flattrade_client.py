#!/usr/bin/env python3
"""
FlatTrade Client - Uses FlatTrade for quotes, Yahoo for historical data
"""
import requests
import pandas as pd
import json
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN_FILE = "/opt/nifty_monitor/flattrade_token.txt"
BASE_URL = "https://piconnect.flattrade.in/PiConnectAPI"

def load_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'r') as f:
            return f.read().strip()
    return None

def api_call(endpoint, j_data):
    token = load_token()
    if not token:
        return None
    j_data_str = json.dumps(j_data)
    payload = f"jData={j_data_str}&jKey={token}"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    url = f"{BASE_URL}/{endpoint}"
    try:
        resp = requests.post(url, data=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            return resp.json()
    except:
        pass
    return None

def get_quote(token_id="26000"):
    """Get real-time quote from FlatTrade"""
    result = api_call("GetQuotes", {"uid": "MADIV253", "exch": "NSE", "token": token_id})
    if result and result.get('stat') == 'Ok':
        return result
    return None

def get_nifty_quote():
    """Get NIFTY real-time quote"""
    return get_quote("26000")

# For historical data - use the existing custom Yahoo fetcher from nifty_monitor_bot
def get_yahoo_data(symbol="^NSEI", interval="5m", period="5d"):
    """Get historical data from Yahoo"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)
        return df
    except Exception as e:
        logger.error(f"Yahoo error: {e}")
        return pd.DataFrame()

if __name__ == '__main__':
    print("FlatTrade Client Test")
    q = get_nifty_quote()
    if q:
        print(f"NIFTY: {q.get('lp')}")
    else:
        print("FlatTrade quote failed")
