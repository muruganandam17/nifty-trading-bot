"""
Scheduler to run alert checks when new candles form
"""
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Callable, Optional
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)


class CandleScheduler:
    """
    Scheduler that triggers callbacks when new candles form.
    Monitors multiple timeframes and detects new candles.
    """
    
    # Timeframe intervals in seconds
    TIMEFRAME_INTERVALS = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "60m": 3600,
        "120m": 7200,
        "240m": 14400,
        "1d": 86400
    }
    
    def __init__(self, check_interval: int = 30):
        """
        Args:
            check_interval: How often to check for new candles (seconds)
        """
        self.check_interval = check_interval
        self.running = False
        self.callbacks: Dict[str, List[Callable]] = {}  # timeframe -> list of callbacks
        self.last_candle_time: Dict[str, datetime] = {}  # timeframe -> last candle time
        self.thread: Optional[threading.Thread] = None
        self.symbols: List[str] = []
        
    def set_symbols(self, symbols: List[str]):
        """Set symbols to monitor"""
        self.symbols = symbols
        
    def register_callback(self, timeframe: str, callback: Callable):
        """Register a callback for a specific timeframe"""
        if timeframe not in self.callbacks:
            self.callbacks[timeframe] = []
        self.callbacks[timeframe].append(callback)
        logger.info(f"Registered callback for {timeframe}")
    
    def _get_current_candle_time(self, timeframe: str) -> datetime:
        """Get the current candle time for a timeframe"""
        now = datetime.now()
        interval = self.TIMEFRAME_INTERVALS.get(timeframe, 300)
        
        # Get seconds since midnight
        seconds_since_midnight = (now - now.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds()
        
        # Round down to interval
        current_candle_seconds = (seconds_since_midnight // interval) * interval
        
        # Create datetime for current candle
        hours = int(current_candle_seconds // 3600)
        minutes = int((current_candle_seconds % 3600) // 60)
        seconds = int(current_candle_seconds % 60)
        
        return now.replace(hour=hours, minute=minutes, second=seconds, microsecond=0)
    
    def _fetch_and_check(self, timeframe: str) -> List[Dict]:
        """Fetch latest data and check for alerts"""
        import yfinance as yf
        from strategies.sqz_momentum import check_alerts
        
        alerts = []
        
        for symbol in self.symbols:
            try:
                result = check_alerts(symbol, timeframe)
                if result["alert"]:
                    alerts.append(result)
            except Exception as e:
                logger.error(f"Error checking {symbol} {timeframe}: {e}")
        
        return alerts
    
    def _run_loop(self):
        """Main scheduler loop"""
        logger.info("Scheduler started")
        
        while self.running:
            try:
                now = datetime.now()
                
                # Check each registered timeframe
                for timeframe in self.callbacks.keys():
                    interval = self.TIMEFRAME_INTERVALS.get(timeframe, 300)
                    current_candle_time = self._get_current_candle_time(timeframe)
                    
                    # Initialize last candle time if not set
                    if timeframe not in self.last_candle_time:
                        self.last_candle_time[timeframe] = current_candle_time
                        continue
                    
                    # Check if new candle has formed
                    if current_candle_time > self.last_candle_time[timeframe]:
                        logger.info(f"New candle detected for {timeframe}")
                        
                        # Fetch and check alerts
                        alerts = self._fetch_and_check(timeframe)
                        
                        # Run callbacks with alerts
                        if timeframe in self.callbacks:
                            for callback in self.callbacks[timeframe]:
                                try:
                                    callback(timeframe, alerts)
                                except Exception as e:
                                    logger.error(f"Error in callback for {timeframe}: {e}")
                        
                        self.last_candle_time[timeframe] = current_candle_time
                
                # Wait before next check
                time.sleep(self.check_interval)
                
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                time.sleep(self.check_interval)
        
        logger.info("Scheduler stopped")
    
    def start(self):
        """Start the scheduler"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()
            logger.info("Scheduler started")
    
    def stop(self):
        """Stop the scheduler"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Scheduler stopped")


def run_alert_check(symbol: str, timeframe: str):
    """Run alert check for a symbol and timeframe"""
    from strategies.sqz_momentum import check_alerts
    
    result = check_alerts(symbol, timeframe)
    
    if result["alert"]:
        logger.warning(f"🚨 ALERT: {result['message']}")
        print(f"\n{'='*60}")
        print(f"🚨 ALERT TRIGGERED!")
        print(f"{result['message']}")
        print(f"{'='*60}\n")
    else:
        logger.debug(f"{timeframe}: {result['message']}")


def run_full_scan(symbol: str, timeframes: List[str] = None):
    """Run alert check on all timeframes"""
    if timeframes is None:
        timeframes = ["5m", "15m", "30m", "60m", "120m", "240m", "1d"]
    
    # Import here to avoid circular import
    from strategies.sqz_momentum import check_alerts
    
    print(f"\n{'='*60}")
    print(f"🔍 Scanning {symbol} - {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}")
    
    alerts_found = []
    
    for tf in timeframes:
        result = check_alerts(symbol, tf)
        
        if result["alert"]:
            alerts_found.append(result["message"])
            print(f"🚨 {tf}: ALERT!")
            print(f"   {result['message']}")
        else:
            print(f"  {tf}: OK")
    
    if alerts_found:
        print(f"\n⚠️ {len(alerts_found)} ALERTS FOUND!")
    else:
        print(f"\n✅ No alerts")
    
    print(f"{'='*60}\n")
    
    return alerts_found


# Example usage
if __name__ == "__main__":
    import sys
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s'
    )
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python scheduler.py <SYMBOL>           # Run once")
        print("  python scheduler.py <SYMBOL> --watch   # Watch continuously")
        sys.exit(1)
    
    symbol = sys.argv[1]
    watch_mode = "--watch" in sys.argv
    
    # Callback function for alerts
    def on_alert(timeframe: str, alerts: List[Dict]):
        """Callback when new candle forms and alerts are detected"""
        if alerts:
            print(f"\n🚨 {'='*60}")
            print(f"🚨 ALERTS on {timeframe} at {datetime.now().strftime('%H:%M:%S')}")
            print(f"🚨 {'='*60}")
            for alert in alerts:
                print(f"  {alert['message']}")
            print(f"🚨 {'='*60}\n")
    
    if watch_mode:
        # Continuous monitoring with callback
        scheduler = CandleScheduler(check_interval=30)
        scheduler.set_symbols([symbol])
        
        # Register callbacks for timeframes
        for tf in ["5m", "15m", "30m", "60m"]:
            scheduler.register_callback(tf, on_alert)
        
        scheduler.start()
        
        print(f"Watching {symbol} for new candles...")
        print(f"Timeframes: 5m, 15m, 30m, 60m")
        print(f"Press Ctrl+C to stop")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping...")
            scheduler.stop()
    else:
        # Single scan
        run_full_scan(symbol)