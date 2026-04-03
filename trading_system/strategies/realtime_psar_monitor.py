"""
Real-time PSAR Crossover Monitor
Uses Flattrade WebSocket for live data to detect PSAR crossovers
"""

import logging
import time
import threading
import json
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Optional

import pandas as pd
import numpy as np
import websocket as ws_client

logger = logging.getLogger(__name__)

# Nifty F&O stocks to monitor
NIFTY_FO_STOCKS = [
    'RELIANCE', 'TCS', 'HDFCBANK', 'ICICIBANK', 'INFY', 'KOTAKBANK',
    'SBIN', 'BAJFINANCE', 'HINDUNILVR', 'ITC', 'LTIM', 'NTPC',
    'POWERGRID', 'MARRICO', 'TITAN', 'SUNPHARMA', 'AXISBANK',
    'MARUTI', 'TATASTEEL', 'WIPRO', 'ADANIPORTS', 'GRASIM',
    'CIPLA', 'DRREDDY', 'EICHERMOT', 'HCLTECH', 'HEROMOTOCO',
    'INDUSINDBK', 'JSWSTEEL', 'ONGC', 'SHREECEM', 'TATAMOTORS',
    'UPL', 'VEDL', 'COALINDIA', 'BPCL', 'HINDZINC', 'DIVISLAB',
    'APOLLOHOSP', 'BRITANNIA', 'DLF', 'GODREJPROP', 'IRCTC',
    'JINDALSTEL', 'LIC', 'M&M', 'NESTLE', 'RECLTD', 'SBICARD',
    'SIEMENS', 'TATACONS', 'TECHM', 'TORNPHARM', 'ULTRACEMCO'
]

# Timeframes to monitor
TIMEFRAMES = ['60m', '4h', '1d']  # 1hr, 4hr, 1day


