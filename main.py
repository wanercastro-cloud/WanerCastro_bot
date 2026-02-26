*** a/main.py
--- b/main.py
***************
*** 1,16 ****
  import os
  import math
  import time
  import asyncio
  from dataclasses import dataclass
  from typing import Any, Dict, List, Optional, Tuple
  
  import httpx
  from dotenv import load_dotenv
  
  from telegram import Update
  from telegram.constants import ParseMode
  from telegram.ext import Application, CommandHandler, ContextTypes
***************
*** 39,63 ****
  TOP_N = int(os.getenv("TOP_N", "5"))
  CANDIDATES = int(os.getenv("CANDIDATES", "120"))  # quantos ativos avaliar antes do ranking final
  VS_CURRENCY = os.getenv("VS_CURRENCY", "usd").strip().lower()
  
  # Filtros (ajuste se quiser)
  MIN_MCAP = float(os.getenv("MIN_MCAP", "2000000"))       # 2M
  MAX_MCAP = float(os.getenv("MAX_MCAP", "250000000"))     # 250M (micro/low caps)
  MIN_VOL24 = float(os.getenv("MIN_VOL24", "1500000"))     # 1.5M
  EXCLUDE_STABLES = os.getenv("EXCLUDE_STABLES", "1").strip() == "1"
  
  HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "20"))
  HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "2"))
  
  if not TG_BOT_TOKEN:
      raise RuntimeError("❌ Variável TG_BOT_TOKEN não definida.")
--- 39,80 ----
  TOP_N = int(os.getenv("TOP_N", "5"))
  CANDIDATES = int(os.getenv("CANDIDATES", "120"))  # quantos ativos avaliar antes do ranking final
  VS_CURRENCY = os.getenv("VS_CURRENCY", "usd").strip().lower()
  
  # Filtros (ajuste se quiser)
  MIN_MCAP = float(os.getenv("MIN_MCAP", "2000000"))       # 2M
  MAX_MCAP = float(os.getenv("MAX_MCAP", "250000000"))     # 250M (micro/low caps)
  MIN_VOL24 = float(os.getenv("MIN_VOL24", "1500000"))     # 1.5M
  EXCLUDE_STABLES = os.getenv("EXCLUDE_STABLES", "1").strip() == "1"
  
+ # Anti-FOMO / "pré-pump" guardrails
+ # Se 24h estiver acima disso, entra na lista "já pumpou" (não concorre ao Top pré-pump)
+ MAX_24H_PREPUMP = float(os.getenv("MAX_24H_PREPUMP", "120"))  # %
+ # Penalidade máxima aplicada quando overheat=1 (aumente se ainda aparecer coin esticada no Top)
+ OVERHEAT_MAX_PENALTY = float(os.getenv("OVERHEAT_MAX_PENALTY", "65"))  # pontos
+ # (Opcional) penaliza também quando 1h está absurdo (spike tardio)
+ MAX_1H_PREPUMP = float(os.getenv("MAX_1H_PREPUMP", "35"))  # %
+ 
  HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "20"))
  HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "2"))
  
  if not TG_BOT_TOKEN:
      raise RuntimeError("❌ Variável TG_BOT_TOKEN não definida.")
