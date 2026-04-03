"""
Telegram Bot - Real-time alert monitoring (checks at candle close)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import dependencies first to avoid import order issues
import pandas as pd
import numpy as np

import logging
import time
import threading
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Your bot token
BOT_TOKEN = "8651836619:AAGHo3gEfWTNKA58MTwBQd-GCM20w2vYRPw"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import
from strategies.sqz_momentum import calculate_sqzmom
import yfinance as yf

# Timeframe intervals in seconds
TF_INTERVALS = {
    '1m': 60,
    '5m': 300,
    '15m': 900,
    '30m': 1800,
    '60m': 3600,
    '1h': 3600,
    '4h': 14400
}

# All timeframes to check
ALL_TIMEFRAMES = ['1m', '5m', '15m', '30m', '60m', '1h', '4h']

# Global state
watching_symbols = {}
last_check_time = {}  # Track last checked candle time per symbol/tf
monitoring = False
monitor_thread = None
summary_enabled = True  # Enable/disable 5-min summary

# Flatrade credentials
FLATTRADE_TOKEN = None
FLATTRADE_USER_ID = None
FLATTRADE_API_KEY = None

# Track last PSAR crossover to avoid duplicate alerts
last_psar_crossover = {}  # {symbol: {'time': timestamp, 'type': 'BUY/SELL'}}

# Market hours (IST)
MARKET_START_HOUR = 9
MARKET_START_MINUTE = 15
MARKET_END_HOUR = 15
MARKET_END_MINUTE = 30


def is_market_hours() -> bool:
    """Check if currently in market hours"""
    now = datetime.now()
    start = now.replace(hour=MARKET_START_HOUR, minute=MARKET_START_MINUTE, second=0, microsecond=0)
    end = now.replace(hour=MARKET_END_HOUR, minute=MARKET_END_MINUTE, second=0, microsecond=0)
    return start <= now <= end


def get_sqzmom_summary(symbol: str) -> str:
    """Get SQZMOM values for all timeframes with PSAR"""
    from strategies.sqz_momentum import calculate_sqzmom, calculate_psar
    import yfinance as yf
    
    timeframes = ['5m', '15m', '30m', '60m']
    summary = f"📊 *SQZMOM: {symbol}*\n"
    summary += f"🕐 {datetime.now().strftime('%H:%M:%S')}\n"
    summary += f"═══════════════════════════\n"
    
    for tf in timeframes:
        try:
            if symbol.startswith('^'):
                ticker = yf.Ticker(symbol)
            else:
                ticker = yf.Ticker(f"{symbol.upper()}.NS")
            
            price_df = ticker.history(period="2d", interval=tf)
            
            if price_df is None or len(price_df) < 25:
                summary += f"{tf}: ❌ No data\n"
                continue
            
            sqz_df = calculate_sqzmom(price_df)
            psar, _ = calculate_psar(price_df)
            
            if sqz_df.empty or len(sqz_df) < 3 or len(psar) < 2:
                summary += f"{tf}: ❌ Insufficient\n"
                continue
            
            # Get current (forming) candle
            curr = sqz_df.iloc[-1]  # Current forming candle
            prev = sqz_df.iloc[-2]  # Previous closed candle
            
            momentum = curr['momentum']
            mom_change = momentum - prev['momentum']
            close_pos = curr['close_position']
            squeeze = curr['squeeze']
            
            # PSAR
            psar_val = psar.iloc[-1]
            close_price = curr['close']
            psar_above = "⬆️" if psar_val > close_price else "⬇️"
            
            # Determine direction
            if mom_change > 0:
                direction = "📈 Up"
            elif mom_change < 0:
                direction = "📉 Down"
            else:
                direction = "➖ Flat"
            
            # Close position
            if close_pos >= 0.90:
                near = "HIGH"
            elif close_pos <= 0.10:
                near = "LOW"
            else:
                near = "MID"
            
            summary += f"{tf}: {momentum:>7.1f} {direction} | {near} ({close_pos*100:.0f}%) | {squeeze} | PSAR {psar_above}\n"
            
        except Exception as e:
            summary += f"{tf}: ❌ Error\n"
    
    return summary

# Timeframe intervals (seconds)
TF_INTERVALS = {"5m": 300, "15m": 900, "30m": 1800, "60m": 3600}


def get_current_candle_time(timeframe: str) -> datetime:
    """Get the current candle time for a timeframe"""
    now = datetime.now()
    interval = TF_INTERVALS.get(timeframe, 900)
    
    seconds_since_midnight = (now - now.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds()
    current_candle_seconds = (seconds_since_midnight // interval) * interval
    
    hours = int(current_candle_seconds // 3600)
    minutes = int((current_candle_seconds % 3600) // 60)
    seconds = int(current_candle_seconds % 60)
    
    return now.replace(hour=hours, minute=minutes, second=seconds, microsecond=0)


def get_next_candle_time(timeframe: str) -> datetime:
    """Get the next candle close time"""
    current = get_current_candle_time(timeframe)
    interval = TF_INTERVALS.get(timeframe, 900)
    return current + timedelta(seconds=interval)


def check_alert(symbol: str, timeframe: str = "15m") -> dict:
    """Check if alert condition is met for the last CLOSED candle"""
    yf_interval = timeframe
    
    try:
        # Handle index symbols (e.g., ^NSEI, ^NSEBANK) vs stock symbols
        if symbol.startswith('^'):
            ticker = yf.Ticker(symbol)  # Indices don't need .NS
        else:
            ticker = yf.Ticker(f"{symbol.upper()}.NS")
        
        # Get enough data to have closed candles
        price_df = ticker.history(period="2d", interval=yf_interval)
        
        if price_df is None or len(price_df) < 25:
            return {"alert": False, "reason": "Insufficient data"}
        
        sqz_df = calculate_sqzmom(price_df)
        
        if sqz_df.empty or len(sqz_df) < 3:
            return {"alert": False, "reason": "Insufficient SQZMOM data"}
        
        # Check the last CLOSED candle (not the current forming one)
        # Use -2 to get the last closed candle, -1 is the current forming candle
        curr = sqz_df.iloc[-2]  # Last closed candle
        prev = sqz_df.iloc[-3]  # Previous to last closed candle
        
        close_near_high = curr['close_position'] >= 0.90
        momentum_decreasing = curr['momentum'] < prev['momentum']
        
        if close_near_high and momentum_decreasing:
            return {
                "alert": True,
                "symbol": symbol.upper(),
                "timeframe": timeframe,
                "price": curr['close'],
                "momentum": curr['momentum'],
                "momentum_change": curr['momentum'] - prev['momentum'],
                "close_position": curr['close_position'],
                "squeeze": curr['squeeze'],
                "time": datetime.now().strftime("%H:%M:%S"),
                "candle_time": price_df.index[-2].strftime("%H:%M"),  # Time of closed candle
                "candle_date": price_df.index[-2].strftime("%m/%d")
            }
        
        return {"alert": False}
        
    except Exception as e:
        return {"alert": False, "reason": str(e)}


def monitor_loop(bot, chat_id):
    """Continuous monitoring - checks at candle close times"""
    global watching_symbols, last_check_time
    
    logger.info("Monitoring started")
    last_summary_sent = {}  # Track last summary time per symbol
    
    while monitoring:
        try:
            now = datetime.now()
            
            # Check if it's market hours and summary is enabled
            if is_market_hours() and summary_enabled:
                # Send SQZMOM summary every 5 minutes
                for symbol in watching_symbols.keys():
                    key = f"summary_{symbol}"
                    if key not in last_summary_sent:
                        last_summary_sent[key] = now - timedelta(minutes=5)
                    
                    # Send if 5 minutes have passed
                    if (now - last_summary_sent[key]).total_seconds() >= 300:
                        try:
                            summary = get_sqzmom_summary(symbol)
                            import asyncio
                            asyncio.run(bot.send_message(chat_id=chat_id, text=summary, parse_mode='Markdown'))
                            last_summary_sent[key] = now
                            logger.info(f"Summary sent for {symbol}")
                        except Exception as e:
                            logger.error(f"Error sending summary: {e}")
            
            # Existing alert checking logic
            for symbol, config in watching_symbols.items():
                timeframes = config.get('timeframes', ['15m'])
                
                for tf in timeframes:
                    # Get the last closed candle time for this timeframe
                    # For 5m: if now is 9:20, last closed is 9:15
                    # For 15m: if now is 9:30, last closed is 9:15
                    interval = TF_INTERVALS.get(tf, 900)
                    seconds_since_midnight = (now - now.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds()
                    
                    # Calculate last closed candle time
                    current_candle_seconds = (seconds_since_midnight // interval) * interval
                    last_closed_seconds = current_candle_seconds - interval
                    
                    # Convert to datetime
                    hours = int(last_closed_seconds // 3600)
                    minutes = int((last_closed_seconds % 3600) // 60)
                    last_closed_time = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
                    
                    key = f"{symbol}_{tf}"
                    
                    # Check if this is a new closed candle since last check
                    if key not in last_check_time or last_check_time[key] != last_closed_time:
                        logger.info(f"Checking {symbol} {tf} - candle {last_closed_time.strftime('%H:%M')} closed")
                        
                        # ONLY PSAR Crossover Alerts - Check all timeframes for crossover
                        from strategies.sqz_momentum import check_psar_crossover, check_all_timeframes
                        
                        # Check this timeframe for PSAR crossover
                        psar_result = check_psar_crossover(symbol, tf)
                        
                        if psar_result.get('crossover'):
                            global last_psar_crossover
                            
                            # Check if we already alerted for this crossover
                            psar_key = f"{symbol}_{tf}"
                            last_alert = last_psar_crossover.get(psar_key, {})
                            
                            # Only alert if new crossover (different time)
                            should_alert = True
                            if last_alert:
                                if last_alert.get('time') == psar_result.get('timestamp'):
                                    should_alert = False
                            
                            if should_alert:
                                # Update tracking
                                last_psar_crossover[psar_key] = {
                                    'time': psar_result.get('timestamp'),
                                    'type': psar_result.get('crossover')
                                }
                                
                                # Get all timeframe info
                                all_tf = check_all_timeframes(symbol)
                                
                                # Determine direction - just info, not signal
                                if psar_result['crossover'] == 'BUY':
                                    # PSAR went BELOW price
                                    direction = "SAR went BELOW price"
                                else:
                                    # PSAR went ABOVE price
                                    direction = "SAR went ABOVE price"
                                
                                # Build alert message - just info
                                psar_msg = (
                                    f"📊 *PSAR CROSSOVER: {symbol}*\n"
                                    f"⏱️ Timeframe: {tf}\n"
                                    f"🕐 {psar_result.get('timestamp', 'N/A')}\n"
                                    f"═══════════════════════════\n"
                                    f"{direction}\n"
                                    f"Price: ₹{psar_result['price']}\n"
                                    f"PSAR: ₹{psar_result['psar_before']} → ₹{psar_result['psar_after']}\n\n"
                                )
                                
                                # Add all TFs with SQZMOM values - include 1h, 4h
                                psar_msg += "*📊 SQZMOM All Timeframes:*\n"
                                
                                for tf_check in ALL_TIMEFRAMES:
                                    tf_data = all_tf['timeframes'].get(tf_check, {})
                                    if 'error' in tf_data:
                                        continue
                                    
                                    squeeze = tf_data.get('squeeze', 'N/A')
                                    direction = tf_data.get('direction', 'N/A')
                                    arrow = tf_data.get('arrow', '❓')
                                    momentum = tf_data.get('momentum', 0)
                                    
                                    psar_msg += f"{tf_check}: {momentum:>7.1f} {arrow} {direction} | Sqz:{squeeze}\n"
                                
                                import asyncio
                                asyncio.run(bot.send_message(chat_id=chat_id, text=psar_msg, parse_mode='Markdown'))
                                logger.info(f"PSAR alert sent for {symbol} {tf}")
                        
                        last_check_time[key] = last_closed_time
            
            # Calculate time until next candle close
            soonest = None
            for symbol, config in watching_symbols.items():
                for tf in config.get('timeframes', ['15m']):
                    interval = TF_INTERVALS.get(tf, 900)
                    now_seconds = (datetime.now() - datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds()
                    next_candle_seconds = ((now_seconds // interval) + 1) * interval
                    wait = next_candle_seconds - now_seconds
                    if soonest is None or wait < soonest:
                        soonest = wait
            
            sleep_time = max(soonest, 15) if soonest else 60
            logger.debug(f"Sleeping {sleep_time:.0f}s until next candle")
            time.sleep(sleep_time)
            
        except Exception as e:
            logger.error(f"Error in monitor loop: {e}")
            time.sleep(30)
    
    logger.info("Monitoring stopped")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    await update.message.reply_text(
        "🚀 *Trading Alert Bot*\n\n"
        "Commands:\n"
        "/watch SYMBOL - Start monitoring\n"
        "/psar SYMBOL - Check PSAR crossover with all TFs\n"
        "/stop SYMBOL - Stop monitoring\n"
        "/list - Show watching symbols\n"
        "/token - Set Flatrade credentials\n\n"
        "Alert (Info only):\n"
        "• PSAR Crossover - when SAR crosses price\n"
        "• SQZMOM values for all TFs\n\n"
        "Example:\n"
        "/watch SBIN\n"
        "/psar SBIN",
        parse_mode='Markdown'
    )


async def watch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /watch command"""
    global watching_symbols, monitoring, monitor_thread
    
    chat_id = update.message.chat_id
    text = update.message.text.replace('/watch', '').strip().upper()
    
    if not text:
        await update.message.reply_text("Usage: /watch SYMBOL [timeframes]\nExample: /watch SBIN (watches all)\n         /watch INFY 15m,30m")
        return
    
    # Parse symbol and timeframes
    parts = text.split()
    symbol = parts[0]
    
    # If no timeframe specified, watch ALL timeframes
    if len(parts) > 1:
        timeframes = parts[1].split(',')
    else:
        timeframes = ['5m', '15m', '30m', '60m']  # Watch all
    
    # Validate timeframes
    valid_tf = ['5m', '15m', '30m', '60m']
    timeframes = [tf for tf in timeframes if tf in valid_tf]
    if not timeframes:
        timeframes = ['5m', '15m', '30m', '60m']
    
    # Add to watchlist
    if symbol not in watching_symbols:
        watching_symbols[symbol] = {'timeframes': timeframes, 'chat_id': chat_id}
    else:
        watching_symbols[symbol]['timeframes'] = list(set(watching_symbols[symbol]['timeframes'] + timeframes))
    
    # Start monitoring if not running
    if not monitoring:
        monitoring = True
        app = context.application
        monitor_thread = threading.Thread(target=monitor_loop, args=(app.bot, chat_id), daemon=True)
        monitor_thread.start()
    
    await update.message.reply_text(
        f"✅ Now watching *{symbol}*\n"
        f"Timeframes: {', '.join(watching_symbols[symbol]['timeframes'])}\n"
        f"Alerts will be sent when:\n"
        f"• Close within 10% of high\n"
        f"• Momentum decreasing",
        parse_mode='Markdown'
    )


