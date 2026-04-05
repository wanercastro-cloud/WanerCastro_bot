#!/usr/bin/env python3
# bot.py - Ponto de entrada principal

import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from crypto_analyzer_advanced import main

if __name__ == "__main__":
    print("🚀 Iniciando Crypto Analyzer Bot (apenas CoinGecko)...\n")
    main()