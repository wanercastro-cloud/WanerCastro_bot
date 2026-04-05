# crypto_analyzer_advanced.py
# Módulo principal com toda a lógica de análise (apenas CoinGecko)

import sys
import logging
import time
import requests
import pandas as pd
import pandas_ta as ta
from datetime import datetime
from typing import Dict, Optional, List

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
# UTILITÁRIOS - TELEGRAM
# ============================================================
def send_telegram_message(message: str):
    """Envia mensagem via Telegram com tratamento de erros."""
    if not config.TELEGRAM_ENABLED:
        logger.debug("Telegram desabilitado. Mensagem não enviada.")
        return

    token = config.TELEGRAM_BOT_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID

    if not token or not chat_id:
        logger.error("Token ou Chat ID do Telegram não configurados.")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(f"Mensagem Telegram enviada: {message[:50]}...")
    except requests.exceptions.Timeout:
        logger.error("Timeout ao enviar mensagem Telegram.")
    except requests.exceptions.RequestException as e:
        logger.error(f"Erro ao enviar mensagem Telegram: {e}")
        if response.status_code == 401:
            logger.error("Token inválido. Verifique TELEGRAM_BOT_TOKEN.")
        elif response.status_code == 400:
            logger.error("Chat ID inválido. Verifique TELEGRAM_CHAT_ID.")

# ============================================================
# 1. BUSCAR LISTA DE MOEDAS (CoinGecko)
# ============================================================
def fetch_coin_list() -> pd.DataFrame:
    """
    Obtém lista das principais moedas da CoinGecko, aplica filtros.
    Retorna DataFrame com colunas: coin_id, symbol, name, price,
    change_1h, change_24h, change_7d, volume_24h.
    """
    headers = {}
    if config.COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = config.COINGECKO_API_KEY

    all_coins = []
    page = 1
    per_page = 250
    max_coins = config.COINGECKO_MAX_COINS

    while len(all_coins) < max_coins:
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {
            "vs_currency": config.COINGECKO_VS_CURRENCY,
            "order": "market_cap_desc",
            "per_page": min(per_page, max_coins - len(all_coins)),
            "page": page,
            "sparkline": "false",
            "price_change_percentage": "1h,24h,7d"
        }
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break
            all_coins.extend(data)
            page += 1
            # Pausa para evitar rate limit (30/min na free)
            if not config.COINGECKO_API_KEY:
                time.sleep(2)
        except Exception as e:
            logger.error(f"Erro ao buscar página {page} da CoinGecko: {e}")
            break

    if not all_coins:
        logger.error("Nenhuma moeda encontrada na CoinGecko.")
        return pd.DataFrame()

    df = pd.DataFrame(all_coins)

    # Filtros
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

    logger.info(f"Carregadas {len(df)} moedas da CoinGecko após filtros.")
    return df

