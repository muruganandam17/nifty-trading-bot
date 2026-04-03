# Trading System

A real-time trading system using the **Squeeze Momentum (SQZMOM)** indicator for the Indian stock market (NSE).

> 📡 **Live on VPS:** The bot is currently running on `175.29.21.65` with Telegram alerts!

## 📁 Project Structure

```text
trading_system/
├── main.py                 # Main entry point
├── trading_engine.py       # Core trading logic
├── nifty_monitor_bot.py    # Telegram bot with alerts
├── config/
│   └── settings.py         # Configuration settings
├── strategies/
│   └── sqz_momentum.py    # SQZMOM indicator
├── data/
│   └── data_fetcher.py    # Market data fetching
├── brokers/
│   └── broker.py          # Broker integration
├── logs/                  # Log files
├── requirements.txt       # Python dependencies
└── DEPLOY.md              # Server deployment guide
```

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Settings

Edit `config/settings.py`:
- Set symbols to trade
- Set market hours (default 9:15 - 15:30 IST)
- Configure broker (demo for now)

### 3. Run Locally

```python
python main.py
```

Or run the Telegram bot:

```python
python nifty_monitor_bot.py
```

## ⚙️ Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `SYMBOLS` | `["RELIANCE","INFY","TCS","HDFCBANK","ICICIBANK"]` | Stocks to trade |
| `MARKET_START` | `9:15` | Market open time (IST) |
| `MARKET_END` | `15:30` | Market close time (IST) |
| `MAX_POSITIONS` | `3` | Maximum concurrent positions |
| `STOP_LOSS` | `2%` | Stop loss percentage |
| `TARGET` | `4%` | Target profit percentage |

## 📊 Strategy

### Entry Conditions

1. **Momentum turns positive** - Momentum crosses from negative to positive
2. **Squeeze release** - Squeeze OFF with positive momentum
3. **Strong momentum** - Momentum increasing >5%

### Exit Conditions

1. Stop loss hit (2%)
2. Target reached (4%)
3. Momentum reversal
4. Squeeze ON (consolidation)

## 📡 Telegram Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Start the bot |
| `/status` | Check bot & market status |
| `/alerts` | View current squeeze/PSAR alerts |
| `/tokenurl` | Get OAuth login URL |
| `/settoken <code>` | Update FlatTrade token |

## 🔧 Deployment to VPS

See [DEPLOY.md](DEPLOY.md) for detailed server deployment instructions.

## 📝 License

MIT