def get_alert_history(symbol: str, num_alerts: int = 10) -> str:
    """Get last N alerts for a symbol across all timeframes"""
    from strategies.sqz_momentum import calculate_sqzmom
    import yfinance as yf
    
    all_alerts = []
    timeframes = ['5m', '15m', '30m', '60m']
    
    for tf in timeframes:
        try:
            # Handle index symbols vs stock symbols
            if symbol.startswith('^'):
                ticker = yf.Ticker(symbol)
            else:
                ticker = yf.Ticker(f"{symbol.upper()}.NS")
            
            price_df = ticker.history(period="1mo", interval=tf)
            
            if price_df is None or len(price_df) < 25:
                continue
            
            sqz_df = calculate_sqzmom(price_df)
            
            if sqz_df.empty or len(sqz_df) < 3:
                continue
            
            # Check last N candles for alerts
            for i in range(2, min(len(sqz_df), 30)):
                curr = sqz_df.iloc[-i]
                prev = sqz_df.iloc[-i-1]
                
                close_near_high = curr['close_position'] >= 0.90
                momentum_decreasing = curr['momentum'] < prev['momentum']
                
                if close_near_high and momentum_decreasing:
                    # Determine if near high or low
                    close_pos = curr['close_position']
                    if close_pos >= 0.90:
                        near = "HIGH"
                    else:
                        near = "LOW"
                    
                    all_alerts.append({
                        'timeframe': tf,
                        'datetime': price_df.index[-i],
                        'price': curr['close'],
                        'momentum': curr['momentum'],
                        'squeeze': curr['squeeze'],
                        'close_pos': close_pos,
                        'near': near
                    })
                    
                    if len(all_alerts) >= num_alerts * len(timeframes):
                        break
            
            if len(all_alerts) >= num_alerts * len(timeframes):
                break
                
        except:
            continue
    
    if not all_alerts:
        return f"No alerts found for {symbol.upper()}"
    
    # Sort by datetime (newest first)
    all_alerts.sort(key=lambda x: x['datetime'], reverse=True)
    all_alerts = all_alerts[:num_alerts]
    
    # Build response
    response = f"📊 *Last {len(all_alerts)} Alerts: {symbol.upper()}*\n"
    response += f"═══════════════════════════════════\n"
    
    for i, a in enumerate(all_alerts, 1):
        response += f"{i}. {a['datetime'].strftime('%m/%d %H:%M')} | {a['timeframe']}\n"
        response += f"   ₹{a['price']:.0f} | {a['near']} ({a['close_pos']*100:.0f}%) | {a['squeeze']}\n"
    
    return response


