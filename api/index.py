# api/index.py
from flask import Flask, request
import os
import requests

app = Flask(__name__)

# O token do teu bot (será configurado como variável de ambiente no Vercel)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")

# Função simples que responde a uma mensagem
def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    requests.post(url, json=payload)

@app.route('/api/index', methods=['POST'])
def webhook():
    """Este endpoint recebe as atualizações do Telegram."""
    update = request.get_json()
    
    # Lógica para processar a mensagem
    if "message" in update and "text" in update["message"]:
        chat_id = update["message"]["chat"]["id"]
        user_text = update["message"]["text"]
        
        # Aqui é onde a tua lógica de análise de EURUSD entraria
        # Por agora, apenas responde com um eco
        response_text = f"Recebi a tua mensagem: '{user_text}'. A processar análise de EURUSD..."
        send_telegram_message(chat_id, response_text)
    
    return "OK", 200