***************
*** 132,183 ****
  def compute_score(
      mcap: float,
      vol24: float,
      chg_1h: float,
      chg_24h: float,
      dex_boost: float = 0.0
  ) -> Tuple[float, str]:
      """
      Score = Liquidez/atenção (vol/mcap) + aceleração (1h vs 24h) + momentum + ajuste DEX.
      """
      # 1) "Smart money attention": volume relativo à mcap
      vm = safe_div(vol24, mcap)  # ex: 0.5 = vol = 50% da mcap
      vm_n = clamp(vm / 1.2, 0.0, 1.2)  # normaliza
  
      # 2) aceleração: 1h positivo e 24h ainda não “esticado demais”
      # (muito 24h e pouco 1h = possivel exaustão)
      accel = (chg_1h - (chg_24h / 24.0))
      accel_n = clamp(accel / 2.5, -0.6, 1.2)
  
      # 3) momentum curto: 1h e 24h
      mom1 = clamp(chg_1h / 6.0, -0.8, 1.3)
      mom24 = clamp(chg_24h / 18.0, -0.8, 1.3)
  
      # 4) penaliza 24h extremamente alto (já “pumped”)
      overheat_penalty = clamp((chg_24h - 35.0) / 30.0, 0.0, 1.0)
  
      # 5) compõe
      raw = (
          45.0 * vm_n +
          20.0 * accel_n +
          20.0 * mom1 +
          15.0 * mom24 +
          10.0 * dex_boost
      )
      score = clamp(raw - 18.0 * overheat_penalty, 0.0, 100.0)
  
      notes = f"vm={vm:.2f} accel={accel:.2f} dex={dex_boost:.2f} overheat={overheat_penalty:.2f}"
      return score, notes
--- 149,224 ----
  def compute_score(
      mcap: float,
      vol24: float,
      chg_1h: float,
      chg_24h: float,
      dex_boost: float = 0.0
  ) -> Tuple[float, str]:
      """
      Score = Liquidez/atenção (vol/mcap) + aceleração (1h vs 24h) + momentum + ajuste DEX.
      Com guardrails anti-FOMO (24h/1h muito esticados).
      """
      # 1) "Smart money attention": volume relativo à mcap
      vm = safe_div(vol24, mcap)  # ex: 0.5 = vol = 50% da mcap
      vm_n = clamp(vm / 1.2, 0.0, 1.2)  # normaliza
  
      # 2) aceleração: 1h positivo e 24h ainda não “esticado demais”
      accel = (chg_1h - (chg_24h / 24.0))
      accel_n = clamp(accel / 2.5, -0.6, 1.2)
  
      # 3) momentum curto: 1h e 24h
      mom1 = clamp(chg_1h / 6.0, -0.8, 1.3)
      mom24 = clamp(chg_24h / 18.0, -0.8, 1.3)
  
      # 4) penaliza 24h extremamente alto (já “pumped”)
      overheat_penalty = clamp((chg_24h - 35.0) / 30.0, 0.0, 1.0)
  
+     # 4b) penaliza spike tardio de 1h (evita pegar topo de vela)
+     spike1h_penalty = clamp((max(chg_1h, 0.0) - 12.0) / 18.0, 0.0, 1.0)
+ 
      # 5) compõe
      raw = (
          45.0 * vm_n +
          20.0 * accel_n +
          20.0 * mom1 +
          15.0 * mom24 +
          10.0 * dex_boost
      )
-     score = clamp(raw - 18.0 * overheat_penalty, 0.0, 100.0)
+     score = clamp(
+         raw
+         - OVERHEAT_MAX_PENALTY * overheat_penalty
+         - 22.0 * spike1h_penalty,
+         0.0,
+         100.0
+     )
  
-     notes = f"vm={vm:.2f} accel={accel:.2f} dex={dex_boost:.2f} overheat={overheat_penalty:.2f}"
+     notes = (
+         f"vm={vm:.2f} accel={accel:.2f} dex={dex_boost:.2f} "
+         f"overheat={overheat_penalty:.2f} spike1h={spike1h_penalty:.2f}"
+     )
      return score, notes
