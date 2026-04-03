#!/usr/bin/env python3
import requests,pandas as pd,time
import json
from datetime import datetime, timedelta
import pytz
import os
import hashlib

UA = "Mozilla/5.0"
TELEGRAM_TOKEN = "8637593160:AAG7VCBAFC5icaxAcvFf1h9QnE6LyMCe0PE"
SYMBOL = "NIFTY"
INTERVAL = 15
TFS_ALERT = ["15m","30m","60m","4h","1d","1w"]
TFS_SQZ = ["5m","15m","30m","60m","1h","4h"]

# FlatTrade Config
NIFTY_TOKEN = "26009"  # NSE NIFTY
CLIENT_ID = "MADIV253"
TOKEN_FILE = "/opt/nifty_monitor/flattrade_token.txt"
PI_BASE_URL = "https://piconnect.flattrade.in/PiConnectAPI"
CANDLE_CACHE_FILE = "/opt/nifty_monitor/ft_candles.json"

# OAuth Config
API_KEY = "ea2b11bbfbce4ad88a7d4285a1647794"
API_SECRET = "2026.f5c5fed60d4b4a81bc1c4a42900de23f21a44f51a61c391f"
REDIRECT_URI = "http://175.29.21.65:9000/callback"
TOKEN_URL = "https://authapi.flattrade.in/trade/apitoken"

sent_alerts = {}
CHAT_ID = None
current_candles = {}
last_token_reminder_date = None

def log(msg):
    try:
        with open("/var/log/nifty_monitor.log", "a") as f:
            f.write(msg+"\n")
    except: pass

def load_token():
    try:
        with open(TOKEN_FILE, "r") as f:
            return f.read().strip()
    except:
        return None

def save_token(token):
    try:
        with open(TOKEN_FILE, "w") as f:
            f.write(token)
        log(f"Token saved: {token[:20]}...")
    except Exception as e:
        log(f"Token save error: {e}")

