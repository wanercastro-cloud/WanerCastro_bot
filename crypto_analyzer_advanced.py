#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Sistema Avançado de Análise de Criptomoedas
- CoinGecko: lista de moedas (evita stablecoins)
- Binance: dados OHLCV históricos e WebSocket em tempo real
- Múltiplos indicadores: RSI, MACD, EMA, ADX, CCI, Bollinger Bands, Stoch, OBV, Aroon
- Scoring para LONG e SHORT com pesos configuráveis
- Backtesting para validar estratégia
- Logging e notificações via Telegram
- Processamento assíncrono (rápido)
"""

import os
import sys
import json
import time
import logging
import asyncio
import aiohttp
import requests
import pandas as pd
import pandas_ta as ta
from datetime import datetime
from decimal import Decimal
from binance.client import Client
from binance.websockets import BinanceSocketManager
from typing import Dict, List, Optional, Tuple

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
# CONFIGURAÇÕES GLOBAIS (EDITAR CONFORME NECESSÁRIO)
# ============================================================
CONFIG = {
    "coin_gecko": {
        "api_key": "",  # Deixe vazio para usar a API gratuita sem chave (limite menor)
        "max_coins": 200,
        "vs_currency": "usd"
    },
    "binance": {
        "historical_days": 90,
        "interval": Client.KLINE_INTERVAL_1DAY,
        "use_websocket": False,  # Ativar apenas se quiser tempo real (consome mais recursos)
    },
    "scoring": {
        "weights_long": {
            "rsi": 0.15,
            "macd": 0.20,
            "ema": 0.20,
            "adx": 0.10,
            "cci": 0.10,
            "bbands": 0.10,
            "stoch": 0.05,
            "obv": 0.05,
            "aroon": 0.05
        },
        "weights_short": {
            "rsi": 0.15,
            "macd": 0.20,
            "ema": 0.20,
            "adx": 0.10,
            "cci": 0.10,
            "bbands": 0.10,
            "stoch": 0.05,
            "obv": 0.05,
            "aroon": 0.05
        }
    },
    "backtest": {
        "enabled": True,
        "test_days": 30,      # Período de teste após o treinamento
        "initial_capital": 10000
    },
    "notifications": {
        "telegram": {
            "enabled": False,
            "bot_token": "SEU_TOKEN",
            "chat_id": "SEU_CHAT_ID"
        }
    },
    "filters": {
        "stablecoins_symbols": ["usdc", "usdt", "dai", "busd", "tusd", "fdusd", "usdp", "lusd", "ustc", "usdd", "usde", "fdai", "cdai", "crvusd", "alusd", "mim", "fei", "frax", "lusd"],
        "stablecoins_names": ["tether", "usd coin", "binance usd", "dai stablecoin", "frax", "magic internet money"],
        "min_volume_usd": 500000,   # Volume mínimo 24h em USD
        "min_price_usd": 0.01
    }
}

# ============================================================
# UTILITÁRIOS
# ============================================================
def send_telegram_message(message: str):
    """Envia mensagem via bot do Telegram (se configurado)."""
    if not CONFIG["notifications"]["telegram"]["enabled"]:
        return
    token = CONFIG["notifications"]["telegram"]["bot_token"]
    chat_id = CONFIG["notifications"]["telegram"]["chat_id"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=5)
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem Telegram: {e}")

# ============================================================
# 1. BUSCAR LISTA DE MOEDAS (CoinGecko) - Síncrono (simples)
# ============================================================
def fetch_coin_list() -> pd.DataFrame:
    """
    Obtém lista das principais moedas da CoinGecko, aplica filtros.
    Retorna DataFrame com colunas: coin_id, symbol, name, price, change_1h, change_24h, change_7d, volume_24h.
    """
    headers = {}
    api_key = CONFIG["coin_gecko"]["api_key"]
    if api_key:
        headers["x-cg-demo-api-key"] = api_key

    all_coins = []
    page = 1
    per_page = 250
    max_coins = CONFIG["coin_gecko"]["max_coins"]

    while len(all_coins) < max_coins:
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {
            "vs_currency": CONFIG["coin_gecko"]["vs_currency"],
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
            time.sleep(0.5)  # Pequena pausa para evitar rate limit
        except Exception as e:
            logger.error(f"Erro ao buscar página {page} da CoinGecko: {e}")
            break

    if not all_coins:
        logger.error("Nenhuma moeda encontrada na CoinGecko.")
        return pd.DataFrame()

    df = pd.DataFrame(all_coins)
    # Filtros
    stable_symbols = CONFIG["filters"]["stablecoins_symbols"]
    stable_names = CONFIG["filters"]["stablecoins_names"]
    df = df[~df["symbol"].str.lower().isin(stable_symbols)]
    df = df[~df["name"].str.lower().str.contains("|".join(stable_names), na=False)]
    df = df[df["total_volume"] >= CONFIG["filters"]["min_volume_usd"]]
    df = df[df["current_price"] >= CONFIG["filters"]["min_price_usd"]]

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
# 2. BUSCAR DADOS HISTÓRICOS (Binance) - Assíncrono
# ============================================================
async def fetch_ohlcv_binance(session: aiohttp.ClientSession, symbol: str, days: int) -> Optional[pd.DataFrame]:
    """
    Busca dados OHLCV da Binance usando API REST (async).
    Retorna DataFrame com open, high, low, close, volume.
    """
    interval = CONFIG["binance"]["interval"]
    # Mapear intervalo para string da Binance
    interval_map = {
        Client.KLINE_INTERVAL_1DAY: "1d",
        Client.KLINE_INTERVAL_1HOUR: "1h",
        Client.KLINE_INTERVAL_15MINUTE: "15m"
    }
    interval_str = interval_map.get(interval, "1d")
    url = f"https://api.binance.com/api/v3/klines"
    params = {
        "symbol": symbol.upper(),
        "interval": interval_str,
        "limit": days + 1
    }
    try:
        async with session.get(url, params=params, timeout=15) as resp:
            if resp.status != 200:
                logger.warning(f"Erro {resp.status} para {symbol}")
                return None
            data = await resp.json()
            if not data:
                return None
            df = pd.DataFrame(data, columns=[
                "timestamp", "open", "high", "low", "close", "volume",
                "close_time", "quote_asset_volume", "number_of_trades",
                "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"
            ])
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)
            return df[["open", "high", "low", "close", "volume"]]
    except Exception as e:
        logger.error(f"Erro ao buscar {symbol}: {e}")
        return None

# ============================================================
# 3. CÁLCULO DE INDICADORES E SCORES (com mais indicadores)
# ============================================================
def calculate_indicators(df: pd.DataFrame) -> Dict[str, float]:
    """
    Calcula todos os indicadores para o último candle.
    Retorna dicionário com os valores finais (já normalizados para score).
    """
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

    # Bollinger Bands (largura e posição)
    bb = ta.bbands(close, length=20, std=2)
    bb_upper = bb["BBU_20_2.0"].iloc[-1] if "BBU_20_2.0" in bb.columns else preco
    bb_lower = bb["BBL_20_2.0"].iloc[-1] if "BBL_20_2.0" in bb.columns else preco
    bb_position = (preco - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) != 0 else 0.5
    bb_width = (bb_upper - bb_lower) / preco  # largura relativa

    # Estocástico (Stoch)
    stoch = ta.stoch(high, low, close, k=14, d=3)
    stoch_k = stoch["STOCHk_14_3_3"].iloc[-1] if stoch is not None and "STOCHk_14_3_3" in stoch.columns else 50
    stoch_d = stoch["STOCHd_14_3_3"].iloc[-1] if stoch is not None and "STOCHd_14_3_3" in stoch.columns else 50

    # On-Balance Volume (OBV) - tendência
    obv = ta.obv(close, volume)
    obv_trend = 1 if len(obv) > 1 and obv.iloc[-1] > obv.iloc[-2] else 0

    # Aroon (força da tendência)
    aroon = ta.aroon(high, low, length=25)
    aroon_up = aroon["AROONU_25"].iloc[-1] if aroon is not None and "AROONU_25" in aroon.columns else 50
    aroon_down = aroon["AROOND_25"].iloc[-1] if aroon is not None and "AROOND_25" in aroon.columns else 50
    aroon_strength = (aroon_up - aroon_down) / 100  # de -1 a 1

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
        "bb_width": bb_width,
        "stoch_k": stoch_k,
        "stoch_d": stoch_d,
        "obv_trend": obv_trend,
        "aroon_strength": aroon_strength,
        "volume_ratio": volume_ratio
    }

def compute_score_long(indicators: Dict[str, float], weights: Dict[str, float]) -> float:
    """
    Calcula score para LONG (0 a 1) com base nos indicadores.
    """
    if not indicators:
        return 0.0

    # RSI: quanto menor, melhor (sobrevendido)
    rsi = indicators["rsi"]
    score_rsi = 1.0 if rsi < 30 else (0.0 if rsi > 70 else (70 - rsi) / 40)

    # MACD: positivo bom
    macd_hist = indicators["macd_hist"]
    score_macd = min(1.0, max(0.0, (macd_hist + 0.5) / 1.0)) if macd_hist > -0.5 else 0.0

    # EMA: preço > EMA9 > EMA21
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

    # ADX: força da tendência (quanto maior, melhor para long se a direção for boa, mas usamos só força)
    adx = indicators["adx"]
    score_adx = min(1.0, max(0.0, (adx - 20) / 30))

    # CCI: acima de -100 é bom
    cci = indicators["cci"]
    score_cci = min(1.0, max(0.0, (cci + 100) / 200))

    # Bollinger Bands: posição próxima à banda inferior é bom para long (oversold)
    bb_pos = indicators["bb_position"]
    score_bb = 1.0 - bb_pos  # quanto mais perto de 0 (banda inferior), melhor

    # Estocástico: abaixo de 20 (sobrevendido) bom
    stoch_k = indicators["stoch_k"]
    score_stoch = 1.0 if stoch_k < 20 else (0.0 if stoch_k > 80 else (80 - stoch_k) / 60)

    # OBV: tendência positiva ajuda
    obv_trend = indicators["obv_trend"]
    score_obv = obv_trend

    # Aroon: AroonUp > AroonDown indica tendência de alta
    aroon_str = indicators["aroon_strength"]
    score_aroon = min(1.0, max(0.0, (aroon_str + 1) / 2))

    # Volume ratio: bônus multiplicativo (não incluso nos pesos)
    vol_ratio = indicators["volume_ratio"]

    # Score ponderado
    score = (weights["rsi"] * score_rsi +
             weights["macd"] * score_macd +
             weights["ema"] * score_ema +
             weights["adx"] * score_adx +
             weights["cci"] * score_cci +
             weights["bbands"] * score_bb +
             weights["stoch"] * score_stoch +
             weights["obv"] * score_obv +
             weights["aroon"] * score_aroon)

    # Ajuste por volume (até +20% se volume alto)
    score = score * (0.9 + min(0.2, vol_ratio * 0.1))
    return round(min(1.0, score), 4)

def compute_score_short(indicators: Dict[str, float], weights: Dict[str, float]) -> float:
    """
    Calcula score para SHORT (0 a 1) com base nos indicadores.
    """
    if not indicators:
        return 0.0

    # RSI: quanto maior, melhor (sobrecomprado)
    rsi = indicators["rsi"]
    score_rsi = 1.0 if rsi > 70 else (0.0 if rsi < 30 else (rsi - 30) / 40)

    # MACD: negativo bom
    macd_hist = indicators["macd_hist"]
    score_macd = min(1.0, max(0.0, (-macd_hist + 0.5) / 1.0)) if macd_hist < 0.5 else 0.0

    # EMA: preço < EMA9 < EMA21
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

    # ADX: força da tendência
    adx = indicators["adx"]
    score_adx = min(1.0, max(0.0, (adx - 20) / 30))

    # CCI: abaixo de +100 é bom (negativo)
    cci = indicators["cci"]
    score_cci = min(1.0, max(0.0, (100 - cci) / 200))

    # Bollinger Bands: posição próxima à banda superior bom para short
    bb_pos = indicators["bb_position"]
    score_bb = bb_pos

    # Estocástico: acima de 80 (sobrecomprado) bom
    stoch_k = indicators["stoch_k"]
    score_stoch = 1.0 if stoch_k > 80 else (0.0 if stoch_k < 20 else (stoch_k - 20) / 60)

    # OBV: tendência negativa ajuda
    obv_trend = indicators["obv_trend"]
    score_obv = 1 - obv_trend

    # Aroon: AroonDown > AroonUp
    aroon_str = indicators["aroon_strength"]
    score_aroon = min(1.0, max(0.0, (1 - (aroon_str + 1) / 2)))

    # Volume ratio bônus
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
# 4. BACKTESTING DA ESTRATÉGIA
# ============================================================
def backtest_strategy(df_ohlc: pd.DataFrame, weights_long: Dict, weights_short: Dict, lookback_days: int = 30) -> Dict:
    """
    Simula a estratégia nos dados históricos.
    Para cada dia (a partir do lookback), calcula o score e gera sinal.
    Retorna estatísticas: retorno total, sharpe, win rate.
    """
    if df_ohlc is None or len(df_ohlc) < lookback_days + 10:
        return {"total_return": 0, "sharpe": 0, "win_rate": 0, "trades": 0}

    # Usamos apenas os últimos 'test_days' para simular
    test_data = df_ohlc.iloc[-CONFIG["backtest"]["test_days"]:].copy()
    if len(test_data) < 10:
        return {"total_return": 0, "sharpe": 0, "win_rate": 0, "trades": 0}

    signals = []
    for i in range(lookback_days, len(test_data)):
        hist = test_data.iloc[:i]
        ind = calculate_indicators(hist)
        if not ind:
            continue
        score_long = compute_score_long(ind, weights_long)
        score_short = compute_score_short(ind, weights_short)
        if score_long > 0.7:
            signals.append(1)   # long
        elif score_short > 0.7:
            signals.append(-1)  # short
        else:
            signals.append(0)

    # Simular retornos
    prices = test_data["close"].values
    returns = []
    position = 0
    entry_price = 0
    capital = CONFIG["backtest"]["initial_capital"]
    equity = [capital]

    for idx, sig in enumerate(signals):
        if idx >= len(prices)-1:
            break
        if sig == 1 and position == 0:  # comprar
            position = 1
            entry_price = prices[idx]
        elif sig == -1 and position == 0:  # short
            position = -1
            entry_price = prices[idx]
        elif sig == 0 and position != 0:  # fechar posição
            exit_price = prices[idx]
            if position == 1:
                ret = (exit_price - entry_price) / entry_price
            else:
                ret = (entry_price - exit_price) / entry_price
            returns.append(ret)
            capital *= (1 + ret)
            equity.append(capital)
            position = 0

    if position != 0:  # fechar no final
        exit_price = prices[-1]
        if position == 1:
            ret = (exit_price - entry_price) / entry_price
        else:
            ret = (entry_price - exit_price) / entry_price
        returns.append(ret)
        capital *= (1 + ret)
        equity.append(capital)

    total_return = (capital - CONFIG["backtest"]["initial_capital"]) / CONFIG["backtest"]["initial_capital"]
    win_rate = sum(1 for r in returns if r > 0) / len(returns) if returns else 0
    sharpe = (pd.Series(returns).mean() / pd.Series(returns).std() * (252**0.5)) if len(returns) > 1 and pd.Series(returns).std() != 0 else 0
    return {
        "total_return": total_return,
        "sharpe": sharpe,
        "win_rate": win_rate,
        "trades": len(returns)
    }

# ============================================================
# 5. PROCESSAMENTO PRINCIPAL ASSÍNCRONO
# ============================================================
async def analyze_coin(session: aiohttp.ClientSession, coin_row: pd.Series) -> Dict:
    """
    Analisa uma única moeda: busca dados Binance, calcula indicadores e scores.
    """
    symbol = coin_row["symbol"].upper()
    binance_symbol = f"{symbol}USDT"
    days = CONFIG["binance"]["historical_days"]

    df_ohlc = await fetch_ohlcv_binance(session, binance_symbol, days)
    if df_ohlc is None:
        return None

    indicators = calculate_indicators(df_ohlc)
    if not indicators:
        return None

    weights_long = CONFIG["scoring"]["weights_long"]
    weights_short = CONFIG["scoring"]["weights_short"]
    score_long = compute_score_long(indicators, weights_long)
    score_short = compute_score_short(indicators, weights_short)

    # Backtest opcional
    backtest_result = None
    if CONFIG["backtest"]["enabled"]:
        backtest_result = backtest_strategy(df_ohlc, weights_long, weights_short)

    return {
        "symbol": symbol,
        "name": coin_row["name"],
        "price": coin_row["price"],
        "change_1h": coin_row["change_1h"],
        "change_24h": coin_row["change_24h"],
        "change_7d": coin_row["change_7d"],
        "volume_24h": coin_row["volume_24h"],
        "score_long": score_long,
        "score_short": score_short,
        "backtest": backtest_result
    }

async def main_async():
    logger.info("Iniciando análise avançada...")
    # 1. Buscar lista de moedas
    df_coins = fetch_coin_list()
    if df_coins.empty:
        logger.error("Nenhuma moeda obtida.")
        return

    # 2. Processar cada moeda assincronamente
    async with aiohttp.ClientSession() as session:
        tasks = []
        for _, row in df_coins.iterrows():
            tasks.append(analyze_coin(session, row))
        results = await asyncio.gather(*tasks, return_exceptions=True)

    # 3. Filtrar resultados válidos
    valid_results = [r for r in results if isinstance(r, dict) and r is not None]
    if not valid_results:
        logger.error("Nenhum resultado válido.")
        return

    # 4. Ordenar por score_long e score_short
    df_long = pd.DataFrame(valid_results).sort_values("score_long", ascending=False)
    df_short = pd.DataFrame(valid_results).sort_values("score_short", ascending=False)

    # 5. Exibir resultados
    print("\n" + "="*80)
    print("📈 TOP 10 PARA LONG (COMPRA) - MAIOR POTENCIAL DE ALTA")
    print("="*80)
    for i, row in df_long.head(10).iterrows():
        print(f"{i+1}. {row['symbol']} - {row['name']}")
        print(f"   Score Long: {row['score_long']:.4f} | Preço: ${row['price']:.4f}")
        print(f"   1h: {row['change_1h']:+.2f}% | 24h: {row['change_24h']:+.2f}% | 7d: {row['change_7d']:+.2f}%")
        print(f"   Volume 24h: ${row['volume_24h']:,.0f}")
        if row.get('backtest') and CONFIG["backtest"]["enabled"]:
            bt = row['backtest']
            print(f"   Backtest (últimos {CONFIG['backtest']['test_days']}d): Retorno {bt['total_return']:.2%} | Win Rate {bt['win_rate']:.1%} | Trades {bt['trades']}")
        print()

    print("\n" + "="*80)
    print("📉 TOP 5 PARA SHORT (VENDA) - MAIOR POTENCIAL DE QUEDA")
    print("="*80)
    for i, row in df_short.head(5).iterrows():
        print(f"{i+1}. {row['symbol']} - {row['name']} (Score Short: {row['score_short']:.4f})")

    # 6. Salvar CSV
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    df_long.to_csv(f"ranking_long_{timestamp}.csv", index=False)
    df_short.to_csv(f"ranking_short_{timestamp}.csv", index=False)
    logger.info(f"Resultados salvos em ranking_long_{timestamp}.csv e ranking_short_{timestamp}.csv")

    # 7. Notificações (opcional)
    top_long = df_long.iloc[0] if not df_long.empty else None
    if top_long is not None:
        msg = f"🚀 SINAL LONG: {top_long['symbol']} - Score {top_long['score_long']:.2f} | Preço ${top_long['price']:.4f}"
        send_telegram_message(msg)

def run():
    asyncio.run(main_async())

if __name__ == "__main__":
    run()