"""
Telegram Bot - Send symbol and get backtest results
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Your bot token
BOT_TOKEN = "8637593160:AAG7VCBAFC5icaxAcvFf1h9QnE6LyMCe0PE"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import the backtest function
from strategies.sqz_momentum import calculate_sqzmom
import yfinance as yf


def run_backtest(symbol: str, timeframe: str = "15m", num_alerts: int = 10) -> str:
    """Run backtest and return formatted results"""
    interval_map = {'5m': '5m', '15m': '15m', '30m': '30m', '60m': '60m'}
    yf_interval = interval_map.get(timeframe, '15m')
    
    try:
        ticker = yf.Ticker(f'{symbol.upper()}.NS')
        price_df = ticker.history(period='1mo', interval=yf_interval)
        
        if price_df is None or len(price_df) < 50:
            return f"❌ Insufficient data for {symbol}"
        
        sqz_df = calculate_sqzmom(price_df)
        
        alerts = []
        for i in range(20, len(sqz_df)):
            curr = sqz_df.iloc[i]
            prev = sqz_df.iloc[i-1]
            
            close_near_high = curr['close_position'] >= 0.90
            momentum_decreasing = curr['momentum'] < prev['momentum']
            
            if close_near_high and momentum_decreasing:
                entry_price = curr['close']
                future_idx = min(i + 3, len(price_df) - 1)
                future_price = price_df.iloc[future_idx]['Close']
                
                pnl_pct = ((future_price - entry_price) / entry_price) * 100
                stop_hit = entry_price * 0.99  # 1% SL
                target_hit = entry_price * 1.02  # 2% TP
                
                next_candles = price_df.iloc[i+1:min(i+4, len(price_df))]
                hit_target = any(next_candles['High'] >= target_hit)
                hit_stop = any(next_candles['Low'] <= stop_hit)
                
                if hit_target and not hit_stop:
                    outcome = '✅ TARGET'
                elif hit_stop and not hit_target:
                    outcome = '🛑 STOP'
                elif pnl_pct > 0:
                    outcome = f'📈 +{pnl_pct:.1f}%'
                elif pnl_pct < 0:
                    outcome = f'📉 {pnl_pct:.1f}%'
                else:
                    outcome = '⚪ BE'
                
                alerts.append({
                    'datetime': price_df.index[i],
                    'price': entry_price,
                    'squeeze': curr['squeeze'],
                    'outcome': outcome
                })
                
                if len(alerts) >= num_alerts:
                    break
        
        if not alerts:
            return f"No alerts found for {symbol} ({timeframe})"
        
        # Calculate overall return
        target_count = sum(1 for a in alerts if 'TARGET' in a['outcome'])
        stop_count = sum(1 for a in alerts if 'STOP' in a['outcome'])
        profit_count = sum(1 for a in alerts if '+' in a['outcome'])
        loss_count = sum(1 for a in alerts if '📉' in a['outcome'])
        be_count = sum(1 for a in alerts if 'BE' in a['outcome'])
        
        # Calculate PnL assuming 1 lot = 1000 rs per trade
        # Target: +2%, Stop: -1%, Profit/Loss: actual %
        total_pnl = 0
        for a in alerts:
            entry = a['price']
            if 'TARGET' in a['outcome']:
                total_pnl += 2.0  # +2%
            elif 'STOP' in a['outcome']:
                total_pnl -= 1.0  # -1%
            elif '+' in a['outcome']:
                pct = float(a['outcome'].replace('📈 +', '').replace('%', ''))
                total_pnl += pct
            elif '📉' in a['outcome']:
                pct = float(a['outcome'].replace('📉 ', '').replace('%', ''))
                total_pnl += pct
        
        win_rate = (target_count + profit_count) / len(alerts) * 100
        
        response = f"📊 *{symbol.upper()} - {timeframe} Backtest*\n"
        response += f"═══════════════════════════\n"
        response += f"Alerts: {len(alerts)} | Win Rate: {win_rate:.0f}%\n"
        response += f"✅ Target: {target_count} | 🛑 Stop: {stop_count} | 📈 Profit: {profit_count} | 📉 Loss: {loss_count}\n"
        response += f"─────────────────────────────────\n"
        response += f"💰 Overall Return: {total_pnl:+.1f}%\n"
        response += f"   (If 10 trades with ₹10k each = ₹{total_pnl*1000:+,})\n"
        response += f"═══════════════════════════\n"
        
        for j, a in enumerate(alerts, 1):
            response += f"{j}. {a['datetime'].strftime('%m/%d %H:%M')} | ₹{a['price']:.0f} | {a['squeeze']} | {a['outcome']}\n"
        
        return response
        
    except Exception as e:
        return f"❌ Error: {str(e)}"


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    await update.message.reply_text(
        "🚀 *Trading System Bot*\n\n"
        "Send me a symbol to get backtest results!\n\n"
        "Examples:\n"
        "• SBIN\n"
        "• RELIANCE 15m\n"
        "• INFY 30m 5\n\n"
        "Format: SYMBOL [TIMEFRAME] [NUM_ALERTS]\n"
        "Timeframes: 5m, 15m, 30m, 60m\n"
        "Default: 15m timeframe, 10 alerts",
        parse_mode='Markdown'
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    await start_command(update, context)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages"""
    try:
        text = update.message.text.strip().upper()
        
        # Parse input
        parts = text.split()
        symbol = parts[0]
        timeframe = parts[1] if len(parts) > 1 else "15m"
        num_alerts = int(parts[2]) if len(parts) > 2 else 10
        
        # Validate timeframe
        if timeframe not in ["5m", "15m", "30m", "60m"]:
            await update.message.reply_text(f"Invalid timeframe: {timeframe}. Use: 5m, 15m, 30m, or 60m")
            return
        
        # Show processing
        await update.message.reply_text(f"⏳ Running backtest for {symbol} ({timeframe})...")
        
        # Run backtest
        result = run_backtest(symbol, timeframe, num_alerts)
        
        await update.message.reply_text(result, parse_mode='Markdown')
        
    except ValueError:
        await update.message.reply_text("Invalid number format. Use: SYMBOL [TIMEFRAME] [NUM_ALERTS]")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")


def main():
    """Start the bot"""
    logger.info("Starting Telegram bot...")
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Bot is running...")
    app.run_polling(poll_interval=3)


if __name__ == "__main__":
    main()