async def alertlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /alertlist command"""
    text = update.message.text.replace('/alertlist', '').strip().upper()
    
    if not text:
        await update.message.reply_text("Usage: /alertlist SYMBOL\nExample: /alertlist SBIN")
        return
    
    symbol = text.split()[0]
    
    await update.message.reply_text(f"⏳ Fetching last 10 alerts for {symbol}...")
    
    result = get_alert_history(symbol, 10)
    await update.message.reply_text(result, parse_mode='Markdown')


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /summary command to toggle 5-min updates"""
    global summary_enabled
    
    text = update.message.text.replace('/summary', '').strip().upper()
    
    if text == 'ON':
        summary_enabled = True
        await update.message.reply_text("✅ 5-minute SQZMOM summary enabled")
    elif text == 'OFF':
        summary_enabled = False
        await update.message.reply_text("❌ 5-minute SQZMOM summary disabled")
    else:
        status = "ON" if summary_enabled else "OFF"
        await update.message.reply_text(f"Current status: {status}\nUse /summary ON or /summary OFF")


async def entry_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /entry command - check trade entry conditions"""
    text = update.message.text.replace('/entry', '').strip().upper()
    
    if not text:
        await update.message.reply_text("Usage: /entry SYMBOL\nExample: /entry SBIN")
        return
    
    symbol = text.split()[0]
    
    await update.message.reply_text(f"⏳ Checking entry conditions for {symbol}...")
    
    from strategies.sqz_momentum import check_entry_conditions
    
    result = check_entry_conditions(symbol)
    
    if result.get("error"):
        await update.message.reply_text(f"❌ Error: {result['error']}")
        return
    
    msg = f"📈 *Entry Check: {symbol}*\n"
    msg += f"═══════════════════════════\n"
    msg += f"🕐 {result.get('timestamp', 'N/A')}\n\n"
    msg += f"5m: Momentum={result.get('momentum_5m')} ({result.get('momentum_dir_5m')}) | Squeeze={result.get('squeeze_5m')}\n"
    msg += f"15m: Momentum={result.get('momentum_15m')} ({result.get('momentum_dir_15m')}) | Squeeze={result.get('squeeze_15m')}\n\n"
    msg += f"💰 Price: ₹{result.get('close_price')}\n"
    msg += f"📊 PSAR: ₹{result.get('psar_value')}\n"
    msg += f"Close %: {result.get('close_position', 0)*100:.0f}%\n\n"
    
    signal = result.get('signal')
    if signal:
        msg += f"🎯 *SIGNAL: {signal}!*\n"
        msg += f"Entry: ₹{result.get('entry_price')}\n"
        msg += f"SL: ₹{result.get('stop_loss')}\n"
    else:
        msg += "🎯 No signal (waiting for conditions)"
    
    await update.message.reply_text(msg, parse_mode='Markdown')


async def psar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /psar command - Check PSAR crossover with all TFs"""
    text = update.message.text.replace('/psar', '').strip().upper()
    
    if not text:
        await update.message.reply_text("Usage: /psar SYMBOL\nExample: /psar SBIN")
        return
    
    symbol = text.split()[0]
    
    await update.message.reply_text(f"⏳ Checking PSAR crossovers for {symbol}...")
    
    from strategies.sqz_momentum import get_psar_alert_message
    
    msg = get_psar_alert_message(symbol)
    
    await update.message.reply_text(msg, parse_mode='Markdown')


