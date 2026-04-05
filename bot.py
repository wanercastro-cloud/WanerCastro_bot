import requests
import logging
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

def send_telegram(message: str) -> bool:
    """
    Envia uma mensagem para o chat/grupo do Telegram configurado.
    
    Args:
        message: Texto da mensagem (pode conter HTML simples)
    
    Returns:
        True se enviado com sucesso, False caso contrário.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Token ou Chat ID do Telegram não configurados")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            logger.info("Mensagem enviada ao Telegram")
            return True
        else:
            logger.error(f"Telegram respondeu com {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Falha ao enviar mensagem para o Telegram: {e}")
        return False