"""
Real-time PSAR Crossover Monitor
Uses Flattrade WebSocket for live data to detect PSAR crossovers
"""

import logging
import time
import threading
import json
import queue
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Optional
import websocket as ws_client

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# Nifty F&O stocks to monitor (top 50 for real-time)
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
TIMEFRAMES = ['60m', '4h', '1d']

# Flattrade WebSocket endpoints
FLATTRADE_WS_URL = "wss://pfeed.flattrade.in/"
FLATTRADE_API_URL = "https://piconnect.flattrade.in/PiConnectAPI"


class RealtimePSARMonitor:
    """
    Real-time PSAR crossover monitor using Flattrade WebSocket
    
    Token Setup:
    -------------
    1. Get your Flattrade credentials:
       - User ID (your trading username)
       - Token (session token from Flattrade Pi)
       
    2. To get feed token for WebSocket:
       - Call API: https://piconnect.flattrade.in/PiConnectAPI/api/marketDataFeed
       - This returns a feed_token needed for WebSocket connection
       
    3. Set token using /token command in Telegram bot
    
    4. The monitor will:
       - Use REST API to get feed token
       - Connect to WebSocket for live ticks
       - Build candles from tick data
       - Calculate PSAR and detect crossovers
    """
    
    def __init__(self, flattrade_connector=None, telegram_bot=None):
        self.ft = flattrade_connector
        self.bot = telegram_bot
        self.running = False
        self.thread = None
        
        # WebSocket connection
        self.ws = None
        self.ws_thread = None
        self.feed_token = None
        
        # Price data storage: {symbol: {timeframe: DataFrame}}
        self.price_data = defaultdict(lambda: defaultdict(pd.DataFrame))
        
        # Live tick buffer for candle building
        self.tick_data = defaultdict(lambda: {
            'last_price': None,
            'last_time': None,
            'ohlc': {'open': None, 'high': None, 'low': None, 'close': None, 'volume': 0}
        })
        
        # Last PSAR state to detect crossovers
        self.last_psar_state = defaultdict(dict)
        
        # Alert history to avoid duplicates
        self.last_alerts = {}
        
        # Message queue for WebSocket
        self.ws_queue = queue.Queue()
        
        # Symbol to token mapping for Flattrade
        self.symbol_tokens = self._get_nse_tokens()
    
    def _get_nse_tokens(self) -> Dict[str, str]:
        """Get NSE symbol to token mapping for Flattrade"""
        # Common Nifty F&O stock tokens (Flattrade uses numeric tokens)
        return {
            'RELIANCE': '2885', 'TCS': '11536', 'HDFCBANK': '133', 'ICICIBANK': '1190',
            'INFY': '1594', 'KOTAKBANK': '1922', 'SBIN': '3045', 'BAJFINANCE': '317',
            'HINDUNILVR': '1394', 'ITC': '1665', 'LTIM': '17818', 'NTPC': '11630',
            'POWERGRID': '12287', 'MARRICO': '13638', 'TITAN': '3570', 'SUNPHARMA': '2891',
            'AXISBANK': '1730', 'MARUTI': '10999', 'TATASTEEL': '3260', 'WIPRO': '3787',
            'ADANIPORTS': '15025', 'GRASIM': '1232', 'CIPLA': '1777', 'DRREDDY': '2721',
            'EICHERMOT': '1909', 'HCLTECH': '7229', 'HEROMOTOCO': '8887', 'INDUSINDBK': '2050',
            'JSWSTEEL': '11723', 'ONGC': '2475', 'SHREECEM': '5902', 'TATAMOTORS': '3456',
            'UPL': '11287', 'VEDL': '3066', 'COALINDIA': '13418', 'BPCL': '1268',
            'HINDZINC': '3040', 'DIVISLAB': '2666', 'APOLLOHOSP': '1570', 'BRITANNIA': '2449',
            'DLF': '3024', 'GODREJPROP': '16530', 'IRCTC': '14738', 'JINDALSTEL': '10444',
            'LIC': '13118', 'M&M': '2050', 'NESTLE': '17968', 'RECLTD': '17348', 'SBICARD': '27419',
            'SIEMENS': '12053', 'TATACONS': '13795', 'TECHM': '5170', 'TORNPHARM': '5070,
            'ULTRACEMCO': '11630'
        }
    
    def start(self, feed_token: str = None):
        """Start the monitoring service"""
        if self.running:
            logger.warning("Monitor already running")
            return
        
        self.running = True
        
        # If feed token provided, use it; otherwise get from API
        if feed_token:
            self.feed_token = feed_token
        elif self.ft and self.ft.connected:
            self.feed_token = self._get_feed_token()
        
        self.thread = threading.Thread(target=self._run_monitor, daemon=True)
        self.thread.start()
        logger.info("Real-time PSAR Monitor started")
    
    def _get_feed_token(self) -> Optional[str]:
        """Get feed token from Flattrade API"""
        try:
            if self.ft and self.ft.api:
                # Call the market data feed API to get feed token
                result = self.ft.api.get_market_data_feed()
                if result and result.get('stat') == 'Ok':
                    return result.get('feedToken')
        except Exception as e:
            logger.error(f"Failed to get feed token: {e}")
        return None
    
    def stop(self):
        """Stop the monitoring service"""
        self.running = False
        
        # Close WebSocket
        if self.ws:
            try:
                self.ws.close()
            except:
                pass
        
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Real-time PSAR Monitor stopped")
    
    def _run_monitor(self):
        """Main monitoring loop"""
        # Initialize historical data for all stocks
        self._load_historical_data()
        
        # Start WebSocket for live prices
        if self.feed_token:
            self._start_websocket()
        else:
            logger.warning("No feed token, using polling fallback")
            self._start_polling()
        
        # Main loop - check PSAR every 60 seconds
        while self.running:
            try:
                # Update candles from tick data
                self._update_candles_from_ticks()
                
                # Check PSAR crossovers
                self._check_all_crossovers()
                
                time.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Monitor error: {e}")
                time.sleep(30)
    
    def _start_websocket(self):
        """Start WebSocket connection to Flattrade"""
        if not self.feed_token:
            logger.error("No feed token available for WebSocket")
            return
        
        def ws_loop():
            try:
                # Flattrade WebSocket connection
                ws_url = f"{FLATTRADE_WS_URL}?feed_token={self.feed_token}&client=PI"
                
                self.ws = ws_client.WebSocketApp(
                    ws_url,
                    on_message=self._on_ws_message,
                    on_error=self._on_ws_error,
                    on_close=self._on_ws_close,
                    on_open=self._on_ws_open
                )
                
                self.ws.run_forever(ping_interval=30)
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
        
        self.ws_thread = threading.Thread(target=ws_loop, daemon=True)
        self.ws_thread.start()
        logger.info("WebSocket thread started")
    
    def _on_ws_open(self, ws):
        """WebSocket opened"""
        logger.info("WebSocket connected")
        
        # Subscribe to all symbols
        for symbol, token in self.symbol_tokens.items():
            sub_msg = {
                "action": "subscribe",
                "instrument": f"NSE:{token}",
                "channel": "ltpc"
            }
            ws.send(json.dumps(sub_msg))
    
    def _on_ws_message(self, ws, message):
        """Handle WebSocket message"""
        try:
            data = json.loads(message)
            
            # Parse tick data
            # Flattrade format: {"instrument": "NSE:3045", "last": 1050.50, ...}
            if 'instrument' in data and 'last' in data:
                instrument = data['instrument']
                token = instrument.split(':')[1] if ':' in instrument else instrument
                
                # Find symbol from token
                symbol = None
                for sym, tok in self.symbol_tokens.items():
                    if tok == token:
                        symbol = sym
                        break
                
                if symbol:
                    self._process_tick(symbol, data)
                    
        except Exception as e:
            logger.debug(f"WS message error: {e}")
    
    def _on_ws_error(self, ws, error):
        """WebSocket error"""
        logger.error(f"WebSocket error: {error}")
    
    def _on_ws_close(self, ws, close_status_code, close_msg):
        """WebSocket closed"""
        logger.warning(f"WebSocket closed: {close_status_code} - {close_msg}")
        
        # Try to reconnect after 5 seconds
        if self.running:
            time.sleep(5)
            if self.feed_token:
                self._start_websocket()
    
    def _process_tick(self, symbol: str, data: dict):
        """Process live tick data"""
        price = data.get('last')
        volume = data.get('volume', 0)
        timestamp = data.get('timestamp', time.time())
        
        if price is None:
            return
        
        current_time = datetime.fromtimestamp(timestamp) if isinstance(timestamp, (int, float)) else datetime.now()
        
        # Initialize if first tick
        if self.tick_data[symbol]['last_price'] is None:
            self.tick_data[symbol]['ohlc'] = {
                'open': price, 'high': price, 'low': price, 'close': price, 'volume': volume
            }
        else:
            ohlc = self.tick_data[symbol]['ohlc']
            ohlc['close'] = price
            ohlc['high'] = max(ohlc['high'], price)
            ohlc['low'] = min(ohlc['low'], price)
            ohlc['volume'] += volume
        
        self.tick_data[symbol]['last_price'] = price
        self.tick_data[symbol]['last_time'] = current_time
    
    def _update_candles_from_ticks(self):
        """Update OHLC candles from tick data for all timeframes"""
        for symbol in self.tick_data:
            if self.tick_data[symbol]['last_price'] is None:
                continue
            
            ohlc = self.tick_data[symbol]['ohlc']
            current_time = self.tick_data[symbol]['last_time']
            
            for tf in TIMEFRAMES:
                # Get existing data
                df = self.price_data[symbol].get(tf)
                if df is None or df.empty:
                    continue
                
                # Determine current candle time based on timeframe
                candle_time = self._get_candle_time(current_time, tf)
                
                if len(df) > 0:
                    last_time = df.index[-1]
                    
                    # If same candle, update it
                    if last_time == candle_time:
                        last_row = df.iloc[-1].copy()
                        last_row['High'] = max(last_row['High'], ohlc['high'])
                        last_row['Low'] = min(last_row['Low'], ohlc['low'])
                        last_row['Close'] = ohlc['close']
                        last_row['Volume'] += ohlc['volume']
                        df.iloc[-1] = last_row
                    else:
                        # New candle
                        new_row = pd.DataFrame({
                            'Open': [ohlc['open']],
                            'High': [ohlc['high']],
                            'Low': [ohlc['low']],
                            'Close': [ohlc['close']],
                            'Volume': [ohlc['volume']]
                        }, index=[candle_time])
                        df = pd.concat([df, new_row])
                        
                        # Keep only last 100 candles
                        df = df.tail(100)
                    
                    self.price_data[symbol][tf] = df
    
    def _get_candle_time(self, dt: datetime, tf: str) -> pd.Timestamp:
        """Get candle timestamp for timeframe"""
        if tf == '60m':
            return dt.replace(minute=0, second=0, microsecond=0)
        elif tf == '4h':
            hour = (dt.hour // 4) * 4
            return dt.replace(hour=hour, minute=0, second=0, microsecond=0)
        elif tf == '1d':
            return dt.replace(hour=0, minute=0, second=0, microsecond=0)
        return dt
    
    def _start_polling(self):
        """Fallback polling method when WebSocket not available"""
        def poll_loop():
            while self.running:
                try:
                    # Get live quotes for all stocks via REST API
                    if self.ft and self.ft.connected:
                        for symbol in list(self.symbol_tokens.keys())[:50]:
                            try:
                                quote = self.ft.get_quote(symbol)
                                if quote:
                                    self._process_tick(symbol, {
                                        'last': quote.get('last'),
                                        'volume': quote.get('volume', 0),
                                        'timestamp': time.time()
                                    })
                            except:
                                pass
                    
                    time.sleep(10)  # Poll every 10 seconds
                except Exception as e:
                    logger.error(f"Polling error: {e}")
                    time.sleep(30)
        
        thread = threading.Thread(target=poll_loop, daemon=True)
        thread.start()
    
    def _load_historical_data(self):
        """Load historical data for all stocks"""
        logger.info("Loading historical data...")
        
        for symbol in NIFTY_FO_STOCKS:
            for tf in TIMEFRAMES:
                try:
                    df = None
                    
                    # Try Flattrade first
                    if self.ft and self.ft.connected:
                        df = self.ft.get_historical_data(symbol, 
                            interval=self._get_flattrade_interval(tf),
                            days=30)
                    
                    # Fallback to Yahoo
                    if df is None or df.empty:
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
            tf_map = {'60m': '1h', '4h': '4h', '1d': '1d'}
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
        mapping = {'60m': '60min', '4h': '60min', '1d': '1min'}
        return mapping.get(tf, '5min')
    
    def _init_psar_state(self, symbol: str, tf: str):
        """Initialize PSAR state for a symbol/timeframe"""
        df = self.price_data[symbol].get(tf)
        if df is None or df.empty or len(df) < 2:
            return
        
        psar = self._calculate_psar(df)
        if psar is not None and len(psar) > 0:
            current_close = df['Close'].iloc[-1]
            current_psar = psar.iloc[-1]
            
            if current_psar > current_close:
                self.last_psar_state[symbol][tf] = 'above'
            else:
                self.last_psar_state[symbol][tf] = 'below'
    
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
        
        current = df.iloc[-1]
        previous = df.iloc[-2] if len(df) >= 2 else None
        if previous is None:
            return
        
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
        
        # BUY: PSAR crosses ABOVE price
        if not prev_psar_above and current_psar_above:
            crossover = 'BUY'
        # SELL: PSAR crosses BELOW price
        elif prev_psar_above and not current_psar_above:
            crossover = 'SELL'
        
        if crossover:
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
            logger.info(f"Alert: {msg}")
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

def start_monitoring(flattrade_connector=None, telegram_bot=None, feed_token: str = None):
    """Start the real-time monitoring"""
    monitor = get_monitor(flattrade_connector, telegram_bot)
    monitor.start(feed_token)
    return monitor

def stop_monitoring():
    """Stop the monitoring"""
    global _monitor
    if _monitor:
        _monitor.stop()
        _monitor = None