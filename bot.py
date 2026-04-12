#!/usr/bin/env python3
# bot.py - Ponto de entrada

import config
config.validate()

from crypto_analyzer_advanced import main

if __name__ == "__main__":
    print("🚀 Crypto Analyzer Bot (CoinGecko Pro API)\n")
    main()
