#!/usr/bin/env python3
# bot.py - Ponto de entrada principal

import sys
import os

# Adiciona diretório atual ao path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Importa e executa o módulo principal
from crypto_analyzer_advanced import run

if __name__ == "__main__":
    print("🚀 Iniciando Crypto Analyzer Bot...\n")
    run()