# ============================================================
# 2. BUSCAR DADOS HISTÓRICOS (CoinGecko)
# ============================================================
def fetch_ohlcv_coingecko(coin_id: str, days: int) -> Optional[pd.DataFrame]:
    """
    Busca dados de preço histórico (OHLCV aproximado) da CoinGecko.
    Retorna DataFrame com colunas 'open', 'high', 'low', 'close', 'volume'.
    """
    headers = {}
    if config.COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = config.COINGECKO_API_KEY

    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
    params = {
        "vs_currency": config.COINGECKO_VS_CURRENCY,
        "days": days,
        "interval": "daily"
    }
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if "prices" not in data or not data["prices"]:
            logger.warning(f"Sem dados de preço para {coin_id}")
            return None

        # Cria DataFrame com preços de fechamento
        df = pd.DataFrame(data["prices"], columns=["timestamp", "close"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)

        # Adiciona volume se disponível
        if "total_volumes" in data and data["total_volumes"]:
            vol_df = pd.DataFrame(data["total_volumes"], columns=["timestamp", "volume"])
            vol_df["timestamp"] = pd.to_datetime(vol_df["timestamp"], unit="ms")
            vol_df.set_index("timestamp", inplace=True)
            df["volume"] = vol_df["volume"]
        else:
            df["volume"] = 0

        # Gera OHLC aproximado (útil para alguns indicadores)
        df["open"] = df["close"].shift(1)
        df["high"] = df["close"].rolling(2).max()
        df["low"] = df["close"].rolling(2).min()
        df.fillna(method="bfill", inplace=True)

        return df[["open", "high", "low", "close", "volume"]]

    except Exception as e:
        logger.error(f"Erro ao buscar dados históricos para {coin_id}: {e}")
        return None

# ============================================================
# 3. CÁLCULO DE INDICADORES
# ============================================================
def calculate_indicators(df: pd.DataFrame) -> Dict[str, float]:
    if df is None or len(df) < 50:
        return {}

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    # RSI
    rsi = ta.rsi(close, length=14)
    rsi_val = rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50

    # MACD
    macd = ta.macd(close)
    macd_hist = macd["MACDh_12_26_9"].iloc[-1] if macd is not None and "MACDh_12_26_9" in macd.columns else 0

    # EMAs
    ema9 = ta.ema(close, length=9)
    ema21 = ta.ema(close, length=21)
    ema9_val = ema9.iloc[-1] if not pd.isna(ema9.iloc[-1]) else close.iloc[-1]
    ema21_val = ema21.iloc[-1] if not pd.isna(ema21.iloc[-1]) else close.iloc[-1]
    preco = close.iloc[-1]

    # ADX
    adx_df = ta.adx(high, low, close, length=14)
    adx_val = adx_df["ADX_14"].iloc[-1] if adx_df is not None and not pd.isna(adx_df["ADX_14"].iloc[-1]) else 20

    # CCI
    cci = ta.cci(high, low, close, length=20)
    cci_val = cci.iloc[-1] if not pd.isna(cci.iloc[-1]) else 0

    # Bollinger Bands
    bb = ta.bbands(close, length=20, std=2)
    bb_upper = bb["BBU_20_2.0"].iloc[-1] if "BBU_20_2.0" in bb.columns else preco
    bb_lower = bb["BBL_20_2.0"].iloc[-1] if "BBL_20_2.0" in bb.columns else preco
    bb_position = (preco - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) != 0 else 0.5

    # Estocástico
    stoch = ta.stoch(high, low, close, k=14, d=3)
    stoch_k = stoch["STOCHk_14_3_3"].iloc[-1] if stoch is not None and "STOCHk_14_3_3" in stoch.columns else 50

    # OBV
    obv = ta.obv(close, volume)
    obv_trend = 1 if len(obv) > 1 and obv.iloc[-1] > obv.iloc[-2] else 0

    # Aroon
    aroon = ta.aroon(high, low, length=25)
    aroon_up = aroon["AROONU_25"].iloc[-1] if aroon is not None and "AROONU_25" in aroon.columns else 50
    aroon_down = aroon["AROOND_25"].iloc[-1] if aroon is not None and "AROOND_25" in aroon.columns else 50
    aroon_strength = (aroon_up - aroon_down) / 100

    # Volume ratio
    vol_ma = volume.rolling(20).mean().iloc[-1] if len(volume) >= 20 else volume.iloc[-1]
    volume_ratio = volume.iloc[-1] / vol_ma if vol_ma > 0 else 1.0

    return {
        "rsi": rsi_val,
        "macd_hist": macd_hist,
        "price": preco,
        "ema9": ema9_val,
        "ema21": ema21_val,
        "adx": adx_val,
        "cci": cci_val,
        "bb_position": bb_position,
        "stoch_k": stoch_k,
        "obv_trend": obv_trend,
        "aroon_strength": aroon_strength,
        "volume_ratio": volume_ratio
    }

def compute_score_long(indicators: Dict[str, float]) -> float:
    weights = config.WEIGHTS_LONG
    if not indicators:
        return 0.0

    rsi = indicators["rsi"]
    score_rsi = 1.0 if rsi < 30 else (0.0 if rsi > 70 else (70 - rsi) / 40)

    macd_hist = indicators["macd_hist"]
    score_macd = min(1.0, max(0.0, (macd_hist + 0.5) / 1.0)) if macd_hist > -0.5 else 0.0

    preco = indicators["price"]
    ema9 = indicators["ema9"]
    ema21 = indicators["ema21"]
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

    obv_trend = indicators["obv_trend"]
    score_obv = obv_trend

    aroon_str = indicators["aroon_strength"]
    score_aroon = min(1.0, max(0.0, (aroon_str + 1) / 2))

    vol_ratio = indicators["volume_ratio"]

    score = (weights["rsi"] * score_rsi +
             weights["macd"] * score_macd +
             weights["ema"] * score_ema +
             weights["adx"] * score_adx +
             weights["cci"] * score_cci +
             weights["bbands"] * score_bb +
             weights["stoch"] * score_stoch +
             weights["obv"] * score_obv +
             weights["aroon"] * score_aroon)

    score = score * (0.9 + min(0.2, vol_ratio * 0.1))
    return round(min(1.0, score), 4)

def compute_score_short(indicators: Dict[str, float]) -> float:
    weights = config.WEIGHTS_SHORT
    if not indicators:
        return 0.0

    rsi = indicators["rsi"]
    score_rsi = 1.0 if rsi > 70 else (0.0 if rsi < 30 else (rsi - 30) / 40)

    macd_hist = indicators["macd_hist"]
    score_macd = min(1.0, max(0.0, (-macd_hist + 0.5) / 1.0)) if macd_hist < 0.5 else 0.0

    preco = indicators["price"]
    ema9 = indicators["ema9"]
    ema21 = indicators["ema21"]
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

    obv_trend = indicators["obv_trend"]
    score_obv = 1 - obv_trend

    aroon_str = indicators["aroon_strength"]
    score_aroon = min(1.0, max(0.0, (1 - (aroon_str + 1) / 2)))

    vol_ratio = indicators["volume_ratio"]

    score = (weights["rsi"] * score_rsi +
             weights["macd"] * score_macd +
             weights["ema"] * score_ema +
             weights["adx"] * score_adx +
             weights["cci"] * score_cci +
             weights["bbands"] * score_bb +
             weights["stoch"] * score_stoch +
             weights["obv"] * score_obv +
             weights["aroon"] * score_aroon)

    score = score * (0.9 + min(0.2, vol_ratio * 0.1))
    return round(min(1.0, score), 4)

# ============================================================
# 4. BACKTESTING
# ============================================================
def backtest_strategy(df_ohlc: pd.DataFrame) -> Dict:
    """Simples backtesting baseado nos scores gerados."""
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
        score_long = compute_score_long(ind)
        score_short = compute_score_short(ind)
        if score_long > 0.7:
            signals.append(1)
        elif score_short > 0.7:
            signals.append(-1)
        else:
            signals.append(0)

    prices = test_data["close"].values
    returns = []
    position = 0
    entry_price = 0
    capital = config.BACKTEST_INITIAL_CAPITAL

    for idx, sig in enumerate(signals):
        if idx >= len(prices)-1:
            break
        if sig == 1 and position == 0:
            position = 1
            entry_price = prices[idx]
        elif sig == -1 and position == 0:
            position = -1
            entry_price = prices[idx]
        elif sig == 0 and position != 0:
            exit_price = prices[idx]
            if position == 1:
                ret = (exit_price - entry_price) / entry_price
            else:
                ret = (entry_price - exit_price) / entry_price
            returns.append(ret)
            capital *= (1 + ret)
            position = 0

    if position != 0:
        exit_price = prices[-1]
        if position == 1:
            ret = (exit_price - entry_price) / entry_price
        else:
            ret = (entry_price - exit_price) / entry_price
        returns.append(ret)
        capital *= (1 + ret)

    total_return = (capital - config.BACKTEST_INITIAL_CAPITAL) / config.BACKTEST_INITIAL_CAPITAL
    win_rate = sum(1 for r in returns if r > 0) / len(returns) if returns else 0
    return {
        "total_return": total_return,
        "win_rate": win_rate,
        "trades": len(returns)
    }

# ============================================================
# 5. ANÁLISE INDIVIDUAL DE UMA MOEDA
# ============================================================
def analyze_coin(coin_row: pd.Series) -> Dict:
    """Analisa uma única moeda (síncrono, respeitando rate limit)."""
    coin_id = coin_row["coin_id"]
    symbol = coin_row["symbol"].upper()
    name = coin_row["name"]

    logger.info(f"Processando {name} ({symbol})")
    df_ohlc = fetch_ohlcv_coingecko(coin_id, days=config.HISTORICAL_DAYS)

    if df_ohlc is None:
        logger.warning(f"Sem dados históricos para {symbol}")
        return None

    indicators = calculate_indicators(df_ohlc)
    if not indicators:
        return None

    score_long = compute_score_long(indicators)
    score_short = compute_score_short(indicators)

    backtest_result = None
    if config.BACKTEST_ENABLED:
        backtest_result = backtest_strategy(df_ohlc)

    return {
        "symbol": symbol,
        "name": name,
        "price": coin_row["price"],
        "change_1h": coin_row["change_1h"],
        "change_24h": coin_row["change_24h"],
        "change_7d": coin_row["change_7d"],
        "volume_24h": coin_row["volume_24h"],
        "score_long": score_long,
        "score_short": score_short,
        "backtest": backtest_result
    }

# ============================================================
# 6. FUNÇÃO PRINCIPAL
# ============================================================
def main():
    logger.info("Iniciando análise avançada (apenas CoinGecko)...")
    df_coins = fetch_coin_list()
    if df_coins.empty:
        logger.error("Nenhuma moeda obtida.")
        return

    results = []
    total = len(df_coins)

    for idx, row in df_coins.iterrows():
        logger.info(f"Processando moeda {idx+1}/{total}: {row['symbol'].upper()}")
        result = analyze_coin(row)
        if result:
            results.append(result)
        # Pausa para respeitar rate limit (30/min na free)
        if not config.COINGECKO_API_KEY:
            time.sleep(2)

    if not results:
        logger.error("Nenhum resultado válido.")
        return

    df_long = pd.DataFrame(results).sort_values("score_long", ascending=False)
    df_short = pd.DataFrame(results).sort_values("score_short", ascending=False)

    # Exibir resultados
    print("\n" + "="*80)
    print("📈 TOP 10 PARA LONG (COMPRA) - MAIOR POTENCIAL DE ALTA")
    print("="*80)
    for i, row in df_long.head(10).iterrows():
        print(f"{i+1}. {row['symbol']} - {row['name']}")
        print(f"   Score Long: {row['score_long']:.4f} | Preço: ${row['price']:.4f}")
        print(f"   1h: {row['change_1h']:+.2f}% | 24h: {row['change_24h']:+.2f}% | 7d: {row['change_7d']:+.2f}%")
        print(f"   Volume 24h: ${row['volume_24h']:,.0f}")
        if row.get('backtest') and config.BACKTEST_ENABLED:
            bt = row['backtest']
            print(f"   Backtest (últimos {config.BACKTEST_TEST_DAYS}d): Retorno {bt['total_return']:.2%} | Win Rate {bt['win_rate']:.1%} | Trades {bt['trades']}")
        print()

    print("\n" + "="*80)
    print("📉 TOP 5 PARA SHORT (VENDA) - MAIOR POTENCIAL DE QUEDA")
    print("="*80)
    for i, row in df_short.head(5).iterrows():
        print(f"{i+1}. {row['symbol']} - {row['name']} (Score Short: {row['score_short']:.4f})")

    # Salvar CSV
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    df_long.to_csv(f"ranking_long_{timestamp}.csv", index=False)
    df_short.to_csv(f"ranking_short_{timestamp}.csv", index=False)
    logger.info(f"Resultados salvos em ranking_long_{timestamp}.csv e ranking_short_{timestamp}.csv")

    # Notificação do topo via Telegram
    top_long = df_long.iloc[0] if not df_long.empty else None
    if top_long is not None and config.TELEGRAM_ENABLED:
        msg = (f"🚀 <b>SINAL LONG DETECTADO</b>\n"
               f"Moeda: {top_long['symbol']} - {top_long['name']}\n"
               f"Score: {top_long['score_long']:.2f}\n"
               f"Preço: ${top_long['price']:.4f}\n"
               f"Variação 24h: {top_long['change_24h']:+.2f}%")
        send_telegram_message(msg)

if __name__ == "__main__":
    main()