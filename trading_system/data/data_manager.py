"""
Data Manager - Unified data interface for trading system
Can use Flatrade API or Yahoo Finance as data source
"""

import logging
import pandas as pd
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)

# Data source configuration
USE_FLATTRADE = True  # Set to False to use Yahoo Finance
DATA_SOURCE = 'flattrade' if USE_FLATTRADE else 'yahoo'


def get_price_data(symbol: str, interval: str = '5min', days: int = 30) -> pd.DataFrame:
    """
    Get OHLC price data for a symbol
    
    Args:
        symbol: Trading symbol (e.g., 'SBIN', '^NSEI')
        interval: Timeframe (1min, 5min, 15min, 30min, 60min, 1day)
        days: Number of days of historical data
        
    Returns:
        DataFrame with columns: Open, High, Low, Close, Volume
    """
    if DATA_SOURCE == 'flattrade':
        return _get_flattrade_data(symbol, interval, days)
    else:
        return _get_yahoo_data(symbol, interval, days)


def _get_flattrade_data(symbol: str, interval: str, days: int) -> pd.DataFrame:
    """Get data from Flatrade API"""
    try:
        from data.flattrade_connector import get_connector
        conn = get_connector()
        
        # Convert interval format
        interval_map = {
            '1min': '1min',
            '5min': '5min',
            '15min': '15min',
            '30min': '15min',
            '60min': '60min',
            '1day': '1day'
        }
        
        ft_interval = interval_map.get(interval, '5min')
        
        # Handle index symbols
        if symbol.startswith('^'):
            # For indices, need special handling
            # Map ^NSEI to NIFTY, ^NSEBANK to BANKNIFTY
            symbol_map = {
                '^NSEI': 'NIFTY',
                '^NSEBANK': 'BANKNIFTY'
            }
            ft_symbol = symbol_map.get(symbol, symbol.replace('^', ''))
        else:
            ft_symbol = symbol
        
        return conn.get_historical_data(ft_symbol, ft_interval, days)
        
    except Exception as e:
        logger.error(f"Flattrade data fetch error: {e}")
        # Fallback to Yahoo
        return _get_yahoo_data(symbol, interval, days)


def _get_yahoo_data(symbol: str, interval: str, days: int) -> pd.DataFrame:
    """Get data from Yahoo Finance"""
    try:
        import yfinance as yf
        
        # Handle symbol format
        if symbol.startswith('^'):
            yf_symbol = symbol  # Indices don't need .NS
        else:
            yf_symbol = f"{symbol}.NS"
        
        # Convert interval format
        interval_map = {
            '1min': '1m',
            '5min': '5m',
            '15m': '15m',
            '30min': '30m',
            '60min': '60m',
            '1day': '1d'
        }
        
        yf_interval = interval_map.get(interval, '5m')
        
        # Calculate period
        if days <= 1:
            period = f"{days + 5}d"  # Need at least a few days
        elif days <= 30:
            period = f"{days}d"
        else:
            period = f"{min(days, 730)}d"
        
        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(period=period, interval=yf_interval)
        
        if df is None or df.empty:
            return pd.DataFrame()
            
        # Clean up columns
        df = df.rename(columns={
            'Open': 'Open',
            'High': 'High',
            'Low': 'Low',
            'Close': 'Close',
            'Volume': 'Volume'
        })
        
        return df[['Open', 'High', 'Low', 'Close', 'Volume']]
        
    except Exception as e:
        logger.error(f"Yahoo data fetch error: {e}")
        return pd.DataFrame()


def get_live_quote(symbol: str) -> Optional[Dict]:
    """Get current price quote"""
    if DATA_SOURCE == 'flattrade':
        try:
            from data.flattrade_connector import get_connector
            conn = get_connector()
            return conn.get_quote(symbol)
        except:
            pass
    
    # Fallback to Yahoo
    try:
        import yfinance as yf
        if symbol.startswith('^'):
            ticker = yf.Ticker(symbol)
        else:
            ticker = yf.Ticker(f"{symbol}.NS")
        
        info = ticker.fast_info
        return {
            'last': info.last_price,
            'volume': info.last_volume,
            'open': info.open,
            'high': info.day_high,
            'low': info.day_low
        }
    except:
        return None


def get_available_symbols() -> List[str]:
    """Get list of available symbols for monitoring"""
    return [
        'SBIN', 'RELIANCE', 'INFY', 'TCS', 'HDFCBANK',
        'HINDUNILVR', 'KOTAKBANK', 'ICICIBANK', 'BAJFINANCE',
        '^NSEI', '^NSEBANK'
    ]


def search_symbol(query: str) -> List[Dict]:
    """Search for symbols"""
    if DATA_SOURCE == 'flattrade':
        try:
            from data.flattrade_connector import get_connector
            conn = get_connector()
            return conn.search_symbol(query)
        except:
            pass
    
    # Simple search for Yahoo
    return [{'symbol': query, 'name': query}]


# Singleton instance
_data_manager = None


class DataManager:
    """
    Centralized data management for the trading system
    Handles data fetching, caching, and preprocessing
    """
    
    def __init__(self):
        self.cache = {}
        self.cache_duration = 60  # seconds
    
    def get_candle_data(self, symbol: str, timeframe: str = '5min') -> pd.DataFrame:
        """
        Get candle data with caching
        
        Args:
            symbol: Trading symbol
            timeframe: 5min, 15min, 30min, 60min
            
        Returns:
            DataFrame with OHLCV data
        """
        import time
        import hashlib
        
        # Create cache key
        cache_key = f"{symbol}_{timeframe}"
        
        # Check cache
        if cache_key in self.cache:
            cached_time, cached_data = self.cache[cache_key]
            if time.time() - cached_time < self.cache_duration:
                return cached_data
        
        # Fetch fresh data
        interval_map = {
            '5min': '5min',
            '15min': '15min',
            '30min': '30min',
            '60min': '60min'
        }
        
        data = get_price_data(symbol, interval_map.get(timeframe, '5min'), 30)
        
        # Update cache
        self.cache[cache_key] = (time.time(), data)
        
        return data
    
    def refresh_cache(self, symbol: str = None):
        """Refresh data cache"""
        if symbol:
            # Clear specific symbol cache
            keys_to_clear = [k for k in self.cache if k.startswith(symbol)]
            for key in keys_to_clear:
                del self.cache[key]
        else:
            # Clear all cache
            self.cache.clear()


# Initialize data manager
data_manager = DataManager()


if __name__ == "__main__":
    print(f"Using data source: {DATA_SOURCE}")
    
    # Test data fetch
    df = get_price_data('SBIN', '5min', 5)
    print(f"Got {len(df)} candles for SBIN")
    print(df.tail())
    
    # Test data manager
    dm = DataManager()
    df2 = dm.get_candle_data('^NSEI', '15min')
    print(f"Got {len(df2)} candles for NIFTY")