"""
Main entry point for the trading system
"""
import logging
import sys
import signal
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from trading_system.config.settings import (
    LOG_LEVEL, LOG_FILE, SYMBOLS, 
    MARKET_START_HOUR, MARKET_START_MINUTE,
    MARKET_END_HOUR, MARKET_END_MINUTE
)
from trading_system.data.data_fetcher import DataFetcher
from trading_system.trading_engine import TradingEngine


def setup_logging():
    """Configure logging"""
    # Create logs directory
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL),
        format='%(asctime)s | %(levelname)s | %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler()
        ]
    )


def is_market_hours() -> bool:
    """Check if current time is within market hours (9:15 - 15:30 IST)"""
    from datetime import datetime, time
    
    now = datetime.now()
    
    # Convert to IST (UTC+5:30)
    ist_hour = now.hour + 5
    ist_minute = now.minute + 30
    if ist_minute >= 60:
        ist_hour += 1
        ist_minute -= 60
    ist_hour = ist_hour % 24
    
    current_ist = time(ist_hour, ist_minute)
    market_start = time(MARKET_START_HOUR, MARKET_START_MINUTE)
    market_end = time(MARKET_END_HOUR, MARKET_END_MINUTE)
    
    # Check weekday (Mon=0, Fri=4, Sat=5, Sun=6)
    is_weekday = now.weekday() < 5
    
    return is_weekday and market_start <= current_ist <= market_end


def get_next_market_start() -> str:
    """Get next market open time"""
    from datetime import datetime, timedelta
    
    now = datetime.now()
    
    # Calculate IST time
    ist_hour = now.hour + 5
    ist_minute = now.minute + 30
    if ist_minute >= 60:
        ist_hour += 1
        ist_minute -= 60
    ist_hour = ist_hour % 24
    
    current_ist = time(ist_hour, ist_minute)
    market_start = time(MARKET_START_HOUR, MARKET_START_MINUTE)
    
    if now.weekday() >= 5:  # Weekend
        days_to_wait = 7 - now.weekday()  # Wait until Monday
        next_start = now + timedelta(days=days_to_wait)
    elif current_ist < market_start:
        # Today, hasn't opened yet
        next_start = now
    else:
        # Already passed, next day
        next_start = now + timedelta(days=1)
    
    # Set to market start time
    from datetime import datetime as dt
    next_market = dt(
        next_start.year, next_start.month, next_start.day,
        MARKET_START_HOUR, MARKET_START_MINUTE, 0
    )
    
    # Subtract 5:30 to convert to UTC
    next_market_utc = next_market - timedelta(hours=5, minutes=30)
    
    return next_market_utc.strftime("%Y-%m-%d %H:%M:%S UTC")


def run_trading():
    """Run the trading system"""
    logger = logging.getLogger(__name__)
    
    # Initialize components
    logger.info("Initializing trading system...")
    
    data_fetcher = DataFetcher(SYMBOLS)
    engine = TradingEngine(data_fetcher)
    
    # Setup signal handlers for graceful shutdown
    def signal_handler(sig, frame):
        logger.info("\nShutdown signal received...")
        engine.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("=" * 60)
    logger.info("TRADING SYSTEM STARTED")
    logger.info(f"Market Hours: {MARKET_START_HOUR:02d}:{MARKET_START_MINUTE:02d} - "
                f"{MARKET_END_HOUR:02d}:{MARKET_END_MINUTE:02d} IST")
    logger.info(f"Symbols: {', '.join(SYMBOLS)}")
    logger.info("=" * 60)
    
    while True:
        try:
            if is_market_hours():
                logger.info("🟢 Market OPEN - Starting trading engine...")
                engine.run()
            else:
                logger.info(f"🔴 Market CLOSED - Waiting for market open...")
                logger.info(f"Next market open: {get_next_market_start()}")
                
                # Wait 60 seconds before checking again
                import time
                time.sleep(60)
                
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            import time
            time.sleep(60)


if __name__ == "__main__":
    setup_logging()
    run_trading()