***************
*** 185,231 ****
  async def build_ranking(client: httpx.AsyncClient) -> List[CandidateScore]:
      markets = await cg_markets(client)
      dex_boost_map = await dex_trending_signal(client)
  
      candidates: List[CandidateScore] = []
  
      for c in markets:
          try:
              symbol = (c.get("symbol") or "").upper().strip()
              name = (c.get("name") or "").strip()
              cg_id = (c.get("id") or "").strip()
  
              price = float(c.get("current_price") or 0.0)
              mcap = float(c.get("market_cap") or 0.0)
              vol24 = float(c.get("total_volume") or 0.0)
  
              chg_1h = float((c.get("price_change_percentage_1h_in_currency") or 0.0) or 0.0)
              chg_24h = float((c.get("price_change_percentage_24h_in_currency") or 0.0) or 0.0)
  
              if not symbol or not cg_id:
                  continue
  
              if EXCLUDE_STABLES and is_stable_like(symbol):
                  continue
  
              if mcap < MIN_MCAP or mcap > MAX_MCAP:
                  continue
  
              if vol24 < MIN_VOL24:
                  continue
  
              dex_boost = float(dex_boost_map.get(symbol, 0.0))
  
              score, notes = compute_score(mcap, vol24, chg_1h, chg_24h, dex_boost=dex_boost)
  
              candidates.append(
                  CandidateScore(
                      symbol=symbol,
                      name=name,
                      cg_id=cg_id,
                      price=price,
                      mcap=mcap,
                      vol24=vol24,
                      chg_1h=chg_1h,
                      chg_24h=chg_24h,
                      score=score,
                      notes=notes,
                  )
              )
          except Exception:
              continue
  
      # Ordena por score
      candidates.sort(key=lambda x: x.score, reverse=True)
      return candidates[:max(TOP_N, 1)]
--- 226,320 ----
+ @dataclass
+ class RankingResult:
+     prepump: List[CandidateScore]
+     pumped: List[CandidateScore]
+ 
+ 
+ async def build_ranking(client: httpx.AsyncClient) -> RankingResult:
      markets = await cg_markets(client)
      dex_boost_map = await dex_trending_signal(client)
  
      candidates: List[CandidateScore] = []
+     pumped: List[CandidateScore] = []
  
      for c in markets:
          try:
              symbol = (c.get("symbol") or "").upper().strip()
              name = (c.get("name") or "").strip()
              cg_id = (c.get("id") or "").strip()
  
              price = float(c.get("current_price") or 0.0)
              mcap = float(c.get("market_cap") or 0.0)
              vol24 = float(c.get("total_volume") or 0.0)
  
              chg_1h = float((c.get("price_change_percentage_1h_in_currency") or 0.0) or 0.0)
              chg_24h = float((c.get("price_change_percentage_24h_in_currency") or 0.0) or 0.0)
  
              if not symbol or not cg_id:
                  continue
  
              if EXCLUDE_STABLES and is_stable_like(symbol):
                  continue
  
              if mcap < MIN_MCAP or mcap > MAX_MCAP:
                  continue
  
              if vol24 < MIN_VOL24:
                  continue
  
              dex_boost = float(dex_boost_map.get(symbol, 0.0))
              score, notes = compute_score(mcap, vol24, chg_1h, chg_24h, dex_boost=dex_boost)
  
+             item = CandidateScore(
+                 symbol=symbol,
+                 name=name,
+                 cg_id=cg_id,
+                 price=price,
+                 mcap=mcap,
+                 vol24=vol24,
+                 chg_1h=chg_1h,
+                 chg_24h=chg_24h,
+                 score=score,
+                 notes=notes,
+             )
+ 
+             # Guardrail: se já “esticou demais”, joga pra lista separada (não concorre no pré-pump)
+             if chg_24h >= MAX_24H_PREPUMP or max(chg_1h, 0.0) >= MAX_1H_PREPUMP:
+                 pumped.append(item)
+                 continue
+ 
+             candidates.append(item)
-             candidates.append(
-                 CandidateScore(
-                     symbol=symbol,
-                     name=name,
-                     cg_id=cg_id,
-                     price=price,
-                     mcap=mcap,
-                     vol24=vol24,
-                     chg_1h=chg_1h,
-                     chg_24h=chg_24h,
-                     score=score,
-                     notes=notes,
-                 )
-             )
          except Exception:
              continue
  
      # Ordena por score
      candidates.sort(key=lambda x: x.score, reverse=True)
