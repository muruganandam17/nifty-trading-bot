#!/usr/bin/env python3
"""
NIFTY PSAR Crossover Monitor
- Monitors NIFTY continuously for PSAR crossovers
- Sends alerts to Telegram when crossover detected
- Includes SQZMOM values for all timeframes
"""

import os
import sys
import time
import logging
from datetime import datetime
from telegram import Bot
from telegram.error import TelegramError

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Bot token
BOT_TOKEN = "8651836619:AAGHo3gEfWTNKA58MTwBQd-GCM20w2vYRPw"
CHAT_ID = None  # Will be set on first message

# Timeframe intervals
TF_INTERVALS = {
    '1m': 60, '5m': 300, '15m': 900, '30m': 1800,
    '60m': 3600, '1h': 3600, '4h': 14400
}
ALL_TIMEFRAMES = ['1m', '5m', '15m', '30m', '60m', '1h', '4h']

# NIFTY symbol
NIFTY_SYMBOL = "^NSEI"

# Track last alerts to prevent duplicates
last_alerts = {}


def get_psar_crossover(symbol, timeframe):
    """Check for PSAR crossover in given timeframe"""
    import yfinance as yf
    from strategies.sqz_momentum import calculate_psar
    
    interval_map = {
        '1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m',
        '60m': '60m', '2h': '2h', '3h': '3h', '4h': '4h'
    }
    
    tf = interval_map.get(timeframe, '5m')
    period = "5d" if timeframe in ['1m', '5m', '15m', '30m'] else "10d"
    
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval=tf)
    
    if df is None or len(df) < 10:
        return None
    
    psar, _ = calculate_psar(df)
    
    # Check last 3 candles for crossover
    for i in range(2, len(df)):
        prev_close = df.iloc[i-1]['Close']
        curr_close = df.iloc[i]['Close']
        prev_psar = psar.iloc[i-1]
        curr_psar = psar.iloc[i]
        
        # PSAR crosses below price (BUY - SAR went below)
        if prev_psar > prev_close and curr_psar < curr_close:
            return {
                'type': 'BELOW',
                'timestamp': str(df.index[i]),
                'price': round(curr_close, 2),
                'psar_before': round(prev_psar, 2),
                'psar_after': round(curr_psar, 2)
            }
        
        # PSAR crosses above price (SELL - SAR went above)
        elif prev_psar < prev_close and curr_psar > curr_close:
            return {
                'type': 'ABOVE',
                'timestamp': str(df.index[i]),
                'price': round(curr_close, 2),
                'psar_before': round(prev_psar, 2),
                'psar_after': round(curr_psar, 2)
            }
    
    return None


def get_all_timeframes_sqzmom(symbol):
    """Get SQZMOM values for all timeframes"""
    import yfinance as yf
    from strategies.sqz_momentum import calculate_sqzmom
    
    result = {}
    
    for tf in ALL_TIMEFRAMES:
        interval_map = {
            '1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m',
            '60m': '60m', '1h': '1h', '4h': '4h'
        }
        
        period = "5d" if tf in ['1m', '5m', '15m', '30m'] else "10d"
        
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval_map[tf])
            
            if df is None or len(df) < 25:
                result[tf] = {'error': 'Insufficient data'}
                continue
            
            sqz_df = calculate_sqzmom(df)
            
            if sqz_df.empty or len(sqz_df) < 3:
                result[tf] = {'error': 'No data'}
                continue
            
            curr = sqz_df.iloc[-1]
            prev = sqz_df.iloc[-2]
            
            momentum = curr['momentum']
            prev_momentum = prev['momentum']
            
            if momentum > prev_momentum:
                direction = "increasing"
                arrow = "📈"
            elif momentum < prev_momentum:
                direction = "decreasing"
                arrow = "📉"
            else:
                direction = "flat"
                arrow = "➖"
            
            result[tf] = {
                'momentum': round(momentum, 2),
                'direction': direction,
                'arrow': arrow,
                'squeeze': curr['squeeze']
            }
            
        except Exception as e:
            result[tf] = {'error': str(e)}
    
    return result


