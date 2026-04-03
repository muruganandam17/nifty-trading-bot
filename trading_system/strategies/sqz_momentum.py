"""
Squeeze Momentum Indicator (SQZMOM) - Python Implementation
Based on Pine Script by LazyBear
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
import requests
import time

# Custom Yahoo Finance fetcher
_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

def get_yahoo_data(symbol, period='5d', interval='5m', max_retries=3):
    """Fetch data from Yahoo Finance using direct API"""
    interval_map = {'1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m', '60m': '60m', '1h': '1h', '4h': '4h', '1d': '1d'}
    interval = interval_map.get(interval, interval)
    
    period_map = {'1d': '1d', '5d': '5d', '10d': '10d', '1mo': '1mo', '3mo': '3mo', '6mo': '6mo', '1y': '1y', '5y': '5y', 'max': 'max'}
    period = period_map.get(period, period)
    
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={period}&interval={interval}'
    headers = {'User-Agent': _USER_AGENT}
    
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 429:
                time.sleep((attempt + 1) * 5)
                continue
            if resp.status_code != 200:
                time.sleep(2)
                continue
            data = resp.json()
            if 'chart' not in data or 'result' not in data['chart'] or data['chart']['result'] is None:
                continue
            result = data['chart']['result'][0]
            if 'timestamp' not in result:
                continue
            timestamps = result['timestamp']
            quote = result.get('indicators', {}).get('quote', [{}])[0]
            if not timestamps:
                return pd.DataFrame()
            df = pd.DataFrame({
                'Open': quote.get('open', []),
                'High': quote.get('high', []),
                'Low': quote.get('low', []),
                'Close': quote.get('close', []),
                'Volume': quote.get('volume', [])
            }, index=pd.to_datetime(timestamps, unit='s'))
            return df.dropna()
        except:
            time.sleep(2)
    return pd.DataFrame()


def linreg(series: pd.Series, length: int) -> float:
    """
    Linear Regression - returns value at x=length-1
    """
    if len(series) < length:
        return np.nan
    
    y = series.iloc[-length:].values
    
    n = length
    sumX = np.sum(np.arange(n))
    sumY = np.sum(y)
    sumXY = np.sum(np.arange(n) * y)
    sumXX = np.sum(np.arange(n) ** 2)
    
    denom = n * sumXX - sumX * sumX
    if denom == 0:
        return 0
    
    slope = (n * sumXY - sumX * sumY) / denom
    intercept = (sumY - slope * sumX) / n
    
    return intercept + slope * (n - 1)


def calculate_sqzmom(df: pd.DataFrame, length: int = 20, lengthKC: int = 20) -> pd.DataFrame:
    """
    Calculate Squeeze Momentum for entire dataframe.
    Returns dataframe with momentum values for each candle.
    """
    if df is None or len(df) < lengthKC + 5:
        return pd.DataFrame()
    
    close = df['Close']
    high = df['High']
    low = df['Low']
    open_price = df['Open']
    
    # Bollinger Bands
    basis = close.rolling(window=length).mean()
    dev = 2 * close.rolling(window=length).std()
    bb_upper = basis + dev
    bb_lower = basis - dev
    
    # Keltner Channels
    ma = close.rolling(window=lengthKC).mean()
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    rangema = tr.rolling(window=lengthKC).mean()
    kc_upper = ma + 1.5 * rangema
    kc_lower = ma - 1.5 * rangema
    
    # Midpoint
    highest_high = high.rolling(window=lengthKC).max()
    lowest_low = low.rolling(window=lengthKC).min()
    sma_close = close.rolling(window=lengthKC).mean()
    avg_hl = (highest_high + lowest_low) / 2
    midpoint = (avg_hl + sma_close) / 2
    
    source_minus_mid = close - midpoint
    
    # Calculate momentum for each candle
    momentum = pd.Series(index=df.index, dtype=float)
    
    for i in range(lengthKC, len(df)):
        y = source_minus_mid.iloc[i - lengthKC + 1:i + 1].values
        n = lengthKC
        sumX = np.sum(np.arange(n))
        sumY = np.sum(y)
        sumXY = np.sum(np.arange(n) * y)
        sumXX = np.sum(np.arange(n) ** 2)
        denom = n * sumXX - sumX * sumX
        if denom == 0:
            continue
        slope = (n * sumXY - sumX * sumY) / denom
        intercept = (sumY - slope * sumX) / n
        momentum.iloc[i] = intercept + slope * (n - 1)
    
    # Squeeze state
    squeeze_on = (bb_lower > kc_lower) & (bb_upper < kc_upper)
    squeeze_off = (bb_lower < kc_lower) & (bb_upper > kc_upper)
    
    # Close position relative to high (close near high indicator)
    # Calculate where close is relative to high-low range
    range_size = high - low
    close_position = np.where(range_size > 0, (close - low) / range_size, 0.5)  # 0 = low, 1 = high
    
    result = pd.DataFrame({
        'open': open_price,
        'close': close,
        'high': high,
        'low': low,
        'momentum': momentum,
        'squeeze': np.where(squeeze_on, 'ON', np.where(squeeze_off, 'OFF', 'NONE')),
        'close_position': close_position  # 0-1, where 1 = closed at high
    })
    
    return result.dropna()


def calculate_psar(df: pd.DataFrame, af_start: float = 0.02, af_increment: float = 0.02, af_max: float = 0.2) -> tuple:
    """
    Calculate Parabolic SAR - matches TradingView ta.sar(start, increment, maximum)
    
    Parameters:
    - af_start: Initial acceleration factor (default 0.02)
    - af_increment: Acceleration increment (default 0.02)
    - af_max: Maximum acceleration factor (default 0.2)
    
    Returns: (psar_series, trend_series) tuple
    """
    high = df['High'].values
    low = df['Low'].values
    close = df['Close'].values
    n = len(close)
    
    psar = np.zeros(n)
    trend = np.zeros(n)  # 1 for uptrend, -1 for downtrend
    
    # Initialize
    psar[0] = low[0]
    trend[0] = 1
    
    ep = high[0]  # Extreme point
    af_val = af_start
    
    for i in range(1, n):
        if trend[i-1] == 1:  # Uptrend
            psar[i] = psar[i-1] + af_val * (ep - psar[i-1])
            
            # Check for reversal
            if low[i] < psar[i]:
                trend[i] = -1
                psar[i] = ep
                ep = low[i]
                af_val = af_start
            else:
                trend[i] = 1
                if high[i] > ep:
                    ep = high[i]
                    af_val = min(af_val + af_increment, af_max)
        else:  # Downtrend
            psar[i] = psar[i-1] + af_val * (ep - psar[i-1])
            
            # Check for reversal
            if high[i] > psar[i]:
                trend[i] = 1
                psar[i] = ep
                ep = high[i]
                af_val = af_start
            else:
                trend[i] = -1
                if low[i] < ep:
                    ep = low[i]
                    af_val = min(af_val + af_increment, af_max)
    
    return pd.Series(psar, index=df.index), pd.Series(trend, index=df.index)


def check_all_timeframes(symbol: str) -> dict:
    """
    Check all timeframes for SQZMOM and return full status
    
    Returns:
        Dictionary with momentum, squeeze, direction for each TF
    """
    # Using custom Yahoo fetcher
    
    # Note: Yahoo supports 1h, 4h (not 2h, 3h)
    timeframes = ['1m', '5m', '15m', '30m', '60m', '1h', '4h']
    result = {
        'symbol': symbol,
        'timeframes': {},
        'timestamp': None
    }
    
    # Determine ticker
    if symbol.startswith('^'):
        ticker = symbol
    else:
        ticker = symbol
    
    for tf in timeframes:
        interval_map = {
            '1m': '1m', '5m': '5m', '15m': '15m',
            '30m': '30m', '60m': '60m', '1h': '1h', '4h': '4h'
        }
        
        try:
            # For longer timeframes, we need less data but longer period
            min_required = 10 if tf in ['1h', '4h'] else 25
            period = "60d" if tf == '4h' else ("5d" if tf in ['1m', '5m', '15m', '30m'] else "10d")
            
            try:
                df = get_yahoo_data(ticker, period=period, interval=tf)
            except Exception as e:
                result['timeframes'][tf] = {'error': f'Fetch error: {str(e)[:50]}'}
                continue
            
            if df is None or len(df) < min_required:
                result['timeframes'][tf] = {'error': 'Insufficient data'}
                continue
            
            # Validate dataframe has required columns
            required_cols = ['Open', 'High', 'Low', 'Close']
            if not all(col in df.columns for col in required_cols):
                result['timeframes'][tf] = {'error': 'Invalid data format'}
                continue
            
            sqz_df = calculate_sqzmom(df)
            psar, _ = calculate_psar(df)
            
            if sqz_df.empty or len(sqz_df) < 3:
                result['timeframes'][tf] = {'error': 'No SQZMOM data'}
                continue
            
            curr = sqz_df.iloc[-1]
            prev = sqz_df.iloc[-2]
            
            momentum = curr['momentum']
            prev_momentum = prev['momentum']
            
            # Direction
            if momentum > prev_momentum:
                direction = "increasing"
                arrow = "📈"
            elif momentum < prev_momentum:
                direction = "decreasing"
                arrow = "📉"
            else:
                direction = "flat"
                arrow = "➖"
            
            # Price info
            close_price = curr['close']
            psar_val = psar.iloc[-1]
            
            # Position
            close_pos = curr['close_position']
            if close_pos >= 0.90:
                near = "HIGH"
            elif close_pos <= 0.10:
                near = "LOW"
            else:
                near = "MID"
            
            result['timeframes'][tf] = {
                'momentum': round(momentum, 2),
                'prev_momentum': round(prev_momentum, 2),
                'direction': direction,
                'arrow': arrow,
                'squeeze': curr['squeeze'],
                'close': round(close_price, 2),
                'psar': round(psar_val, 2),
                'psar_position': 'above' if psar_val > close_price else 'below',
                'close_position': round(close_pos, 2),
                'near': near,
                'volume': int(df.iloc[-1]['Volume']) if 'Volume' in df.columns else 0
            }
            
            result['timestamp'] = str(df.index[-1])
            
        except Exception as e:
            result['timeframes'][tf] = {'error': str(e)}
    
    return result


def check_psar_crossover(symbol: str, timeframe: str = '5m') -> dict:
    """
    Check for Parabolic SAR crossover in a timeframe
    
    Returns:
        dict with crossover info: type (BUY/SELL), price, psar values, etc.
    """
    # Using custom Yahoo fetcher
    
    interval_map = {
        '1m': '1m', '5m': '5m', '15m': '15m',
        '30m': '30m', '60m': '60m'
    }
    
    # Determine ticker
    if symbol.startswith('^'):
        ticker = symbol
    else:
        ticker = symbol
    
    period = "5d" if timeframe in ['1m', '5m', '15m'] else "10d"
    try:
        df = ticker.history(period=period, interval=interval_map.get(timeframe, '5m'))
    except Exception as e:
        result['error'] = f'Fetch error: {str(e)[:50]}'
        return result
    
    result = {
        'symbol': symbol,
        'timeframe': timeframe,
        'crossover': None,  # 'BUY' or 'SELL' or None
        'timestamp': None,
        'price': None,
        'psar_before': None,
        'psar_after': None,
        'psar_cross_value': None
    }
    
    if df is None or len(df) < 10:
        result['error'] = 'Insufficient data'
        return result
    
    psar, trend = calculate_psar(df)
    
    # Check last 3 candles for crossover
    for i in range(2, len(df)):
        prev_close = df.iloc[i-1]['Close']
        curr_close = df.iloc[i]['Close']
        
        prev_psar = psar.iloc[i-1]
        curr_psar = psar.iloc[i]
        
        # PSAR cross above (BUY signal) - was above, now below
        if prev_psar > prev_close and curr_psar < curr_close:
            result['crossover'] = 'BUY'
            result['timestamp'] = str(df.index[i])
            result['price'] = round(curr_close, 2)
            result['psar_before'] = round(prev_psar, 2)
            result['psar_after'] = round(curr_psar, 2)
            result['psar_cross_value'] = round(curr_psar, 2)
            break
        
        # PSAR cross below (SELL signal) - was below, now above
        elif prev_psar < prev_close and curr_psar > curr_close:
            result['crossover'] = 'SELL'
            result['timestamp'] = str(df.index[i])
            result['price'] = round(curr_close, 2)
            result['psar_before'] = round(prev_psar, 2)
            result['psar_after'] = round(curr_psar, 2)
            result['psar_cross_value'] = round(curr_psar, 2)
            break
    
    return result


def get_psar_alert_message(symbol: str) -> str:
    """
    Generate alert message for PSAR crossover with all timeframe SQZMOM values
    """
    # Using custom Yahoo fetcher
    from datetime import datetime
    
    # Check all timeframes for PSAR crossover
    timeframes = ['5m', '15m', '30m', '60m']
    crossover_found = None
    crossover_tf = None
    
    for tf in timeframes:
        result = check_psar_crossover(symbol, tf)
        if result.get('crossover'):
            crossover_found = result
            crossover_tf = tf
            break
    
    # Build message - just info, no signals
    msg = f"📊 *PSAR CROSSOVER: {symbol}*\n"
    msg += f"⏱️ Timeframe: {crossover_tf or 'N/A'}\n"
    msg += f"🕐 {datetime.now().strftime('%H:%M:%S')}\n"
    msg += f"═══════════════════════════\n"
    
    if crossover_found and crossover_found.get('crossover'):
        # Just info, not signal
        if crossover_found['crossover'] == 'BUY':
            direction = "SAR went BELOW price"
        else:
            direction = "SAR went ABOVE price"
        
        msg += f"{direction}\n"
        msg += f"Price: ₹{crossover_found['price']}\n"
        msg += f"PSAR: ₹{crossover_found['psar_before']} → ₹{crossover_found['psar_after']}\n\n"
    else:
        msg += "No recent PSAR crossover\n\n"
    
    # Add all timeframe SQZMOM values
    all_tf = check_all_timeframes(symbol)
    
    msg += "*📊 SQZMOM All Timeframes:*\n"
    
    for tf in ['5m', '15m', '30m', '60m', '1h', '4h']:
        tf_data = all_tf['timeframes'].get(tf, {})
        
        if 'error' in tf_data:
            continue
        
        squeeze = tf_data.get('squeeze', 'N/A')
        direction = tf_data.get('direction', 'N/A')
        arrow = tf_data.get('arrow', '❓')
        momentum = tf_data.get('momentum', 0)
        
        msg += f"{tf}: {momentum:>7.1f} {arrow} {direction} | Sqz:{squeeze}\n"
    
    return msg


def check_entry_conditions(symbol: str, timeframe: str = "15m") -> dict:
    """
    Check for trade entry conditions:
    
    BUY:
    - Squeeze is ON on both 5m and 15m (or momentum increasing on both)
    - Parabolic SAR crosses above price (PSAR < Close, was previously > Close)
    - Enter at candle close
    
    SELL:
    - Squeeze is ON on both 5m and 15m (or momentum decreasing on both)
    - Parabolic SAR crosses below price (PSAR > Close, was previously < Close)
    - Enter at candle close
    
    Exit conditions:
    - Buy: Close below low of entry candle
    - Sell: Close above high of entry candle
    
    Stop Loss:
    - Buy: Close below low of entry candle
    - Sell: Close above high of entry candle
    """
    # Using custom Yahoo fetcher
    
    # Determine ticker
    if symbol.startswith('^'):
        ticker = symbol
    else:
        ticker = symbol
    
    # Get data for both timeframes
    df_5m = ticker.history(period="2d", interval="5m")
    df_15m = ticker.history(period="2d", interval="15m")
    
    result = {
        "symbol": symbol,
        "timeframe": timeframe,
        "signal": None,  # "BUY", "SELL", or None
        "entry_price": None,
        "stop_loss": None,
        "squeeze_5m": None,
        "squeeze_15m": None,
        "momentum_5m": None,
        "momentum_15m": None,
        "momentum_dir_5m": None,  # "increasing" or "decreasing"
        "momentum_dir_15m": None,
        "psar_cross": None,
        "psar_value": None,
        "close_price": None,
        "close_position": None,
        "timestamp": None
    }
    
    try:
        # Calculate for 5m
        sqz_5m = calculate_sqzmom(df_5m)
        psar_5m, trend_5m = calculate_psar(df_5m)
        
        # Calculate for 15m
        sqz_15m = calculate_sqzmom(df_15m)
        psar_15m, trend_15m = calculate_psar(df_15m)
        
        if sqz_5m.empty or sqz_15m.empty or len(sqz_5m) < 3 or len(sqz_15m) < 3:
            result["error"] = "Insufficient data"
            return result
        
        # Get current candle data (forming candle)
        curr_5m = sqz_5m.iloc[-1]
        prev_5m = sqz_5m.iloc[-2]
        
        curr_15m = sqz_15m.iloc[-1]
        prev_15m = sqz_15m.iloc[-2]
        
        # Squeeze status
        squeeze_5m = curr_5m['squeeze']
        squeeze_15m = curr_15m['squeeze']
        
        # Momentum values
        mom_5m = curr_5m['momentum']
        mom_5m_prev = prev_5m['momentum']
        mom_15m = curr_15m['momentum']
        mom_15m_prev = prev_15m['momentum']
        
        # Momentum direction
        mom_dir_5m = "increasing" if mom_5m > mom_5m_prev else "decreasing"
        mom_dir_15m = "increasing" if mom_15m > mom_15m_prev else "decreasing"
        
        # PSAR values
        psar_val = psar_5m.iloc[-1]
        psar_prev = psar_5m.iloc[-2]
        
        close_price = curr_5m['close']
        
        # Store in result
        result["squeeze_5m"] = squeeze_5m
        result["squeeze_15m"] = squeeze_15m
        result["momentum_5m"] = round(mom_5m, 2)
        result["momentum_15m"] = round(mom_15m, 2)
        result["momentum_dir_5m"] = mom_dir_5m
        result["momentum_dir_15m"] = mom_dir_15m
        result["psar_value"] = round(psar_val, 2)
        result["close_price"] = round(close_price, 2)
        result["close_position"] = round(curr_5m['close_position'], 2)
        result["timestamp"] = str(df_5m.index[-1])
        
        # Check BUY conditions:
        # 1. Momentum increasing on both 5m and 15m
        # 2. PSAR crosses above price (was above, now below)
        momentum_inc = mom_dir_5m == "increasing" and mom_dir_15m == "increasing"
        
        psar_cross_up = (psar_prev > prev_5m['close']) and (psar_val < curr_5m['close'])
        
        if momentum_inc and psar_cross_up:
            result["signal"] = "BUY"
            result["entry_price"] = round(close_price, 2)
            result["stop_loss"] = round(curr_5m['low'], 2)  # SL = low of entry candle
            result["psar_cross"] = "ABOVE"
        
        # Check SELL conditions:
        # 1. Momentum decreasing on both 5m and 15m
        # 2. PSAR crosses below price (was below, now above)
        momentum_dec = mom_dir_5m == "decreasing" and mom_dir_15m == "decreasing"
        
        psar_cross_down = (psar_prev < prev_5m['close']) and (psar_val > curr_5m['close'])
        
        if momentum_dec and psar_cross_down:
            result["signal"] = "SELL"
            result["entry_price"] = round(close_price, 2)
            result["stop_loss"] = round(curr_5m['high'], 2)  # SL = high of entry candle
            result["psar_cross"] = "BELOW"
        
        return result
        
    except Exception as e:
        result["error"] = str(e)
        return result


def check_alerts(symbol: str, timeframe: str, 
                 close_position_threshold: float = 0.90,
                 momentum_decrease_threshold: float = 0) -> Dict:
    """
    Check for alert conditions:
    - Candle closes near high (close_position >= threshold)
    - Momentum is decreasing (current < previous)
    
    Args:
        symbol: Stock symbol
        timeframe: Timeframe to check (e.g., "5m", "15m", "30m")
        close_position_threshold: Min close position to trigger alert (0-1, default 0.90 = within 10% of high)
        momentum_decrease_threshold: Max momentum change to consider "decreasing" (default 0 = any decrease)
    
    Returns:
        Dict with alert info or no alert
    """
    # Using custom Yahoo fetcher
    
    interval_map = {
        "1m": "1m", "5m": "5m", "15m": "15m",
        "30m": "30m", "60m": "60m", "1h": "1h",
        "120m": "90m", "240m": "4h", "1d": "1d"
    }
    
    period_map = {
        "1m": "5d", "5m": "5d", "15m": "5d", "30m": "5d",
        "60m": "1mo", "120m": "1mo", "240m": "2mo", "1d": "3mo"
    }
    
    yf_interval = interval_map.get(timeframe, "5m")
    period = period_map.get(timeframe, "5d")
    
    result = {
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "alert": False,
        "message": ""
    }
    
    try:
        ticker = symbol
        df = ticker.history(period=period, interval=yf_interval)
        
        if df is None or len(df) < 25:
            result["message"] = "Insufficient data"
            return result
        
        sqz_df = calculate_sqzmom(df)
        
        if sqz_df.empty or len(sqz_df) < 2:
            result["message"] = "Insufficient SQZMOM data"
            return result
        
        # Get last two candles
        last_candle = sqz_df.iloc[-1]
        prev_candle = sqz_df.iloc[-2]
        
        current_momentum = last_candle['momentum']
        prev_momentum = prev_candle['momentum']
        current_close_pos = last_candle['close_position']
        squeeze_state = last_candle['squeeze']
        current_price = last_candle['close']
        
        # Check alert conditions
        momentum_decreasing = current_momentum < (prev_momentum + momentum_decrease_threshold)
        close_near_high = current_close_pos >= close_position_threshold
        
        if close_near_high and momentum_decreasing:
            result["alert"] = True
            
            # Calculate how much momentum decreased
            mom_change = current_momentum - prev_momentum
            close_pct = round(current_close_pos * 100, 1)
            
            result["message"] = (
                f"⚠️ ALERT: {symbol} ({timeframe})\n"
                f"  Price: ₹{current_price:.2f}\n"
                f"  Close: {close_pct}% from low (near high)\n"
                f"  Momentum: {current_momentum:.4f} (↓ {abs(mom_change):.4f})\n"
                f"  Squeeze: {squeeze_state}"
            )
        else:
            result["message"] = (
                f"No Alert | Close: {round(current_close_pos*100,1)}% | "
                f"Momentum: {current_momentum:.4f} ({'↓' if momentum_decreasing else '↑'})"
            )
        
    except Exception as e:
        result["message"] = f"Error: {str(e)}"
    
    return result


def get_sqzmom_data(symbol: str, timeframes: List[str] = None) -> Dict:
    """
    Get SQZMOM data for multiple timeframes.
    
    Args:
        symbol: Stock symbol (e.g., "RELIANCE")
        timeframes: List of timeframes to fetch (default: all available)
    
    Returns:
        Dict with timeframe data and last 5 candle momentum values
    """
    # Using custom Yahoo fetcher
    
    # Default timeframes
    if timeframes is None:
        timeframes = ["5m", "15m", "30m", "60m", "120m", "240m", "1d"]
    
    interval_map = {
        "1m": "1m", "5m": "5m", "15m": "15m",
        "30m": "30m", "60m": "60m", "1h": "1h",
        "120m": "90m", "240m": "4h", "1d": "1d"
    }
    
    # Period mapping for different timeframes
    period_map = {
        "1m": "5d",
        "5m": "5d",
        "15m": "5d",
        "30m": "5d",
        "60m": "1mo",
        "120m": "1mo",
        "240m": "2mo",
        "1d": "3mo"
    }
    
    result = {
        "symbol": symbol.upper(),
        "timeframes": {},
        "current_price": None
    }
    
    try:
        ticker = symbol
        
        # Get current price
        stock_info = ticker.fast_info
        if stock_info.last_price:
            result["current_price"] = round(stock_info.last_price, 2)
        
        for tf in timeframes:
            yf_interval = interval_map.get(tf, "5m")
            period = period_map.get(tf, "5d")
            
            # Get data
            df = ticker.history(period=period, interval=yf_interval)
            
            if df is None or len(df) < 25:
                result["timeframes"][tf] = {"error": f"Insufficient data ({len(df) if df is not None else 0} candles)"}
                continue
            
            # Calculate SQZMOM
            sqz_df = calculate_sqzmom(df)
            
            if sqz_df.empty or len(sqz_df) < 5:
                result["timeframes"][tf] = {"error": "Insufficient SQZMOM data"}
                continue
            
            # Get last 5 values (most recent first)
            last_5 = sqz_df.tail(5).iloc[::-1]
            
            # Get timestamp of last candle
            last_timestamp = df.index[-1].strftime("%Y-%m-%d %H:%M") if hasattr(df.index[-1], 'strftime') else str(df.index[-1])
            
            result["timeframes"][tf] = {
                "current_price": round(sqz_df['close'].iloc[-1], 2),
                "current_momentum": round(sqz_df['momentum'].iloc[-1], 4),
                "current_squeeze": sqz_df['squeeze'].iloc[-1],
                "last_timestamp": last_timestamp,
                "last_5_candles": [
                    {
                        "candle": i + 1,
                        "close": round(row['close'], 2),
                        "momentum": round(row['momentum'], 4),
                        "squeeze": row['squeeze']
                    }
                    for i, (_, row) in enumerate(last_5.iterrows())
                ]
            }
            
    except Exception as e:
        result["error"] = str(e)
    
    return result


def format_sqzmom_response(data: Dict) -> str:
    """Format SQZMOM data as readable string"""
    if "error" in data:
        return f"Error: {data['error']}"
    
    symbol = data.get("symbol", "")
    current_price = data.get("current_price", 0)
    
    msg = f"📊 {symbol} | Current Price: ₹{current_price}\n"
    msg += "=" * 60 + "\n"
    
    for tf, tf_data in data.get("timeframes", {}).items():
        if "error" in tf_data:
            msg += f"\n{tf}: {tf_data['error']}\n"
            continue
        
        squeeze = tf_data.get("current_squeeze", "NONE")
        momentum = tf_data.get("current_momentum", 0)
        
        squeeze_emoji = "🔴" if squeeze == "ON" else "🟢" if squeeze == "OFF" else "⚪"
        
        msg += f"\n⏱️ {tf}: Squeeze {squeeze_emoji} {squeeze} | Momentum: {momentum:.4f}\n"
        msg += "-" * 40 + "\n"
        
        for candle in tf_data.get("last_5_candles", []):
            m = candle['momentum']
            sqz = candle['squeeze']
            sqz_char = "🔴" if sqz == "ON" else "🟢" if sqz == "OFF" else "⚪"
            msg += f"  Candle {candle['candle']}: {m:>8.4f} {sqz_char}\n"
    
    return msg


def get_squeeze_direction(symbol: str, timeframe: str) -> str:
    """
    Get squeeze direction: 'INCREASING' or 'DECREASING' for a timeframe
    Based on momentum change between recent and previous candles
    """
    try:
        df = get_yahoo_data(symbol, period="10d", interval=timeframe)
        if df is None or len(df) < 20:
            return "NONE"
        
        sqz_df = calculate_sqzmom(df)
        if len(sqz_df) < 20:
            return "NONE"
        
        # Compare last 5 candles momentum vs previous 5
        recent_momentum = sqz_df['momentum'].tail(5).mean()
        prev_momentum = sqz_df.iloc[-10:-5]['momentum'].mean() if len(sqz_df) >= 10 else sqz_df.head(5)['momentum'].mean()
        
        momentum_change = recent_momentum - prev_momentum
        
        if momentum_change > 0.1:
            return "INCREASING"
        elif momentum_change < -0.1:
            return "DECREASING"
        else:
            return "NONE"
    except:
        return "NONE"


def check_new_alert_logic(symbol: str) -> dict:
    """
    New alert logic based on user requirements:
    
    30m PSAR crossover +:
    - BUY: 60m,120m,240m,1d squeeze INCREASING + PSAR crosses above
    - SELL: 60m,120m,240m,1d squeeze DECREASING + PSAR crosses below
    
    60m PSAR crossover +:
    - BUY: 120m,240m,1d squeeze INCREASING + PSAR crosses above
    - SELL: 120m,240m,1d squeeze DECREASING + PSAR crosses below
    
    120m PSAR crossover +:
    - BUY: 240m,1d squeeze INCREASING + PSAR crosses above
    - SELL: 240m,1d squeeze DECREASING + PSAR crosses below
    """
    # Map our TFs to Yahoo TFs: 60m->1h, 120m->2h, 240m->4h
    tf_config = {
        '30m': {'interval': '30m', 'squeeze_tfs': [('1h', '60m'), ('2h', '120m'), ('4h', '240m'), ('1d', '1d')], 'psar_cross_above_is_buy': True},
        '60m': {'interval': '1h', 'squeeze_tfs': [('2h', '120m'), ('4h', '240m'), ('1d', '1d')], 'psar_cross_above_is_buy': True},
        '120m': {'interval': '2h', 'squeeze_tfs': [('4h', '240m'), ('1d', '1d')], 'psar_cross_above_is_buy': True}
    }
    
    results = {'symbol': symbol, 'alerts': []}
    
    for main_tf, config in tf_config.items():
        # Get PSAR crossover in main timeframe
        psar_result = check_psar_crossover(symbol, main_tf)
        
        if not psar_result.get('crossover'):
            continue
        
        crossover = psar_result['crossover']  # 'BUY' or 'SELL'
        psar_cross_above = (crossover == 'BUY')  # PSAR above = BUY signal
        
        # Get squeeze directions for all required timeframes
        squeeze_directions = {}
        valid = True
        
        for yahoo_tf, display_name in config['squeeze_tfs']:
            direction = get_squeeze_direction(symbol, yahoo_tf)
            if direction == "NONE":
                valid = False
                break
            squeeze_directions[display_name] = direction
        
        if not valid:
            continue
        
        # Check conditions
        should_alert = False
        
        if main_tf == '30m':
            if psar_cross_above:
                should_alert = all(d == 'INCREASING' for d in ['60m', '120m', '240m', '1d'] if d in squeeze_directions)
            else:
                should_alert = all(d == 'DECREASING' for d in ['60m', '120m', '240m', '1d'] if d in squeeze_directions)
        
        elif main_tf == '60m':
            if psar_cross_above:
                should_alert = all(d == 'INCREASING' for d in ['120m', '240m', '1d'] if d in squeeze_directions)
            else:
                should_alert = all(d == 'DECREASING' for d in ['120m', '240m', '1d'] if d in squeeze_directions)
        
        elif main_tf == '120m':
            if psar_cross_above:
                should_alert = all(d == 'INCREASING' for d in ['240m', '1d'] if d in squeeze_directions)
            else:
                should_alert = all(d == 'DECREASING' for d in ['240m', '1d'] if d in squeeze_directions)
        
        if should_alert:
            signal = "🟢 BUY" if psar_cross_above else "🔴 SELL"
            results['alerts'].append({
                'timeframe': main_tf,
                'signal': signal,
                'psar_crossover': crossover,
                'psar_price': psar_result['price'],
                'psar_before': psar_result['psar_before'],
                'psar_after': psar_result['psar_after'],
                'timestamp': psar_result['timestamp'],
                'squeeze_directions': squeeze_directions
            })
    
    return results


def format_new_alert_message(symbol: str) -> str:
    """Format alert results for Telegram message"""
    result = check_new_alert_logic(symbol)
    
    if not result.get('alerts'):
        return f"ℹ️ No alerts for {symbol}"
    
    msg = f"🔔 *NEW ALERT: {symbol}*\n"
    msg += "=" * 40 + "\n"
    
    for alert in result['alerts']:
        msg += f"\n⏱️ *Timeframe:* {alert['timeframe']}\n"
        msg += f"📊 *Signal:* {alert['signal']}\n"
        msg += f"🕐 {alert['timestamp']}\n"
        msg += f"💰 Price: ₹{alert['psar_price']}\n"
        msg += f"📈 PSAR: ₹{alert['psar_before']} → ₹{alert['psar_after']}\n"
        msg += f"\n*Squeeze Directions:*\n"
        for tf, direction in alert['squeeze_directions'].items():
            arrow = "📈" if direction == "INCREASING" else "📉" if direction == "DECREASING" else "➡️"
            msg += f"  {tf}: {direction} {arrow}\n"
        msg += "-" * 40 + "\n"
    
    return msg


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python sqz_api.py <SYMBOL> [timeframes]")
        print("Example: python sqz_api.py RELIANCE")
        print("Example: python sqz_api.py RELIANCE 5m,15m,30m")
        sys.exit(1)
    
    symbol = sys.argv[1]
    timeframes = sys.argv[2].split(",") if len(sys.argv) > 2 else None
    
    data = get_sqzmom_data(symbol, timeframes)
    print(format_sqzmom_response(data))