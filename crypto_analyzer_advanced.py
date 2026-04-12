# crypto_analyzer_advanced.py
# Versão FINAL com suporte à API Key CoinGecko Pro + Telegram integrado

import sys
import logging
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Optional

import config

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("crypto_analyzer.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("CryptoAnalyzer")

# ============================================================
# VERIFICAÇÃO DA API KEY
# ============================================================
def verificar_api_key():
    if not config.COINGECKO_API_KEY:
        logger.error("❌ API Key não configurada!")
        logger.info("   Configure o secret COINGECKO_API_KEY no GitHub Actions.")
        return False
    logger.info(f"✅ API Key configurada: {config.COINGECKO_API_KEY[:10]}...")
    return True

# ============================================================
# TELEGRAM
# ============================================================
def send_telegram(message: str):
    if not config.TELEGRAM_ENABLED or not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.warning("Telegram não configurado, pulando envio.")
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
        if resp.status_code == 200:
            logger.info("✅ Mensagem enviada ao Telegram.")
        else:
            logger.error(f"Telegram erro {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.error(f"Erro ao enviar Telegram: {e}")

def send_telegram_long(message: str):
    """Envia mensagens longas em blocos de até 4096 caracteres."""
    if not config.TELEGRAM_ENABLED or not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID:
        return
    max_len = 4096
    for i in range(0, len(message), max_len):
        send_telegram(message[i:i + max_len])
        time.sleep(0.5)

def build_telegram_message(df_long: pd.DataFrame, df_short: pd.DataFrame) -> str:
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    lines = [
        f"🤖 <b>Crypto Analyzer — {now}</b>",
        "",
        "📈 <b>TOP 10 LONG (maior potencial de alta)</b>",
        "─────────────────────────────"
    ]

    for rank, (_, row) in enumerate(df_long.head(10).iterrows(), start=1):
        bt = row.get("backtest") or {}
        bt_str = ""
        if bt and bt.get("trades", 0) > 0:
            bt_str = (
                f"  📊 Backtest: retorno <b>{bt['total_return']:.1%}</b> | "
                f"win rate <b>{bt['win_rate']:.0%}</b> | {bt['trades']} trades"
            )

        lines.append(
            f"{rank}. <b>{row['symbol']}</b> — {row['name']}\n"
            f"  💰 ${row['price']:.4f} | Score: <b>{row['score_long']:.3f}</b>\n"
            f"  ⏱ 1h: {_fmt(row['change_1h'])} | "
            f"24h: {_fmt(row['change_24h'])} | "
            f"7d: {_fmt(row['change_7d'])}\n"
            f"  📦 Vol 24h: ${row['volume_24h']:,.0f}"
            + (f"\n{bt_str}" if bt_str else "")
        )

    lines += [
        "",
        "📉 <b>TOP 5 SHORT (maior potencial de queda)</b>",
        "─────────────────────────────"
    ]

    for rank, (_, row) in enumerate(df_short.head(5).iterrows(), start=1):
        lines.append(
            f"{rank}. <b>{row['symbol']}</b> — {row['name']}\n"
            f"  💰 ${row['price']:.4f} | Score Short: <b>{row['score_short']:.3f}</b>\n"
            f"  ⏱ 1h: {_fmt(row['change_1h'])} | "
            f"24h: {_fmt(row['change_24h'])} | "
            f"7d: {_fmt(row['change_7d'])}"
        )

    lines += ["", "─────────────────────────────", "🔄 Próxima análise em ~15 min"]
    return "\n".join(lines)

def _fmt(value) -> str:
    """Formata variação percentual com emoji."""
    try:
        v = float(value)
        emoji = "🟢" if v >= 0 else "🔴"
        return f"{emoji} {v:+.2f}%"
    except (TypeError, ValueError):
        return "—"

# ============================================================
# INDICADORES TÉCNICOS
# ============================================================
def calculate_rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=length).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=length).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return {"macd": macd_line, "signal": signal_line, "histogram": macd_line - signal_line}