async def newalert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /newalert command - Check new alert logic"""
    text = update.message.text.replace('/newalert', '').strip().upper()
    
    if not text:
        await update.message.reply_text(
            "Usage: /newalert SYMBOL\n\n"
            "Checks for new alert logic:\n"
            "• 30m PSAR + squeeze in 60m,120m,240m,1d\n"
            "• 60m PSAR + squeeze in 120m,240m,1d\n"
            "• 120m PSAR + squeeze in 240m,1d\n\n"
            "Example: /newalert NIFTY",
            parse_mode='Markdown'
        )
        return
    
    symbol = text.split()[0]
    
    await update.message.reply_text(f"⏳ Checking new alerts for {symbol}...")
    
    from strategies.sqz_momentum import format_new_alert_message
    
    msg = format_new_alert_message(symbol)
    
    await update.message.reply_text(msg, parse_mode='Markdown')


async def psarscan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /psarscan command - Scan Nifty F&O stocks for PSAR crossovers"""
    text = update.message.text.replace('/psarscan', '').strip().upper()
    
    # Nifty F&O stocks to scan
    NIFTY_FO_STOCKS = [
        'RELIANCE', 'TCS', 'HDFCBANK', 'ICICIBANK', 'INFY', 'KOTAKBANK',
        'SBIN', 'BAJFINANCE', 'HINDUNILVR', 'ITC', 'LTIM', 'NTPC',
        'POWERGRID', 'MARRICO', 'TITAN', 'SUNPHARMA', 'AXISBANK',
        'MARUTI', 'TATASTEEL', 'WIPRO', 'ADANIPORTS', 'GRASIM'
    ]
    
    # Timeframes to check
    TIMEFRAMES = ['60m', '4h', '1d', '1w']
    
    await update.message.reply_text(f"🔍 Scanning {len(NIFTY_FO_STOCKS)} stocks across {len(TIMEFRAMES)} timeframes...\nThis may take a minute...", parse_mode='Markdown')
    
    from strategies.sqz_momentum import check_psar_crossover
    import yfinance as yf
    
    results = {'BUY': [], 'SELL': []}
    
    for symbol in NIFTY_FO_STOCKS:
        for tf in TIMEFRAMES:
            try:
                # Map timeframe
                tf_map = {'60m': '1h', '4h': '4h', '1d': '1d', '1w': '1wk'}
                interval = tf_map.get(tf, tf)
                
                # Get data
                ticker = yf.Ticker(f"{symbol}.NS")
                df = ticker.history(period="30d", interval=interval)
                
                if df is None or len(df) < 10:
                    continue
                
                # Check PSAR crossover
                psar_result = check_psar_crossover(symbol, tf)
                
                if psar_result.get('crossover'):
                    direction = psar_result['crossover']
                    results[direction].append({
                        'symbol': symbol,
                        'timeframe': tf,
                        'price': psar_result.get('price'),
                        'psar_before': psar_result.get('psar_before'),
                        'psar_after': psar_result.get('psar_after'),
                        'timestamp': psar_result.get('timestamp')
                    })
            except Exception as e:
                continue
    
    # Format message
    msg = "📊 *PSAR CROSSOVER SCAN RESULTS*\n"
    msg += f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    msg += "═══════════════════════════\n\n"
    
    if results['BUY']:
        msg += "🟢 *BUY SIGNALS (PSAR crosses ABOVE):*\n"
        for r in results['BUY']:
            msg += f"• {r['symbol']} [{r['timeframe']}] @ ₹{r['price']:.2f}\n"
        msg += "\n"
    
    if results['SELL']:
        msg += "🔴 *SELL SIGNALS (PSAR crosses BELOW):*\n"
        for r in results['SELL']:
            msg += f"• {r['symbol']} [{r['timeframe']}] @ ₹{r['price']:.2f}\n"
        msg += "\n"
    
    if not results['BUY'] and not results['SELL']:
        msg += "ℹ️ No PSAR crossovers found in any timeframe."
    
    total = len(results['BUY']) + len(results['SELL'])
    msg += f"\nTotal: {total} signals"
    
    await update.message.reply_text(msg, parse_mode='Markdown')