def check_token_valid():
    """Check if token is valid"""
    try:
        token = load_token()
        if not token:
            return False, "No token"
        
        j_data = {"uid": CLIENT_ID, "exch": "NSE", "token": NIFTY_TOKEN}
        j_data_str = json.dumps(j_data)
        payload = f"jData={j_data_str}&jKey={token}"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        
        r = requests.post(f"{PI_BASE_URL}/GetQuotes", data=payload, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data.get('stat') == 'Ok':
                return True, "Valid"
        
        return False, "Expired/Invalid"
    except:
        return False, "Error"

def compute_hash(api_key, code, api_secret):
    raw = f"{api_key}{code}{api_secret}"
    return hashlib.sha256(raw.encode()).hexdigest()

def exchange_code_for_token(code):
    """Exchange OAuth code for access token"""
    try:
        hash_value = compute_hash(API_KEY, code, API_SECRET)
        payload = {"api_key": API_KEY, "request_code": code, "api_secret": hash_value}
        
        r = requests.post(TOKEN_URL, json=payload, timeout=30)
        result = r.json()
        
        if result.get('stat') == 'Ok' and result.get('token'):
            token = result.get('token')
            save_token(token)
            return True, token
        
        return False, str(result)
    except Exception as e:
        return False, str(e)

def get_oauth_url():
    return f"https://auth.flattrade.in/?app_key={API_KEY}&redirect_uri={REDIRECT_URI}&response_type=code"

def get_live_price():
    token = load_token()
    if not token:
        return None
    
    j_data = {"uid": CLIENT_ID, "exch": "NSE", "token": NIFTY_TOKEN}
    j_data_str = json.dumps(j_data)
    payload = f"jData={j_data_str}&jKey={token}"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    
    try:
        r = requests.post(f"{PI_BASE_URL}/GetQuotes", data=payload, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data.get('stat') == 'Ok':
                return float(data.get('lp'))
    except: pass
    return None

def get_candle_start_time(interval):
    tz = pytz.timezone("Asia/Kolkata")
    now = datetime.now(tz)
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    
    if now < market_open:
        return None
    
    minutes_map = {"5m": 5, "15m": 15, "30m": 30, "60m": 60, "1h": 60, "4h": 240}
    interval_min = minutes_map.get(interval, 15)
    
    minutes_since_open = int((now - market_open).total_seconds() / 60)
    candles_passed = minutes_since_open // interval_min
    candle_start = market_open + timedelta(minutes=candles_passed * interval_min)
    
    return int(candle_start.timestamp())

def update_intraday_candle(interval, price):
    global current_candles
    
    if interval not in current_candles:
        current_candles[interval] = {}
    
    candle_ts = get_candle_start_time(interval)
    if not candle_ts:
        return
    
    if candle_ts not in current_candles[interval]:
        current_candles[interval][candle_ts] = {"O": price, "H": price, "L": price, "C": price}
    else:
        candle = current_candles[interval][candle_ts]
        candle["H"] = max(candle["H"], price)
        candle["L"] = min(candle["L"], price)
        candle["C"] = price
    
    try:
        with open(CANDLE_CACHE_FILE, "w") as f:
            json.dump(current_candles, f)
    except: pass

def get_intraday_data(interval):
    global current_candles
    
    try:
        if os.path.exists(CANDLE_CACHE_FILE):
            with open(CANDLE_CACHE_FILE, "r") as f:
                current_candles = json.load(f)
    except: pass
    
    live_price = get_live_price()
    if live_price:
        update_intraday_candle(interval, live_price)
    
    if interval in current_candles and current_candles[interval]:
        candles = current_candles[interval]
        data = []
        for ts, ohlc in sorted(candles.items()):
            data.append({
                "timestamp": pd.to_datetime(int(ts), unit="s"),
                "O": ohlc["O"], "H": ohlc["H"], "L": ohlc["L"], "C": ohlc["C"]
            })
        if data:
            df = pd.DataFrame(data)
            df.set_index("timestamp", inplace=True)
            return df
    
    return pd.DataFrame()

def get_historical_data(sym, per, intv):
    intv_map = {"5m":"5m","15m":"15m","30m":"30m","60m":"60m","1h":"60m","4h":"4h","1d":"1d","1w":"1wk"}
    intv = intv_map.get(intv,intv)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/^{sym}?range={per}&interval={intv}"
    
    for _ in range(3):
        try:
            r = requests.get(url, headers={"User-Agent":UA}, timeout=15)
            if r.status_code==200:
                d = r.json()
                if d.get("chart",{}).get("result"):
                    res = d["chart"]["result"][0]
                    ts = res.get("timestamp",[])
                    q = res.get("indicators",{}).get("quote",[{}])[0]
                    if ts:
                        return pd.DataFrame({"O":q.get("open",[]),"H":q.get("high",[]),"L":q.get("low",[]),"C":q.get("close",[])}, index=pd.to_datetime(ts, unit="s").tz_localize(None).dropna())
        except: pass
        time.sleep(2)
    return pd.DataFrame()

def get_data(sym, per, intv):
    hist_df = get_historical_data(sym, "60d", intv)
    ft_df = get_intraday_data(intv)
    
    if hist_df.empty and ft_df.empty:
        return pd.DataFrame()
    
    if hist_df.empty:
        return ft_df
    
    if ft_df.empty:
        return hist_df
    
    cutoff = datetime.now() - timedelta(days=1)
    hist_df = hist_df[hist_df.index < cutoff]
    
    combined = pd.concat([hist_df, ft_df])
    combined = combined[~combined.index.duplicated(keep="last")]
    combined = combined.sort_index()
    
    return combined

def calc_bollinger_squeeze(df, period=20):
    df = df.copy()
    df['MA'] = df['C'].rolling(window=period).mean()
    df['STD'] = df['C'].rolling(window=period).std()
    df['BB_UPPER'] = df['MA'] + (2 * df['STD'])
    df['BB_LOWER'] = df['MA'] - (2 * df['STD'])
    df['BB_WIDTH'] = df['BB_UPPER'] - df['BB_LOWER']
    return df

def get_all_squeeze_status():
    status = []
    for tf in TFS_SQZ:
        df = get_data(SYMBOL, "30d", tf)
        if df.empty or len(df) < 25:
            status.append((tf, "N/A", "N/A"))
            continue
        df = calc_bollinger_squeeze(df, period=20)
        prev_w = df['BB_WIDTH'].iloc[-2]
        curr_w = df['BB_WIDTH'].iloc[-1]
        direction = "INCR" if curr_w > prev_w else "DECR"
        status.append((tf, direction, round(curr_w, 2)))
    return status

def format_squeeze_table():
    status = get_all_squeeze_status()
    msg = "SQZ: "
    for tf, direction, width in status:
        msg += f"{tf}:{direction}/{width} "
    return msg

def check_squeeze_alert(tf):
    df = get_data(SYMBOL, "30d", tf)
    if df.empty or len(df) < 25:
        return None
    
    df = calc_bollinger_squeeze(df, period=20)
    
    prev_high = df['H'].iloc[-2]
    prev_low = df['L'].iloc[-2]
    prev_range = prev_high - prev_low
    curr_close = df['C'].iloc[-1]
    
    prev_width = df['BB_WIDTH'].iloc[-2]
    curr_width = df['BB_WIDTH'].iloc[-1]
    squeeze_dir = "INCREASING" if curr_width > prev_width else "DECREASING"
    
    now = datetime.now(pytz.timezone("Asia/Kolkata"))
    alert_time = now.strftime("%H:%M")
    
    pct = 0.05
    threshold = pct * prev_range
    
    near_low = (curr_close >= prev_low) and (curr_close <= prev_low + threshold)
    near_high = (curr_close <= prev_high) and (curr_close >= prev_high - threshold)
    
    live_price = get_live_price()
    price_src = "LIVE" if live_price else "DELAYED"
    
    if squeeze_dir == "INCREASING" and near_low:
        return {'type':'SQZ','tf':tf,'direction':'BULLISH','curr_close':curr_close,'time':alert_time,
            'msg':f"SQZ: {tf} INCREASING near LOW\nTime: {alert_time}\nPrice: {curr_close:.2f} ({price_src})\nSignal: BULLISH\nData: Yahoo Hist + FT Intraday"}
    
    elif squeeze_dir == "DECREASING" and near_high:
        return {'type':'SQZ','tf':tf,'direction':'BEARISH','curr_close':curr_close,'time':alert_time,
            'msg':f"SQZ: {tf} DECREASING near HIGH\nTime: {alert_time}\nPrice: {curr_close:.2f} ({price_src})\nSignal: BEARISH\nData: Yahoo Hist + FT Intraday"}
    
    return None

def calc_psar(df,af=0.02,maxaf=0.2):
    if len(df)<3: return df
    psar = [df["C"].iloc[0]]
    trend = [1]
    ep = df["H"].iloc[0]
    afv = af
    for i in range(1,len(df)):
        pps = psar[-1]
        cc, ch, cl = df["C"].iloc[i], df["H"].iloc[i], df["L"].iloc[i]
        pl = df["L"].iloc[i-1] if i>1 else cl
        ph = df["H"].iloc[i-1] if i>1 else ch
        if trend[-1]==1:
            nps = min(pps + afv*(ep-pps), pl)
            if nps>cl: trend.append(-1); nps=ep; afv=af; ep=cl
            else: trend.append(1); afv = min(afv+af, maxaf) if ch>ep else afv; ep = max(ep,ch)
        else:
            nps = max(pps + afv*(ep-pps), ph)
            if nps<ch: trend.append(1); nps=ep; afv=af; ep=ch
            else: trend.append(-1); afv = min(afv+af, maxaf) if cl<ep else afv; ep = min(ep,cl)
        psar.append(nps)
    df = df.copy()
    df["PSAR"] = psar
    return df

def check_psar_alert(tf):
    df = get_data(SYMBOL, "10d", tf)
    if df.empty or len(df) < 3:
        return None
    
    df = calc_psar(df)
    i = len(df) - 1
    
    pps = df["PSAR"].iloc[i-1]
    cps = df["PSAR"].iloc[i]
    pc = df["C"].iloc[i-1]
    cc = df["C"].iloc[i]
    
    now = datetime.now(pytz.timezone("Asia/Kolkata"))
    alert_time = now.strftime("%H:%M")
    sqz_table = format_squeeze_table()
    
    live_price = get_live_price()
    price_src = "LIVE" if live_price else "DELAYED"
    
    if pps > pc and cps < cc:
        return {'type':'PSAR','tf':tf,'direction':'BULLISH','price':round(cc,2),
            'psar_prev':round(pps,2),'psar_curr':round(cps,2),'time':alert_time,
            'msg':f"PSAR: {tf} ABOVE\nTime: {alert_time}\nPrice: {cc:.2f} ({price_src})\nPSAR: {pps:.2f}->{cps:.2f}\n{sqz_table}\nBULLISH\nData: Yahoo Hist + FT Intraday"}
    
    if pps < pc and cps > cc:
        return {'type':'PSAR','tf':tf,'direction':'BEARISH','price':round(cc,2),
            'psar_prev':round(pps,2),'psar_curr':round(cps,2),'time':alert_time,
            'msg':f"PSAR: {tf} BELOW\nTime: {alert_time}\nPrice: {cc:.2f} ({price_src})\nPSAR: {pps:.2f}->{cps:.2f}\n{sqz_table}\nBEARISH\nData: Yahoo Hist + FT Intraday"}
    
    return None

def send_msg(msg):
    global CHAT_ID
    if not CHAT_ID:
        return False
    try:
        r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendMessage", json={"chat_id":CHAT_ID,"text":msg}, timeout=10)
        return r.status_code==200
    except: return False

def handle_command(cmd):
    global CHAT_ID
    cmd = cmd.strip().lower()
    
    if cmd == "/start":
        return "NIFTY ALERT Bot\n\nData:\n- Yahoo: Historical\n- FlatTrade: Intraday + Live\n\nCommands:\n/alerts\n/status\n/tokenurl"
    
    elif cmd == "/status":
        tz = pytz.timezone("Asia/Kolkata")
        n = datetime.now(tz)
        is_open = n.weekday()<5 and (9,15)<=(n.hour,n.minute)<=(15,30)
        
        valid, token_msg = check_token_valid()
        live_price = get_live_price()
        price_str = f"LIVE: {live_price}" if live_price else "N/A"
        
        return f"Bot: Running\nMarket: {'OPEN' if is_open else 'CLOSED'}\nPrice: {price_str}\nToken: {token_msg}"
    
    elif cmd == "/tokenurl":
        return f"🔐 Login to refresh token:\n\n{get_oauth_url()}\n\nLogin here, token auto-updates."
    
    elif cmd == "/alerts":
        msg = "Status:\n"
        for tf in TFS_SQZ:
            a = check_squeeze_alert(tf)
            msg += f"{tf}: {a['direction'] if a else 'Neutral'}\n"
        return msg
    
    return "Unknown: /help"

def market_open():
    n = datetime.now(pytz.timezone("Asia/Kolkata"))
    return n.weekday()<5 and (9,15)<=(n.hour,n.minute)<=(15,30)

def send_daily_token_reminder():
    """Send token refresh reminder at 9:15 AM"""
    global last_token_reminder_date
    
    tz = pytz.timezone("Asia/Kolkata")
    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")
    
    # Check if it's 9:15 AM (within 5 min window)
    if now.hour == 9 and 15 <= now.minute <= 20:
        # Check if we already sent today
        if last_token_reminder_date != today_str:
            last_token_reminder_date = today_str
            oauth_url = get_oauth_url()
            msg = f"☀️ Good Morning! Market open soon.\n\n🔐 Login to refresh FlatTrade token:\n\n{oauth_url}\n\nLogin to keep data running!"
            send_msg(msg)
            log(f"Daily token reminder sent for {today_str}")

log("=== BOT STARTING (Yahoo + FT Intraday) ===")

last_seen_updates = []

while True:
    try:
        # Handle Telegram commands
        r = requests.get("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/getUpdates?timeout=1", timeout=5)
        if r.status_code==200:
            updates = r.json().get("result",[])
            if updates:
                for u in updates[-3:]:
                    uid = u.get("update_id")
                    if uid not in last_seen_updates:
                        last_seen_updates.append(uid)
                        if len(last_seen_updates) > 10:
                            last_seen_updates = last_seen_updates[-10:]
                        
                        if "message" in u and "chat" in u["message"]:
                            CHAT_ID = u["message"]["chat"].get("id")
                            text = u["message"].get("text", "")
                            log(f"Msg: {text}")
                            
                            # Handle /settoken command
                            if text and text.startswith("/settoken "):
                                code = text.split("/settoken ", 1)[1].strip()
                                success, result = exchange_code_for_token(code)
                                if success:
                                    send_msg(f"✅ Token updated!\nLength: {len(result)}")
                                else:
                                    send_msg(f"❌ Token update failed: {result}")
                            elif text and text.startswith("/"):
                                send_msg(handle_command(text))
        
        # Send daily token reminder at 9:15 AM
        send_daily_token_reminder()
        
        if not market_open():
            time.sleep(30)
            continue
        
        # Update intraday candles
        for tf in ["5m", "15m", "30m", "60m"]:
            live_price = get_live_price()
            if live_price:
                update_intraday_candle(tf, live_price)
        
        # Check alerts
        for tf in TFS_ALERT:
            try:
                alert = check_squeeze_alert(tf)
                if alert:
                    key = "SQZ_"+tf
                    if key not in sent_alerts:
                        if send_msg(alert['msg']):
                            sent_alerts[key] = True
                            log(f"SQZ: {tf}")
            except: pass
        
        for tf in TFS_ALERT:
            try:
                alert = check_psar_alert(tf)
                if alert:
                    key = "PSAR_"+tf
                    if key not in sent_alerts:
                        if send_msg(alert['msg']):
                            sent_alerts[key] = True
                            log(f"PSAR: {tf}")
            except: pass
        
        if len(sent_alerts) > 50:
            sent_alerts.clear()
        
        time.sleep(INTERVAL)
    except Exception as e:
        log("Error: "+str(e))
        time.sleep(30)