def calculate_ema(close: pd.Series, length: int) -> pd.Series:
    return close.ewm(span=length, adjust=False).mean()

def calculate_adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    plus_dm = high.diff()
    minus_dm = low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm > 0] = 0
    minus_dm = abs(minus_dm)
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=14).mean()
    plus_di = 100 * (plus_dm.rolling(window=14).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(window=14).mean() / atr)
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    return dx.rolling(window=14).mean()

def calculate_cci(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 20) -> pd.Series:
    tp = (high + low + close) / 3
    sma = tp.rolling(window=length).mean()
    mad = tp.rolling(window=length).apply(lambda x: np.abs(x - x.mean()).mean())
    return (tp - sma) / (0.015 * mad)

def calculate_bollinger_bands(close: pd.Series, length: int = 20, std: int = 2) -> Dict:
    sma = close.rolling(window=length).mean()
    std_dev = close.rolling(window=length).std()
    return {"upper": sma + (std_dev * std), "middle": sma, "lower": sma - (std_dev * std)}

def calculate_stoch(high: pd.Series, low: pd.Series, close: pd.Series, k: int = 14, d: int = 3) -> Dict:
    lowest_low = low.rolling(window=k).min()
    highest_high = high.rolling(window=k).max()
    stoch_k = 100 * ((close - lowest_low) / (highest_high - lowest_low))
    return {"k": stoch_k, "d": stoch_k.rolling(window=d).mean()}

def calculate_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    obv = pd.Series(index=close.index, dtype=float)
    obv.iloc[0] = volume.iloc[0]
    for i in range(1, len(close)):
        if close.iloc[i] > close.iloc[i-1]:
            obv.iloc[i] = obv.iloc[i-1] + volume.iloc[i]
        elif close.iloc[i] < close.iloc[i-1]:
            obv.iloc[i] = obv.iloc[i-1] - volume.iloc[i]
        else:
            obv.iloc[i] = obv.iloc[i-1]
    return obv

def calculate_aroon(high: pd.Series, low: pd.Series, length: int = 25) -> Dict:
    aroon_up = 100 * (high.rolling(window=length+1).apply(lambda x: x.argmax()) / length)
    aroon_down = 100 * (low.rolling(window=length+1).apply(lambda x: x.argmin()) / length)
    return {"up": aroon_up, "down": aroon_down}

# ============================================================
# 1. BUSCAR LISTA DE MOEDAS
# ============================================================
def fetch_coin_list() -> pd.DataFrame:
    headers = {
        "x-cg-pro-api-key": config.COINGECKO_API_KEY,
        "Accept": "application/json"
    }

    all_coins = []
    page = 1
    per_page = 250
    max_coins = config.COINGECKO_MAX_COINS

    while len(all_coins) < max_coins:
        url = "https://pro-api.coingecko.com/api/v3/coins/markets"
        params = {
            "vs_currency": config.COINGECKO_VS_CURRENCY,
            "order": "market_cap_desc",
            "per_page": min(per_page, max_coins - len(all_coins)),
            "page": page,
            "sparkline": "false",
            "price_change_percentage": "1h,24h,7d"
        }

        try:
            logger.info(f"Buscando página {page}...")
            resp = requests.get(url, headers=headers, params=params, timeout=30)

            if resp.status_code == 429:
                logger.warning("Rate limit. Aguardando 60s...")
                time.sleep(60)
                continue

            resp.raise_for_status()
            data = resp.json()

            if not data:
                break

            all_coins.extend(data)
            logger.info(f"Página {page}: {len(data)} moedas. Total: {len(all_coins)}")
            page += 1
            time.sleep(0.5)

        except Exception as e:
            logger.error(f"Erro na página {page}: {e}")
            if 'resp' in locals():
                logger.error(f"Status: {resp.status_code}")
                logger.error(f"Resposta: {resp.text[:200]}")
            break

    if not all_coins:
        logger.error("Nenhuma moeda encontrada.")
        return pd.DataFrame()

    df = pd.DataFrame(all_coins)
    df = df[~df["symbol"].str.lower().isin(config.STABLECOINS_SYMBOLS)]
    df = df[~df["name"].str.lower().str.contains("|".join(config.STABLECOINS_NAMES), na=False)]
    df = df[df["total_volume"] >= config.MIN_VOLUME_USD]
    df = df[df["current_price"] >= config.MIN_PRICE_USD]

    df = df[[
        "id", "symbol", "name", "current_price",
        "price_change_percentage_1h_in_currency",
        "price_change_percentage_24h_in_currency",
        "price_change_percentage_7d_in_currency",
        "total_volume"
    ]]
    df.columns = ["coin_id", "symbol", "name", "price",
                  "change_1h", "change_24h", "change_7d", "volume_24h"]
    df = df.head(max_coins)

    logger.info(f"✅ {len(df)} moedas carregadas após filtros.")
    return df

