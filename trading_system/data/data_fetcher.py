"""
Data fetcher module - gets real-time market data
"""
import yfinance as yf
import pandas as pd
import logging
from typing import Optional, Dict
from datetime import datetime, time

logger = logging.getLogger(__name__)


class DataFetcher:
    """Fetch real-time and historical market data"""
    
    def __init__(self, symbols: list):
        self.symbols = [s.upper() for s in symbols]
        self.cache = {}
        self.cache_time = {}
        self.cache_duration = 30  # seconds
    
    def get_live_price(self, symbol: str) -> Optional[float]:
        """Get live price for a symbol"""
        try:
            ticker = yf.Ticker(f"{symbol.upper()}.NS")
            data = ticker.fast_info
            return float(data.last_price) if data.last_price else None
        except Exception as e:
            logger.warning(f"Failed to get live price for {symbol}: {e}")
            return None
    
    def get_historical_data(self, symbol: str, period: str = "5d", 
                          interval: str = "5m") -> Optional[pd.DataFrame]:
        """Get historical data for backtesting"""
        try:
            ticker = yf.Ticker(f"{symbol.upper()}.NS")
            df = ticker.history(period=period, interval=interval)
            if df.empty:
                logger.warning(f"No historical data for {symbol}")
                return None
            return df
        except Exception as e:
            logger.error(f"Failed to get historical data for {symbol}: {e}")
            return None
    
    def get_live_candle(self, symbol: str, interval: str = "5m") -> Optional[pd.DataFrame]:
        """Get latest candle data"""
        try:
            ticker = yf.Ticker(f"{symbol.upper()}.NS")
            df = ticker.history(period="1d", interval=interval)
            if df.empty:
                return None
            return df.tail(1)
        except Exception as e:
            logger.error(f"Failed to get live candle for {symbol}: {e}")
            return None
    
    def get_multiple_prices(self) -> Dict[str, float]:
        """Get live prices for all symbols"""
        prices = {}
        for symbol in self.symbols:
            price = self.get_live_price(symbol)
            if price:
                prices[symbol] = price
        return prices
    
    def is_market_open(self) -> bool:
        """Check if NSE market is currently open (9:15 - 15:30 IST)"""
        now = datetime.now()
        
        # IST timezone (UTC+5:30)
        ist_hour = now.hour + 5
        ist_minute = now.minute + 30
        if ist_minute >= 60:
            ist_hour += 1
            ist_minute -= 60
        
        current_ist_time = time(ist_hour % 24, ist_minute)
        market_start = time(9, 15)
        market_end = time(15, 30)
        
        # Check if weekday (Monday=0, Sunday=6)
        is_weekday = now.weekday() < 5
        
        return is_weekday and market_start <= current_ist_time <= market_end
    
    def wait_for_market_open(self):
        """Wait until market opens"""
        import time
        while not self.is_market_open():
            logger.info("Market closed. Waiting...")
            time.sleep(60)  # Check every minute
    
    def wait_for_market_close(self):
        """Wait until market closes"""
        import time
        while self.is_market_open():
            time.sleep(60)  # Check every minute


if __name__ == "__main__":
    # Test
    fetcher = DataFetcher(["RELIANCE", "INFY"])
    print(f"Market open: {fetcher.is_market_open()}")
    print(f"Price: {fetcher.get_live_price('RELIANCE')}")