-     return candidates[:max(TOP_N, 1)]
+     pumped.sort(key=lambda x: (x.chg_24h, x.vol24), reverse=True)
+ 
+     return RankingResult(
+         prepump=candidates[:max(TOP_N, 1)],
+         pumped=pumped[:min(5, max(TOP_N, 1))],
+     )
***************
*** 244,276 ****
  def format_top_message(items: List[CandidateScore]) -> str:
      if not items:
          return "⚠️ Sem candidatos no filtro atual (ajuste MIN_MCAP / MAX_MCAP / MIN_VOL24)."
  
      lines = [f"🔥 <b>SMART MONEY PRÉ-PUMP</b> (Top {len(items)})"]
      for i, it in enumerate(items, 1):
          lines.append(
              f"\n<b>{i}) {it.symbol}/{VS_CURRENCY.upper()}</b> | <b>Score {it.score:.1f}</b>\n"
              f"• Mcap: {fmt_money(it.mcap)} | Vol24: {fmt_money(it.vol24)}\n"
              f"• 1h: {it.chg_1h:+.2f}% | 24h: {it.chg_24h:+.2f}%"
          )
      return "\n".join(lines)
--- 333,392 ----
+ def format_pumped_message(items: List[CandidateScore]) -> str:
+     if not items:
+         return ""
+     lines = [f"\n\n⚠️ <b>JÁ PUMPOU (evitar FOMO)</b> (Top {len(items)})"]
+     for i, it in enumerate(items, 1):
+         lines.append(
+             f"\n<b>{i}) {it.symbol}/{VS_CURRENCY.upper()}</b>\n"
+             f"• Mcap: {fmt_money(it.mcap)} | Vol24: {fmt_money(it.vol24)}\n"
+             f"• 1h: {it.chg_1h:+.2f}% | 24h: {it.chg_24h:+.2f}%"
+         )
+     return "\n".join(lines)
+ 
+ 
  def format_top_message(items: List[CandidateScore]) -> str:
      if not items:
          return "⚠️ Sem candidatos no filtro atual (ajuste MIN_MCAP / MAX_MCAP / MIN_VOL24)."
  
      lines = [f"🔥 <b>SMART MONEY PRÉ-PUMP</b> (Top {len(items)})"]
      for i, it in enumerate(items, 1):
          lines.append(
              f"\n<b>{i}) {it.symbol}/{VS_CURRENCY.upper()}</b> | <b>Score {it.score:.1f}</b>\n"
              f"• Mcap: {fmt_money(it.mcap)} | Vol24: {fmt_money(it.vol24)}\n"
              f"• 1h: {it.chg_1h:+.2f}% | 24h: {it.chg_24h:+.2f}%"
          )
      return "\n".join(lines)
***************
*** 314,340 ****
  async def cmd_smartmoney(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
      await update.message.reply_text("🔎 Rodando scanner CoinGecko (pré-pump)...")
  
      client: httpx.AsyncClient = context.application.bot_data["http"]
  
      try:
          # opcional: tenta ler top_gainers_losers (premium). Se não tiver acesso, ignora.
          _ = await cg_top_gainers_losers(client)
  
-         top = await build_ranking(client)
-         msg = format_top_message(top)
+         res = await build_ranking(client)
+         msg = format_top_message(res.prepump) + format_pumped_message(res.pumped)
          await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
      except httpx.HTTPStatusError as e:
          await update.message.reply_text(
              f"⚠️ Erro no CoinGecko: {e.response.status_code} {e.response.reason_phrase}\n"
              f"URL: {str(e.request.url)}"
          )
      except Exception as e:
          await update.message.reply_text(f"⚠️ Erro no scanner: {type(e).__name__}: {e}")