# ============================================================
# 2. BUSCAR DADOS HISTÓRICOS
# ============================================================
def fetch_ohlcv_coingecko(coin_id: str, days: int) -> Optional[pd.DataFrame]:
    headers = {
        "x-cg-pro-api-key": config.COINGECKO_API_KEY,
        "Accept": "application/json"
    }

    url = f"https://pro-api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
    params = {
        "vs_currency": config.COINGECKO_VS_CURRENCY,
        "days": days,
        "interval": "daily"
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)

        if resp.status_code == 429:
            logger.warning(f"Rate limit para {coin_id}, aguardando...")
            time.sleep(60)
            return fetch_ohlcv_coingecko(coin_id, days)

        resp.raise_for_status()
        data = resp.json()

        if "prices" not in data or not data["prices"]:
            return None

        df = pd.DataFrame(data["prices"], columns=["timestamp", "close"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)

        if "total_volumes" in data and data["total_volumes"]:
            vol_df = pd.DataFrame(data["total_volumes"], columns=["timestamp", "volume"])
            vol_df["timestamp"] = pd.to_datetime(vol_df["timestamp"], unit="ms")
            vol_df.set_index("timestamp", inplace=True)
            df["volume"] = vol_df["volume"]
        else:
            df["volume"] = 0

        df["open"] = df["close"].shift(1)
        df["high"] = df["close"].rolling(2).max()
        df["low"] = df["close"].rolling(2).min()
        df.ffill(inplace=True)
        df.bfill(inplace=True)

        return df[["open", "high", "low", "close", "volume"]]

    except Exception as e:
        logger.error(f"Erro ao buscar dados de {coin_id}: {e}")
        return None

# ============================================================
# 3. CÁLCULO DE INDICADORES E SCORES
# ============================================================
def calculate_indicators(df: pd.DataFrame) -> Dict[str, float]:
    if df is None or len(df) < 50:
        return {}

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    rsi = calculate_rsi(close, 14)
    rsi_val = rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50

    macd_data = calculate_macd(close)
    macd_hist = macd_data["histogram"].iloc[-1] if not pd.isna(macd_data["histogram"].iloc[-1]) else 0

    ema9 = calculate_ema(close, 9)
    ema21 = calculate_ema(close, 21)
    ema9_val = ema9.iloc[-1] if not pd.isna(ema9.iloc[-1]) else close.iloc[-1]
    ema21_val = ema21.iloc[-1] if not pd.isna(ema21.iloc[-1]) else close.iloc[-1]
    preco = close.iloc[-1]

    adx = calculate_adx(high, low, close, 14)
    adx_val = adx.iloc[-1] if not pd.isna(adx.iloc[-1]) else 20

    cci = calculate_cci(high, low, close, 20)
    cci_val = cci.iloc[-1] if not pd.isna(cci.iloc[-1]) else 0

    bb = calculate_bollinger_bands(close, 20, 2)
    bb_position = (preco - bb["lower"].iloc[-1]) / (bb["upper"].iloc[-1] - bb["lower"].iloc[-1]) \
        if (bb["upper"].iloc[-1] - bb["lower"].iloc[-1]) != 0 else 0.5

    stoch = calculate_stoch(high, low, close, 14, 3)
    stoch_k = stoch["k"].iloc[-1] if not pd.isna(stoch["k"].iloc[-1]) else 50

    obv = calculate_obv(close, volume)
    obv_trend = 1 if len(obv) > 1 and obv.iloc[-1] > obv.iloc[-2] else 0

    aroon = calculate_aroon(high, low, 25)
    aroon_strength = (aroon["up"].iloc[-1] - aroon["down"].iloc[-1]) / 100 \
        if not pd.isna(aroon["up"].iloc[-1]) else 0

    vol_ma = volume.rolling(20).mean().iloc[-1] if len(volume) >= 20 else volume.iloc[-1]
    volume_ratio = volume.iloc[-1] / vol_ma if vol_ma > 0 else 1.0

    return {
        "rsi": rsi_val, "macd_hist": macd_hist, "price": preco,
        "ema9": ema9_val, "ema21": ema21_val, "adx": adx_val, "cci": cci_val,
        "bb_position": bb_position, "stoch_k": stoch_k, "obv_trend": obv_trend,
        "aroon_strength": aroon_strength, "volume_ratio": volume_ratio
    }

def compute_score_long(indicators: Dict[str, float]) -> float:
    w = config.WEIGHTS_LONG
    if not indicators:
        return 0.0

    rsi = indicators["rsi"]
    score_rsi = 1.0 if rsi < 30 else (0.0 if rsi > 70 else (70 - rsi) / 40)

    macd_hist = indicators["macd_hist"]
    score_macd = min(1.0, max(0.0, (macd_hist + 0.5) / 1.0)) if macd_hist > -0.5 else 0.0

    preco, ema9, ema21 = indicators["price"], indicators["ema9"], indicators["ema21"]
    if preco > ema9 and ema9 > ema21:
        score_ema = 1.0
    elif preco > ema9:
        score_ema = 0.6
    elif preco > ema21:
        score_ema = 0.3
    else:
        score_ema = 0.0

    adx = indicators["adx"]
    score_adx = min(1.0, max(0.0, (adx - 20) / 30))

    cci = indicators["cci"]
    score_cci = min(1.0, max(0.0, (cci + 100) / 200))

    bb_pos = indicators["bb_position"]
    score_bb = 1.0 - bb_pos

    stoch_k = indicators["stoch_k"]
    score_stoch = 1.0 if stoch_k < 20 else (0.0 if stoch_k > 80 else (80 - stoch_k) / 60)

    score_obv = indicators["obv_trend"]

    aroon_str = indicators["aroon_strength"]
    score_aroon = min(1.0, max(0.0, (aroon_str + 1) / 2))

    vol_ratio = indicators["volume_ratio"]

    score = (w["rsi"] * score_rsi + w["macd"] * score_macd + w["ema"] * score_ema +
             w["adx"] * score_adx + w["cci"] * score_cci + w["bbands"] * score_bb +
             w["stoch"] * score_stoch + w["obv"] * score_obv + w["aroon"] * score_aroon)

    return round(min(1.0, score * (0.9 + min(0.2, vol_ratio * 0.1))), 4)

def compute_score_short(indicators: Dict[str, float]) -> float:
    w = config.WEIGHTS_SHORT
    if not indicators:
        return 0.0

    rsi = indicators["rsi"]
    score_rsi = 1.0 if rsi > 70 else (0.0 if rsi < 30 else (rsi - 30) / 40)

    macd_hist = indicators["macd_hist"]
    score_macd = min(1.0, max(0.0, (-macd_hist + 0.5) / 1.0)) if macd_hist < 0.5 else 0.0

    preco, ema9, ema21 = indicators["price"], indicators["ema9"], indicators["ema21"]
    if preco < ema9 and ema9 < ema21:
        score_ema = 1.0
    elif preco < ema9:
        score_ema = 0.6
    elif preco < ema21:
        score_ema = 0.3
    else:
        score_ema = 0.0

    adx = indicators["adx"]
    score_adx = min(1.0, max(0.0, (adx - 20) / 30))

    cci = indicators["cci"]
    score_cci = min(1.0, max(0.0, (100 - cci) / 200))

    bb_pos = indicators["bb_position"]
    score_bb = bb_pos

    stoch_k = indicators["stoch_k"]
    score_stoch = 1.0 if stoch_k > 80 else (0.0 if stoch_k < 20 else (stoch_k - 20) / 60)

    score_obv = 1 - indicators["obv_trend"]

    aroon_str = indicators["aroon_strength"]
    score_aroon = min(1.0, max(0.0, (1 - (aroon_str + 1) / 2)))

    vol_ratio = indicators["volume_ratio"]

    score = (w["rsi"] * score_rsi + w["macd"] * score_macd + w["ema"] * score_ema +
             w["adx"] * score_adx + w["cci"] * score_cci + w["bbands"] * score_bb +
             w["stoch"] * score_stoch + w["obv"] * score_obv + w["aroon"] * score_aroon)

    return round(min(1.0, score * (0.9 + min(0.2, vol_ratio * 0.1))), 4)

# ============================================================
# 4. BACKTESTING
# ============================================================
def backtest_strategy(df_ohlc: pd.DataFrame) -> Dict:
    if df_ohlc is None or len(df_ohlc) < config.BACKTEST_TEST_DAYS + 30:
        return {"total_return": 0, "win_rate": 0, "trades": 0}

    test_data = df_ohlc.iloc[-config.BACKTEST_TEST_DAYS:].copy()
    if len(test_data) < 10:
        return {"total_return": 0, "win_rate": 0, "trades": 0}

    signals = []
    for i in range(30, len(test_data)):
        hist = test_data.iloc[:i]
        ind = calculate_indicators(hist)
        if not ind:
            continue
        if compute_score_long(ind) > 0.7:
            signals.append(1)
        elif compute_score_short(ind) > 0.7:
            signals.append(-1)
        else:
            signals.append(0)

    prices = test_data["close"].values
    returns = []
    position = 0
    entry_price = 0
    capital = config.BACKTEST_INITIAL_CAPITAL

    for idx, sig in enumerate(signals):
        if idx >= len(prices) - 1:
            break
        if sig == 1 and position == 0:
            position, entry_price = 1, prices[idx]
        elif sig == -1 and position == 0:
            position, entry_price = -1, prices[idx]
        elif sig == 0 and position != 0:
            exit_price = prices[idx]
            ret = (exit_price - entry_price) / entry_price if position == 1 \
                else (entry_price - exit_price) / entry_price
            returns.append(ret)
            capital *= (1 + ret)
            position = 0

    if position != 0:
        exit_price = prices[-1]
        ret = (exit_price - entry_price) / entry_price if position == 1 \
            else (entry_price - exit_price) / entry_price
        returns.append(ret)
        capital *= (1 + ret)

    total_return = (capital - config.BACKTEST_INITIAL_CAPITAL) / config.BACKTEST_INITIAL_CAPITAL
    win_rate = sum(1 for r in returns if r > 0) / len(returns) if returns else 0
    return {"total_return": total_return, "win_rate": win_rate, "trades": len(returns)}

# ============================================================
# 5. ANÁLISE PRINCIPAL
# ============================================================
def analyze_coin(coin_row: pd.Series) -> Dict:
    coin_id = coin_row["coin_id"]
    symbol = coin_row["symbol"].upper()
    name = coin_row["name"]

    logger.info(f"Processando {name} ({symbol})")
    df_ohlc = fetch_ohlcv_coingecko(coin_id, days=config.HISTORICAL_DAYS)

    if df_ohlc is None:
        return None

    indicators = calculate_indicators(df_ohlc)
    if not indicators:
        return None

    score_long = compute_score_long(indicators)
    score_short = compute_score_short(indicators)
    backtest_result = backtest_strategy(df_ohlc) if config.BACKTEST_ENABLED else None

    return {
        "symbol": symbol, "name": name, "price": coin_row["price"],
        "change_1h": coin_row["change_1h"], "change_24h": coin_row["change_24h"],
        "change_7d": coin_row["change_7d"], "volume_24h": coin_row["volume_24h"],
        "score_long": score_long, "score_short": score_short, "backtest": backtest_result
    }

def main():
    logger.info("Iniciando análise avançada (CoinGecko Pro + Telegram)...")

    if not verificar_api_key():
        send_telegram("❌ <b>Crypto Analyzer</b>\nAPI Key da CoinGecko não configurada. Verifique os secrets do GitHub Actions.")
        return

    df_coins = fetch_coin_list()
    if df_coins.empty:
        send_telegram("❌ <b>Crypto Analyzer</b>\nNenhuma moeda obtida. Verifique a API Key e a conexão.")
        logger.error("Nenhuma moeda obtida.")
        return

    results = []
    total = len(df_coins)

    for idx, row in df_coins.iterrows():
        logger.info(f"Progresso: {idx+1}/{total} - {row['symbol'].upper()}")
        result = analyze_coin(row)
        if result:
            results.append(result)
        time.sleep(0.3)

    if not results:
        send_telegram("⚠️ <b>Crypto Analyzer</b>\nAnálise concluída, mas nenhum resultado válido foi gerado.")
        logger.error("Nenhum resultado válido.")
        return

    df_long = pd.DataFrame(results).sort_values("score_long", ascending=False)
    df_short = pd.DataFrame(results).sort_values("score_short", ascending=False)

    # Exibir no terminal
    print("\n" + "="*80)
    print("📈 TOP 10 PARA LONG (COMPRA)")
    print("="*80)
    for rank, (_, row) in enumerate(df_long.head(10).iterrows(), start=1):
        print(f"{rank}. {row['symbol']} - {row['name']}")
        print(f"   Score Long: {row['score_long']:.4f} | Preço: ${row['price']:.4f}")
        print(f"   1h: {row['change_1h']:+.2f}% | 24h: {row['change_24h']:+.2f}% | 7d: {row['change_7d']:+.2f}%")
        print(f"   Volume 24h: ${row['volume_24h']:,.0f}")
        if row.get("backtest") and row["backtest"]["trades"] > 0:
            bt = row["backtest"]
            print(f"   Backtest: {bt['total_return']:.2%} retorno | {bt['win_rate']:.1%} win rate | {bt['trades']} trades")
        print()

    print("\n" + "="*80)
    print("📉 TOP 5 PARA SHORT (VENDA)")
    print("="*80)
    for rank, (_, row) in enumerate(df_short.head(5).iterrows(), start=1):
        print(f"{rank}. {row['symbol']} - {row['name']} (Score Short: {row['score_short']:.4f})")

    # Enviar ao Telegram
    msg = build_telegram_message(df_long, df_short)
    send_telegram_long(msg)

    # Salvar CSV
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    df_long.to_csv(f"ranking_long_{timestamp}.csv", index=False)
    df_short.to_csv(f"ranking_short_{timestamp}.csv", index=False)
    logger.info(f"✅ Resultados salvos em ranking_long_{timestamp}.csv")

if __name__ == "__main__":
    main()
