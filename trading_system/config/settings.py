"""
Trading System Configuration
"""
import os
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / "config"
LOG_DIR = BASE_DIR / "logs"
DATA_DIR = BASE_DIR / "data"

# Ensure directories exist
LOG_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# Market timings (IST)
MARKET_START_HOUR = 9
MARKET_START_MINUTE = 15
MARKET_END_HOUR = 15
MARKET_END_MINUTE = 30

# Trading settings
MAX_POSITIONS = 3
DEFAULT_CAPITAL_PER_TRADE = 10000  # ₹10,000 per trade
STOP_LOSS_PERCENT = 2.0  # 2% stop loss
TARGET_PROFIT_PERCENT = 4.0  # 4% target

# Trading intervals
DATA_REFRESH_INTERVAL = 60  # seconds
CHECK_INTERVAL = 5  # seconds between strategy checks

# Symbols to trade (NSE stocks)
SYMBOLS = ["RELIANCE", "INFY", "TCS", "HDFCBANK", "ICICIBANK"]

# Data provider
DATA_PROVIDER = "yfinance"  # yfinance, websocket, or custom

# Broker settings (to be configured by user)
BROKER_API_KEY = os.getenv("BROKER_API_KEY", "")
BROKER_API_SECRET = os.getenv("BROKER_API_SECRET", "")
BROKER_NAME = os.getenv("BROKER_NAME", "demo")  # zerodha, angelone, upstox, demo

# Telegram notifications (optional)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Logging
LOG_LEVEL = "INFO"
LOG_FILE = LOG_DIR / "trading.log"

# Database (optional)
USE_DATABASE = False
DB_PATH = DATA_DIR / "trades.db"