class RealtimePSARMonitor:
    """
    Real-time PSAR crossover monitor using Flattrade WebSocket
    """
    
    def __init__(self, flattrade_connector=None, telegram_bot=None):
        self.ft = flattrade_connector
        self.bot = telegram_bot
        self.running = False
        self.thread = None
        
        # Price data storage: {symbol: {timeframe: DataFrame}}
        self.price_data = defaultdict(lambda: defaultdict(pd.DataFrame))
        
        # Last PSAR state to detect crossovers: {symbol: {timeframe: 'above'|'below'}}
        self.last_psar_state = defaultdict(dict)
        
        # Alert history to avoid duplicates
        self.last_alerts = {}  # {symbol: {timeframe: timestamp}}
        
        # Candle building buffers
        self.tick_buffer = defaultdict(lambda: defaultdict(lambda: {
            'open': None, 'high': None, 'low': None, 'close': None, 'volume': 0
        }))
    
    def start(self):
        """Start the monitoring service"""
        if self.running:
            logger.warning("Monitor already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run_monitor, daemon=True)
        self.thread.start()
        logger.info("Real-time PSAR Monitor started")
    
    def stop(self):
        """Stop the monitoring service"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Real-time PSAR Monitor stopped")
    
    def _run_monitor(self):
        """Main monitoring loop"""
        # Initialize historical data for all stocks
        self._load_historical_data()
        
        # Start WebSocket for live prices
        self._start_websocket_feed()
        
        # Main loop - check PSAR every 60 seconds
        while self.running:
            try:
                self._check_all_crossovers()
                time.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Monitor error: {e}")
                time.sleep(30)
    
    def _load_historical_data(self):
        """Load historical data for all stocks"""
        logger.info("Loading historical data...")
        
        for symbol in NIFTY_FO_STOCKS:
            for tf in TIMEFRAMES:
                try:
                    # Get historical data from Flattrade or Yahoo
                    if self.ft and self.ft.connected:
                        df = self.ft.get_historical_data(symbol, 
                            interval=self._get_flattrade_interval(tf),
                            days=30)
                    
                    if df is None or df.empty:
                        # Fallback to Yahoo
                        df = self._get_yahoo_data(symbol, tf)
                    
                    if not df.empty:
                        self.price_data[symbol][tf] = df
                        self._init_psar_state(symbol, tf)
                        
                except Exception as e:
                    logger.debug(f"Could not load {symbol} {tf}: {e}")
        
        logger.info(f"Loaded data for {len(self.price_data)} stocks")
    
    def _get_yahoo_data(self, symbol: str, tf: str) -> pd.DataFrame:
        """Fallback to Yahoo Finance"""
        try:
            import yfinance as yf
            tf_map = {'60m': '1h', '4h': '4h', '1d': '1d', '1w': '1wk'}
            interval = tf_map.get(tf, tf)
            
            ticker = yf.Ticker(f"{symbol}.NS")
            df = ticker.history(period="30d", interval=interval)
            
            if df is not None and not df.empty:
                return df
        except:
            pass
        return pd.DataFrame()
    
    def _get_flattrade_interval(self, tf: str) -> str:
        """Convert timeframe to Flattrade interval"""
        mapping = {'60m': '60min', '4h': '60min', '1d': '1min', '1w': '1min'}
        return mapping.get(tf, '5min')
    
    def _init_psar_state(self, symbol: str, tf: str):
        """Initialize PSAR state for a symbol/timeframe"""
        df = self.price_data[symbol].get(tf)
        if df is None or df.empty or len(df) < 2:
            return
        
        # Calculate PSAR
        psar = self._calculate_psar(df)
        if psar is not None and len(psar) > 0:
            current_close = df['Close'].iloc[-1]
            current_psar = psar.iloc[-1]
            
            if current_psar > current_close:
                self.last_psar_state[symbol][tf] = 'above'
            else:
                self.last_psar_state[symbol][tf] = 'below'
    
    def _start_websocket_feed(self):
        """Start WebSocket connection to Flattrade"""
        # This would connect to Flattrade's WebSocket feed
        # For now, use polling fallback
        self._start_polling()
    
    def _start_polling(self):
        """Fallback polling method"""
        def poll_loop():
            while self.running:
                try:
                    # Get live quotes for all stocks
                    for symbol in NIFTY_FO_STOCKS:
                        if self.ft and self.ft.connected:
                            quote = self.ft.get_quote(symbol)
                            if quote:
                                self._update_live_price(symbol, quote)
                    
                    time.sleep(10)  # Poll every 10 seconds
                except Exception as e:
                    logger.error(f"Polling error: {e}")
                    time.sleep(30)
        
        thread = threading.Thread(target=poll_loop, daemon=True)
        thread.start()
    
    def _update_live_price(self, symbol: str, quote: dict):
        """Update live price and build candles"""
        # This would aggregate ticks into candles
        # Simplified - just update close price
        for tf in TIMEFRAMES:
            df = self.price_data[symbol].get(tf)
            if df is not None and not df.empty:
                # Add new candle or update current
                last_time = df.index[-1]
                
                # Create new row with live price
                new_row = pd.DataFrame({
                    'Open': [quote.get('last', quote.get('close', df['Close'].iloc[-1]))],
                    'High': [quote.get('high', quote.get('last', df['High'].iloc[-1]))],
                    'Low': [quote.get('low', quote.get('last', df['Low'].iloc[-1]))],
                    'Close': [quote.get('last', df['Close'].iloc[-1])],
                    'Volume': [quote.get('volume', 0)]
                }, index=[pd.Timestamp.now()])
                
                # Append to dataframe (in production, would aggregate properly)
                self.price_data[symbol][tf] = pd.concat([df, new_row]).tail(100)
    
    def _check_all_crossovers(self):
        """Check PSAR crossovers for all stocks"""
        current_time = datetime.now()
        
        for symbol in NIFTY_FO_STOCKS:
            for tf in TIMEFRAMES:
                try:
                    self._check_crossover(symbol, tf, current_time)
                except Exception as e:
                    logger.debug(f"Error checking {symbol} {tf}: {e}")
    
    def _check_crossover(self, symbol: str, tf: str, current_time: datetime):
        """Check for PSAR crossover in a symbol/timeframe"""
        df = self.price_data[symbol].get(tf)
        if df is None or df.empty or len(df) < 2:
            return
        
        # Get current candle
        current = df.iloc[-1]
        previous = df.iloc[-2] if len(df) >= 2 else None
        if previous is None:
            return
        
        # Calculate current PSAR
        psar = self._calculate_psar(df)
        if psar is None or len(psar) < 2:
            return
        
        current_psar = psar.iloc[-1]
        prev_psar = psar.iloc[-2]
        
        current_price = current['Close']
        prev_price = previous['Close']
        
        # Determine current PSAR position
        current_psar_above = current_psar > current_price
        prev_psar_above = prev_psar > prev_price
        
        # Check for crossover
        crossover = None
        
        # BUY: PSAR crosses ABOVE price (was below, now above)
        if not prev_psar_above and current_psar_above:
            crossover = 'BUY'
        
        # SELL: PSAR crosses BELOW price (was above, now below)
        elif prev_psar_above and not current_psar_above:
            crossover = 'SELL'
        
        if crossover:
            # Check if we already alerted recently (avoid spam)
            alert_key = f"{symbol}_{tf}"
            last_alert = self.last_alerts.get(alert_key)
            
            # Only alert if not alerted in last 1 hour
            if last_alert is None or (current_time - last_alert).total_seconds() > 3600:
                self._send_alert(symbol, tf, crossover, current_price, current_psar)
                self.last_alerts[alert_key] = current_time
    
    def _calculate_psar(self, df: pd.DataFrame, af: float = 0.02, max_af: float = 0.2) -> pd.Series:
        """Calculate Parabolic SAR"""
        if len(df) < 2:
            return pd.Series()
        
        try:
            high = df['High'].values
            low = df['Low'].values
            close = df['Close'].values
            
            psar = np.zeros(len(close))
            trend = np.zeros(len(close))
            
            # Initialize
            psar[0] = close[0]
            trend[0] = 1
            
            for i in range(1, len(close)):
                if trend[i-1] == 1:  # Uptrend
                    psar[i] = psar[i-1] + af * (high[i-1] - psar[i-1])
                    
                    if low[i] < psar[i]:
                        trend[i] = -1
                        psar[i] = high[i-1]
                        af = 0.02
                    else:
                        trend[i] = 1
                        if high[i] > high[i-1] and af < max_af:
                            af += 0.01
                else:  # Downtrend
                    psar[i] = psar[i-1] + af * (low[i-1] - psar[i-1])
                    
                    if high[i] > psar[i]:
                        trend[i] = 1
                        psar[i] = low[i-1]
                        af = 0.02
                    else:
                        trend[i] = -1
                        if low[i] < low[i-1] and af < max_af:
                            af += 0.01
            
            return pd.Series(psar, index=df.index)
        except:
            return pd.Series()
    
    def _send_alert(self, symbol: str, tf: str, direction: str, price: float, psar: float):
        """Send Telegram alert"""
        if not self.bot:
            logger.info(f"ALERT: {symbol} {tf} {direction} @ ₹{price:.2f}")
            return
        
        emoji = "🟢" if direction == "BUY" else "🔴"
        
        msg = f"""
{emoji} *PSAR CROSSOVER ALERT*

📊 *{symbol}* [{tf}]
💰 Price: ₹{price:.2f}
📈 PSAR: ₹{psar:.2f}
🔄 Signal: {direction}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        try:
            # Would send via Telegram
            logger.info(f"Sending alert: {msg}")
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")


# Singleton instance
_monitor = None

def get_monitor(flattrade_connector=None, telegram_bot=None) -> RealtimePSARMonitor:
    """Get or create the monitor instance"""
    global _monitor
    if _monitor is None:
        _monitor = RealtimePSARMonitor(flattrade_connector, telegram_bot)
    return _monitor

def start_monitoring(flattrade_connector=None, telegram_bot=None):
    """Start the real-time monitoring"""
    monitor = get_monitor(flattrade_connector, telegram_bot)
    monitor.start()
    return monitor

def stop_monitoring():
    """Stop the monitoring"""
    global _monitor
    if _monitor:
        _monitor.stop()
        _monitor = None