async def token_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /token command to update Flatrade credentials"""
    global FLATTRADE_TOKEN, FLATTRADE_USER_ID, FLATTRADE_API_KEY
    
    text = update.message.text.replace('/token', '').strip()
    
    if not text:
        # Show current status
        if FLATTRADE_TOKEN:
            await update.message.reply_text(
                "✅ *Flattrade Connected*\n"
                f"User ID: `{FLATTRADE_USER_ID or 'Set'}`\n"
                f"Token: `{FLATTRADE_TOKEN[:20]}...`\n\n"
                "To update, send:\n"
                "/token YOUR_USER_ID YOUR_TOKEN",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "❌ *Flattrade Not Connected*\n\n"
                "To set credentials, send:\n"
                "/token YOUR_USER_ID YOUR_TOKEN"
            )
        return
    
    # Parse token and user_id
    parts = text.split()
    if len(parts) >= 2:
        FLATTRADE_USER_ID = parts[0]
        FLATTRADE_TOKEN = parts[1]
        if len(parts) >= 3:
            FLATTRADE_API_KEY = parts[2]
        
        # Try to connect
        try:
            from data.flattrade_connector import init_flatrade
            init_flatrade(user_id=FLATTRADE_USER_ID, token=FLATTRADE_TOKEN)
            await update.message.reply_text(
                "✅ *Flattrade Token Updated!*\n\n"
                f"User ID: `{FLATTRADE_USER_ID}`\n"
                f"Token: Set ✓\n\n"
                "Data will now be fetched from Flatrade API",
                parse_mode='Markdown'
            )
        except Exception as e:
            await update.message.reply_text(
                f"⚠️ Token stored but connection test failed:\n`{str(e)}`\n\n"
                "Will try using it anyway.",
                parse_mode='Markdown'
            )
    else:
        await update.message.reply_text(
            "Usage: /token USER_ID TOKEN [API_KEY]\n"
            "Example: /token DEMO123 abcdef123456"
        )


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stop command"""
    global watching_symbols
    
    text = update.message.text.replace('/stop', '').strip().upper()
    
    if not text:
        await update.message.reply_text("Usage: /stop SYMBOL")
        return
    
    if text in watching_symbols:
        del watching_symbols[text]
        await update.message.reply_text(f"✅ Stopped watching {text}")
    else:
        await update.message.reply_text(f"{text} is not being watched")


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /list command"""
    global watching_symbols, monitoring
    
    if not watching_symbols:
        await update.message.reply_text("No symbols being watched.\nUse /watch SYMBOL to start.")
        return
    
    msg = "📋 *Watching Symbols:*\n\n"
    for symbol, config in watching_symbols.items():
        msg += f"• {symbol}: {', '.join(config['timeframes'])}\n"
    
    msg += f"\n🟢 Monitoring: {'Active' if monitoring else 'Inactive'}"
    
    await update.message.reply_text(msg, parse_mode='Markdown')


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command"""
    global monitoring
    
    status = "🟢 Running" if monitoring else "🔴 Stopped"
    
    await update.message.reply_text(
        f"📊 *Status:* {status}\n"
        f"Watching: {len(watching_symbols)} symbols",
        parse_mode='Markdown'
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages"""
    text = update.message.text.strip()
    
    # Check if it's a command (starts with /)
    if text.startswith('/'):
        await update.message.reply_text("Unknown command. Use /watch, /stop, /list, /status, or /alertlist")
        return
    
    # Only process non-command messages
    text = text.upper()
    parts = text.split()
    symbol = parts[0]
    
    # If symbol is in our list, treat as watch
    valid_symbols = ['SBIN', 'RELIANCE', 'INFY', 'TCS', 'HDFCBANK', 'NIFTY', 'BANKNIFTY']
    
    # Treat as watch command - default to all timeframes
    if len(parts) > 1:
        timeframes = parts[1].split(',')
    else:
        timeframes = ['5m', '15m', '30m', '60m']
    
    valid_tf = ['5m', '15m', '30m', '60m']
    timeframes = [tf for tf in timeframes if tf in valid_tf]
    if not timeframes:
        timeframes = ['5m', '15m', '30m', '60m']
    
    global watching_symbols, monitoring, monitor_thread
    
    chat_id = update.message.chat_id
    
    if symbol not in watching_symbols:
        watching_symbols[symbol] = {'timeframes': timeframes, 'chat_id': chat_id}
    else:
        watching_symbols[symbol]['timeframes'] = list(set(watching_symbols[symbol]['timeframes'] + timeframes))
    
    # Start monitoring if not running
    if not monitoring:
        monitoring = True
        app = context.application
        monitor_thread = threading.Thread(target=monitor_loop, args=(app.bot, chat_id), daemon=True)
        monitor_thread.start()
    
    await update.message.reply_text(
        f"✅ Now watching *{symbol}*\n"
        f"Timeframes: {', '.join(watching_symbols[symbol]['timeframes'])}",
        parse_mode='Markdown'
    )


def main():
    """Start the bot"""
    logger.info("Starting Telegram alert bot...")
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("watch", watch_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("list", list_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("alertlist", alertlist_command))
    app.add_handler(CommandHandler("summary", summary_command))
    app.add_handler(CommandHandler("entry", entry_command))
    app.add_handler(CommandHandler("psar", psar_command))
    app.add_handler(CommandHandler("newalert", newalert_command))
    app.add_handler(CommandHandler("psarscan", psarscan_command))
    app.add_handler(CommandHandler("token", token_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Bot is running...")
    app.run_polling(poll_interval=3)


if __name__ == "__main__":
    main()