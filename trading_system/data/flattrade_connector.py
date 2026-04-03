"""
Flatrade API Connector
Connects to Flatrade PI API for live market data and historical data
"""

import logging
import time
import threading
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable

# Try to import Flatrade API, if not available use mock
try:
    from api_helper import NorenApiPy
    FLATTRADE_AVAILABLE = True
except ImportError:
    FLATTRADE_AVAILABLE = False
    print("Flattrade API not installed. Using mock data.")

import pandas as pd
import websocket

logger = logging.getLogger(__name__)


class FlatradeConnector:
    """
    Flatrade API Connector for fetching live and historical data
    """
    
    def __init__(self, api_key: str = None, api_secret: str = None, 
                 user_id: str = None, token: str = None):
        """
        Initialize Flatrade API connection
        
        Args:
            api_key: API Key from Flatrade Pi
            api_secret: API Secret
            user_id: User ID
            token: Session token
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.user_id = user_id
        self.token = token
        self.api = None
        self.connected = False
        
        # Data storage
        self.live_quotes = {}  # Current LTP for subscribed symbols
        self.historical_data = {}  # OHLC data storage
        self.candle_data = {}  # Aggregated candle data per timeframe
        
        # WebSocket for live data
        self.ws = None
        self.ws_subscriptions = set()
        self.ws_thread = None
        
        # Callback for live data updates
        self.on_price_update = None
        
    def connect(self) -> bool:
        """Connect to Flatrade API"""
        if not FLATTRADE_AVAILABLE:
            logger.warning("Flatrade API not available, using mock mode")
            self.connected = True
            return True
            
        try:
            self.api = NorenApiPy()
            
            # Set session if token provided
            if self.token and self.user_id:
                ret = self.api.set_session(userid=self.user_id, 
                                          password='', 
                                          usertoken=self.token)
                if ret.get('stat') == 'Ok':
                    self.connected = True
                    logger.info("Connected to Flatrade API")
                    return True
                else:
                    logger.error(f"Session failed: {ret}")
                    return False
            else:
                logger.warning("No token provided, API calls may fail")
                self.connected = True
                return True
                
        except Exception as e:
            logger.error(f"Failed to connect to Flatrade: {e}")
            return False
    
    def search_symbol(self, query: str) -> List[Dict]:
        """Search for symbols"""
        if not self.api or not self.connected:
            return []
            
        try:
            result = self.api.searchscrip(exchange='NSE', searchtext=query)
            return result if result else []
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []
    
    def get_quote(self, symbol: str) -> Optional[Dict]:
        """Get live quote for a symbol"""
        if not self.connected:
            return None
            
        try:
            if FLATTRADE_AVAILABLE and self.api:
                result = self.api.get_quotes(exchange='NSE', 
                                            tradingsymbol=symbol)
                return result[0] if result else None
            else:
                # Mock data
                return self._get_mock_quote(symbol)
        except Exception as e:
            logger.error(f"Get quote failed: {e}")
            return None
    
    def get_historical_data(self, symbol: str, 
                           interval: str = '5min',
                           days: int = 30) -> pd.DataFrame:
        """
        Get historical intraday data
        
        Args:
            symbol: Trading symbol (e.g., 'SBIN')
            interval: 1min, 5min, 15min, 60min
            days: Number of days of data
            
        Returns:
            DataFrame with OHLC data
        """
        if not self.connected:
            return pd.DataFrame()
            
        try:
            if FLATTRADE_AVAILABLE and self.api:
                # Convert interval format
                interval_map = {
                    '1min': '1',
                    '5min': '5',
                    '15min': '15',
                    '60min': '60'
                }
                ft_interval = interval_map.get(interval, '5')
                
                # Get time price series
                result = self.api.get_time_price_series(
                    exchange='NSE',
                    tradingsymbol=symbol,
                    starttime='',
                    endtime='',
                    interval=ft_interval,
                    candlecount=days * 78  # ~78 5-min candles per day
                )
                
                if result and result.get('stat') == 'Ok':
                    df = pd.DataFrame(result.get('values', []))
                    if not df.empty:
                        df['time'] = pd.to_datetime(df['time'], format='%d-%m-%Y %H:%M:%S')
                        df.set_index('time', inplace=True)
                        df = df.rename(columns={
                            'open': 'Open',
                            'high': 'High', 
                            'low': 'Low',
                            'close': 'Close',
                            'volume': 'Volume'
                        })
                        df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
                        return df.astype(float)
                return pd.DataFrame()
            else:
                return self._get_mock_historical(symbol, interval, days)
                
        except Exception as e:
            logger.error(f"Get historical failed: {e}")
            return pd.DataFrame()
    
    def subscribe_live(self, symbols: List[str], 
                       callback: Callable[[str, Dict], None] = None):
        """
        Subscribe to live market feed via WebSocket
        
        Args:
            symbols: List of symbols to subscribe
            callback: Function to call on price update
        """
        self.on_price_update = callback
        
        # Store subscriptions
        self.ws_subscriptions.update(symbols)
        
        # Start WebSocket if not running
        if self.ws_thread is None or not self.ws_thread.is_alive():
            self._start_websocket()
    
    def _start_websocket(self):
        """Start WebSocket connection for live data"""
        # For demo purposes, simulate live updates
        # In production, use actual WebSocket endpoint
        
        def ws_simulator():
            while self.ws_subscriptions:
                for symbol in list(self.ws_subscriptions):
                    if symbol in self.live_quotes:
                        # Simulate price movement
                        base_price = self.live_quotes[symbol].get('last', 1000)
                        change = base_price * 0.0001  # 0.01% change
                        new_price = base_price + (hash(str(time.time())) % 100 - 50) * change
                        
                        self.live_quotes[symbol] = {
                            'last': new_price,
                            'volume': self.live_quotes[symbol].get('volume', 0) + 100
                        }
                        
                        if self.on_price_update:
                            self.on_price_update(symbol, self.live_quotes[symbol])
                
                time.sleep(1)  # Update every second
        
        self.ws_thread = threading.Thread(target=ws_simulator, daemon=True)
        self.ws_thread.start()
        logger.info("Live feed simulator started")
    
    def unsubscribe(self, symbols: List[str]):
        """Unsubscribe from live feed"""
        for symbol in symbols:
            self.ws_subscriptions.discard(symbol)
    
    def get_live_price(self, symbol: str) -> Optional[float]:
        """Get current LTP for a symbol"""
        if symbol in self.live_quotes:
            return self.live_quotes[symbol].get('last')
        return None
    
    def build_candles(self, symbol: str, timeframe: str = '5min',
                      force_update: bool = False) -> pd.DataFrame:
        """
        Build OHLC candles from live data
        
        Args:
            symbol: Trading symbol
            timeframe: 5min, 15min, 30min, 60min
            force_update: Force rebuild from historical
            
        Returns:
            DataFrame with OHLC candles
        """
        key = f"{symbol}_{timeframe}"
        
        if not force_update and key in self.candle_data:
            return self.candle_data[key]
        
        # Get historical data and build candles
        interval_map = {
            '5min': '5min',
            '15min': '15min', 
            '30min': '15min',
            '60min': '60min'
        }
        
        hist = self.get_historical_data(symbol, interval_map.get(timeframe, '5min'))
        
        if not hist.empty:
            self.candle_data[key] = hist
            return hist
        
        return pd.DataFrame()
    
    def disconnect(self):
        """Disconnect from API"""
        self.connected = False
        if self.ws:
            self.ws.close()
        logger.info("Disconnected from Flatrade API")
    
    # Mock methods for testing without API
    def _get_mock_quote(self, symbol: str) -> Dict:
        """Generate mock quote data"""
        import random
        base_prices = {
            'SBIN': 1020,
            'RELIANCE': 2950,
            'INFY': 1850,
            'TCS': 4200,
            'HDFCBANK': 1680,
            '^NSEI': 22700,
            '^NSEBANK': 52000
        }
        base = base_prices.get(symbol, 1000)
        return {
            'tradingsymbol': symbol,
            'last': base + random.uniform(-10, 10),
            'open': base - 5,
            'high': base + 15,
            'low': base - 15,
            'close': base,
            'volume': random.randint(100000, 1000000),
            'value': random.randint(10000000, 100000000)
        }
    
    def _get_mock_historical(self, symbol: str, interval: str, days: int) -> pd.DataFrame:
        """Generate mock historical data"""
        import random
        base_prices = {
            'SBIN': 1020,
            'RELIANCE': 2950,
            'INFY': 1850,
            'TCS': 4200,
            'HDFCBANK': 1680,
            '^NSEI': 22700,
            '^NSEBANK': 52000
        }
        
        base = base_prices.get(symbol, 1000)
        
        # Determine number of candles
        interval_minutes = {'1min': 1, '5min': 5, '15min': 15, '60min': 60}
        mins = interval_minutes.get(interval, 5)
        candles_per_day = 78  # Market hours 6.5 hours * 12 (5min intervals)
        
        n_candles = min(days * candles_per_day, 500)
        
        # Generate dates
        end_time = datetime.now()
        start_time = end_time - timedelta(minutes=mins * n_candles)
        
        dates = pd.date_range(start=start_time, end=end_time, periods=n_candles)
        
        # Generate OHLC
        data = []
        price = base
        
        for dt in dates:
            if random.random() > 0.3:  # 70% chance of upward movement
                change = random.uniform(-0.02, 0.03)
            else:
                change = random.uniform(-0.03, 0.02)
            
            price *= (1 + change)
            open_price = price * (1 + random.uniform(-0.005, 0.005))
            high = max(price, open_price) * (1 + random.uniform(0, 0.01))
            low = min(price, open_price) * (1 - random.uniform(0, 0.01))
            close = price
            
            data.append({
                'Open': open_price,
                'High': high,
                'Low': low,
                'Close': close,
                'Volume': random.randint(100000, 500000)
            })
        
        df = pd.DataFrame(data, index=dates)
        return df


# Default connector instance
connector = None


def init_flatrade(api_key: str = None, api_secret: str = None,
                  user_id: str = None, token: str = None) -> FlatradeConnector:
    """Initialize and return Flatrade connector"""
    global connector
    connector = FlatradeConnector(api_key, api_secret, user_id, token)
    connector.connect()
    return connector


def get_connector() -> FlatradeConnector:
    """Get existing connector or create new one"""
    global connector
    if connector is None:
        connector = FlatradeConnector()
        connector.connect()
    return connector


if __name__ == "__main__":
    # Test the connector
    conn = init_flatrade()
    
    # Test search
    results = conn.search_symbol("SBIN")
    print(f"Search results: {len(results)}")
    
    # Test quote
    quote = conn.get_quote("SBIN")
    print(f"Quote: {quote}")
    
    # Test historical
    hist = conn.get_historical_data("SBIN", "5min", 1)
    print(f"Historical data: {len(hist)} candles")
    print(hist.tail())