# api/index.py
from flask import Flask, request
import os
import requests
import yfinance as yf
import pandas as pd

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    requests.post(url, json=payload)

def analisar_eurusd():
    """Busca dados do EURUSD e calcula indicadores simples."""
    try:
        # Busca os últimos candles de 15 minutos (5 dias para garantir dados suficientes)
        data = yf.download("EURUSD=X", period="5d", interval="15m", progress=False)
        
        if data.empty:
            return "Não consegui obter dados do EUR/USD. Tenta novamente mais tarde."

        # Se as colunas forem MultiIndex, "achata-as"
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        # Garante que a coluna Close é numérica e remove valores inválidos
        data['Close'] = pd.to_numeric(data['Close'], errors='coerce')
        data = data.dropna(subset=['Close'])

        # Calcula a Média Móvel Exponencial (EMA) de 9 e 21 períodos
        data['EMA9'] = data['Close'].ewm(span=9, adjust=False).mean()
        data['EMA21'] = data['Close'].ewm(span=21, adjust=False).mean()

        # Calcula o RSI de 14 períodos
        delta = data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        data['RSI'] = 100 - (100 / (1 + rs))

        # Pega nos valores mais recentes e força-os a serem números (float)
        ultimo_preco = float(data['Close'].iloc[-1])
        ultima_ema9 = float(data['EMA9'].iloc[-1])
        ultima_ema21 = float(data['EMA21'].iloc[-1])
        ultimo_rsi = float(data['RSI'].iloc[-1])

        # Lógica de decisão simples
        sinal = "NEUTRO ⚪"
        if ultima_ema9 > ultima_ema21 and ultimo_rsi > 50:
            sinal = "COMPRA 🟢 (Tendência de alta com momentum)"
        elif ultima_ema9 < ultima_ema21 and ultimo_rsi < 50:
            sinal = "VENDA 🔴 (Tendência de baixa com momentum)"

        # Formata a resposta
        resposta = (
            f"📊 Análise EUR/USD (M15)\n\n"
            f"Preço atual: {ultimo_preco:.4f}\n"
            f"EMA 9: {ultima_ema9:.4f}\n"
            f"EMA 21: {ultima_ema21:.4f}\n"
            f"RSI (14): {ultimo_rsi:.2f}\n\n"
            f"Sinal: {sinal}"
        )
        return resposta

    except Exception as e:
        return f"Erro ao analisar o mercado: {str(e)}"

@app.route('/api/index', methods=['POST'])
def webhook():
    """Este endpoint recebe as atualizações do Telegram."""
    update = request.get_json()
    
    if "message" in update and "text" in update["message"]:
        chat_id = update["message"]["chat"]["id"]
        user_text = update["message"]["text"].lower()
        
        if user_text == "/start" or user_text == "ola" or user_text == "olá":
            send_telegram_message(chat_id, "Olá! Sou o teu bot de trading. Envia /analise para receber uma análise do EUR/USD.")
        elif user_text == "/analise" or user_text == "analise":
            send_telegram_message(chat_id, "A analisar o mercado... ⏳")
            resultado = analisar_eurusd()
            send_telegram_message(chat_id, resultado)
        else:
            send_telegram_message(chat_id, "Comando não reconhecido. Envia /analise para analisar o EUR/USD.")
    
    return "OK", 200