def build_alert_message(symbol, timeframe, psar_data, sqzmom_data):
    """Build the alert message"""
    
    if psar_data['type'] == 'BELOW':
        direction = "SAR went BELOW price"
    else:
        direction = "SAR went ABOVE price"
    
    msg = f"📊 *PSAR CROSSOVER: NIFTY*\n"
    msg += f"⏱️ Timeframe: {timeframe}\n"
    msg += f"🕐 {psar_data['timestamp']}\n"
    msg += f"═══════════════════════════\n"
    msg += f"{direction}\n"
    msg += f"Price: ₹{psar_data['price']}\n"
    msg += f"PSAR: ₹{psar_data['psar_before']} → ₹{psar_data['psar_after']}\n\n"
    
    msg += "*📊 SQZMOM All Timeframes:*\n"
    
    for tf in ALL_TIMEFRAMES:
        tf_data = sqzmom_data.get(tf, {})
        if 'error' in tf_data:
            continue
        
        squeeze = tf_data.get('squeeze', 'N/A')
        direction = tf_data.get('direction', 'N/A')
        arrow = tf_data.get('arrow', '❓')
        momentum = tf_data.get('momentum', 0)
        
        msg += f"{tf}: {momentum:>7.1f} {arrow} {direction} | Sqz:{squeeze}\n"
    
    return msg


def send_telegram_alert(message):
    """Send alert to Telegram"""
    global CHAT_ID
    
    try:
        bot = Bot(token=BOT_TOKEN)
        
        # If no chat_id, we can't send - need user to message first
        if CHAT_ID is None:
            logger.warning("No CHAT_ID set - cannot send alert. User needs to message bot first.")
            return False
        
        bot.send_message(chat_id=CHAT_ID, text=message, parse_mode='Markdown')
        logger.info(f"Alert sent to {CHAT_ID}")
        return True
        
    except TelegramError as e:
        logger.error(f"Telegram error: {e}")
        return False


def check_and_alert(symbol, timeframe):
    """Check for PSAR crossover and send alert if found"""
    global last_alerts
    
    key = f"{symbol}_{timeframe}"
    
    psar_result = get_psar_crossover(symbol, timeframe)
    
    if psar_result:
        # Check if we already alerted for this
        last_alert = last_alerts.get(key, {})
        
        if last_alert and last_alert['timestamp'] == psar_result['timestamp']:
            return False  # Already alerted for this
        
        # New crossover - get all TFs and send alert
        sqzmom = get_all_timeframes_sqzmom(symbol)
        message = build_alert_message(symbol, timeframe, psar_result, sqzmom)
        
        # Update last alert
        last_alerts[key] = psar_result
        
        # Send alert
        return send_telegram_alert(message)
    
    return False


def continuous_monitor():
    """Continuously monitor NIFTY for PSAR crossovers"""
    global CHAT_ID
    
    logger.info("Starting NIFTY PSAR Crossover Monitor")
    logger.info(f"Monitoring: {NIFTY_SYMBOL}")
    logger.info(f"Timeframes: {ALL_TIMEFRAMES}")
    
    # Track last data update time for each timeframe
    last_data_time = {tf: None for tf in ALL_TIMEFRAMES}
    
    while True:
        try:
            now = datetime.now()
            
            for tf in ALL_TIMEFRAMES:
                interval = TF_INTERVALS[tf]
                
                # Get current candle time for this timeframe
                current_candle_seconds = (now.hour * 3600 + now.minute * 60 + now.second)
                candle_time_seconds = (current_candle_seconds // interval) * interval
                current_candle_time = now.replace(
                    hour=candle_time_seconds // 3600,
                    minute=(candle_time_seconds % 3600) // 60,
                    second=candle_time_seconds % 60,
                    microsecond=0
                )
                
                # Check if there's new data for this timeframe
                last_time = last_data_time.get(tf)
                
                if last_time is None or current_candle_time > last_time:
                    logger.debug(f"Checking {tf} at {current_candle_time.strftime('%H:%M:%S')}")
                    
                    # Check for PSAR crossover
                    if check_and_alert(NIFTY_SYMBOL, tf):
                        logger.info(f"ALERT SENT for {tf}")
                    
                    # Update last data time
                    last_data_time[tf] = current_candle_time
            
            # Sleep a bit before next check
            time.sleep(30)
            
        except Exception as e:
            logger.error(f"Error in monitor loop: {e}")
            time.sleep(60)


def main():
    """Main entry point"""
    # Import strategy functions
    sys.path.insert(0, '/workspace/project/trading_system')
    from strategies.sqz_momentum import calculate_sqzmom, calculate_psar
    
    logger.info("="*50)
    logger.info("NIFTY PSAR Crossover Monitor Started")
    logger.info("="*50)
    
    # Start continuous monitoring
    continuous_monitor()


if __name__ == "__main__":
    main()