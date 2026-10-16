# api/index.py
from flask import Flask, request
import os
import io
import requests
import yfinance as yf
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Backend não-interativo (obrigatório para Vercel)
import matplotlib.pyplot as plt

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


# ---------- Funções de envio para o Telegram ----------

def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    requests.post(f"{TELEGRAM_API}/sendMessage", json=payload)


def send_photo(chat_id, photo_bytes, caption=""):
    files = {"photo": ("grafico.png", photo_bytes, "image/png")}
    data = {"chat_id": chat_id, "caption": caption, "parse_mode": "Markdown"}
    requests.post(f"{TELEGRAM_API}/sendPhoto", data=data, files=files)


def answer_callback(callback_id):
    requests.post(f"{TELEGRAM_API}/answerCallbackQuery", json={"callback_query_id": callback_id})


# ---------- Teclado com botões ----------

def teclado_principal():
    return {
        "inline_keyboard": [
            [
                {"text": "📊 Analisar", "callback_data": "analisar"},
                {"text": "📈 Gráfico", "callback_data": "grafico"},
            ],
            [
                {"text": "❓ Ajuda", "callback_data": "ajuda"},
            ],
        ]
    }


# ---------- Lógica de análise ----------

def obter_dados():
    """Devolve o DataFrame do EUR/USD M15 já tratado, ou None se falhar."""
    data = yf.download("EURUSD=X", period="5d", interval="15m", progress=False)
    if data.empty:
        return None
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    data['Close'] = pd.to_numeric(data['Close'], errors='coerce')
    data = data.dropna(subset=['Close'])
    if data.empty:
        return None
    data['EMA9'] = data['Close'].ewm(span=9, adjust=False).mean()
    data['EMA21'] = data['Close'].ewm(span=21, adjust=False).mean()
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    data['RSI'] = 100 - (100 / (1 + rs))
    return data


def calcular_sinal(data):
    """Devolve (sinal, preco, ema9, ema21, rsi). sinal = 'COMPRA'|'VENDA'|'NEUTRO'."""
    preco = float(data['Close'].iloc[-1])
    ema9 = float(data['EMA9'].iloc[-1])
    ema21 = float(data['EMA21'].iloc[-1])
    rsi = float(data['RSI'].iloc[-1])

    sinal = "NEUTRO"
    if ema9 > ema21 and rsi > 50:
        sinal = "COMPRA"
    elif ema9 < ema21 and rsi < 50:
        sinal = "VENDA"
    return sinal, preco, ema9, ema21, rsi


def texto_analise(sinal, preco, ema9, ema21, rsi):
    if sinal == "COMPRA":
        emoji = "🟢⬆️ *SINAL DE COMPRA*"
    elif sinal == "VENDA":
        emoji = "🔴⬇️ *SINAL DE VENDA*"
    else:
        emoji = "⚪ *NEUTRO* (sem sinal claro)"

    return (
        f"📊 *Análise EUR/USD (M15)*\n\n"
        f"{emoji}\n\n"
        f"💵 Preço: `{preco:.4f}`\n"
        f"📈 EMA 9: `{ema9:.4f}`\n"
        f"📉 EMA 21: `{ema21:.4f}`\n"
        f"⚡ RSI (14): `{rsi:.2f}`\n\n"
        f"⚠️ _Análise automática. Não é aconselhamento financeiro._"
    )


# ---------- Gerar gráfico ----------

def gerar_grafico(data, sinal):
    """Devolve bytes de uma imagem PNG com o gráfico e a seta."""
    ultimos = data.tail(60).copy()

    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=110)
    fig.patch.set_facecolor('#0e1621')
    ax.set_facecolor('#0e1621')

    x = range(len(ultimos))
    ax.plot(x, ultimos['Close'].values, color='#4da3ff', linewidth=1.8, label='Preço')
    ax.plot(x, ultimos['EMA9'].values, color='#00e676', linewidth=1.2, label='EMA 9')
    ax.plot(x, ultimos['EMA21'].values, color='#ff5252', linewidth=1.2, label='EMA 21')

    # Seta grande de compra/venda
    ultimo_x = len(ultimos) - 1
    ultimo_y = float(ultimos['Close'].iloc[-1])

    if sinal == "COMPRA":
        ax.annotate('', xy=(ultimo_x, ultimo_y * 1.0006),
                    xytext=(ultimo_x, ultimo_y * 0.9994),
                    arrowprops=dict(facecolor='#00e676', edgecolor='#00e676',
                                    width=6, headwidth=18, headlength=14))
        ax.text(0.02, 0.95, 'COMPRA', color='#00e676', fontsize=16,
                fontweight='bold', transform=ax.transAxes, va='top')
    elif sinal == "VENDA":
        ax.annotate('', xy=(ultimo_x, ultimo_y * 0.9994),
                    xytext=(ultimo_x, ultimo_y * 1.0006),
                    arrowprops=dict(facecolor='#ff5252', edgecolor='#ff5252',
                                    width=6, headwidth=18, headlength=14))
        ax.text(0.02, 0.95, 'VENDA', color='#ff5252', fontsize=16,
                fontweight='bold', transform=ax.transAxes, va='top')
    else:
        ax.text(0.02, 0.95, 'NEUTRO', color='#cccccc', fontsize=16,
                fontweight='bold', transform=ax.transAxes, va='top')

    ax.set_title('EUR/USD — M15', color='white', fontsize=13, pad=10)
    ax.tick_params(colors='#aaaaaa', labelsize=8)
    for spine in ax.spines.values():
        spine.set_color('#2a3a4a')
    ax.grid(True, alpha=0.15, color='#8899aa')
    legend = ax.legend(loc='lower right', fontsize=8, facecolor='#1a2433', edgecolor='#2a3a4a')
    for t in legend.get_texts():
        t.set_color('white')

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


# ---------- Ações ----------

def acao_analisar(chat_id):
    data = obter_dados()
    if data is None:
        send_message(chat_id, "❌ Não consegui obter dados do EUR/USD. Tenta novamente mais tarde.")
        return
    sinal, preco, ema9, ema21, rsi = calcular_sinal(data)
    send_message(chat_id, texto_analise(sinal, preco, ema9, ema21, rsi), teclado_principal())


def acao_grafico(chat_id):
    data = obter_dados()
    if data is None:
        send_message(chat_id, "❌ Não consegui obter dados do EUR/USD.")
        return
    sinal, preco, ema9, ema21, rsi = calcular_sinal(data)
    img = gerar_grafico(data, sinal)
    emoji = {"COMPRA": "🟢⬆️", "VENDA": "🔴⬇️", "NEUTRO": "⚪"}[sinal]
    caption = f"{emoji} *{sinal}* | Preço: `{preco:.4f}` | RSI: `{rsi:.1f}`"
    send_photo(chat_id, img, caption=caption)


def acao_ajuda(chat_id):
    texto = (
        "🤖 *Bot de Trading EUR/USD*\n\n"
        "Usa os botões abaixo ou os comandos:\n"
        "• `/analise` — Análise técnica + sinal\n"
        "• `/grafico` — Gráfico visual com seta\n"
        "• `/ajuda` — Esta mensagem\n\n"
        "⚠️ _Ferramenta educacional. Não é aconselhamento financeiro._"
    )
    send_message(chat_id, texto, teclado_principal())


# ---------- Endpoints ----------

@app.route('/api/index', methods=['POST'])
def webhook():
    update = request.get_json()

    # Cliques nos botões
    if "callback_query" in update:
        cq = update["callback_query"]
        chat_id = cq["message"]["chat"]["id"]
        data_btn = cq["data"]
        answer_callback(cq["id"])

        if data_btn == "analisar":
            acao_analisar(chat_id)
        elif data_btn == "grafico":
            acao_grafico(chat_id)
        elif data_btn == "ajuda":
            acao_ajuda(chat_id)

    # Mensagens de texto
    elif "message" in update and "text" in update["message"]:
        chat_id = update["message"]["chat"]["id"]
        texto = update["message"]["text"].strip().lower()

        if texto in ("/start", "ola", "olá", "oi"):
            send_message(
                chat_id,
                "👋 Olá! Sou o teu bot de trading de EUR/USD.\nUsa os botões abaixo para começar:",
                teclado_principal(),
            )
        elif texto in ("/analise", "analise", "analisar"):
            acao_analisar(chat_id)
        elif texto in ("/grafico", "grafico", "gráfico"):
            acao_grafico(chat_id)
        elif texto in ("/ajuda", "ajuda", "help"):
            acao_ajuda(chat_id)
        else:
            send_message(
                chat_id,
                "Não reconheci esse comando. Usa os botões abaixo 👇",
                teclado_principal(),
            )

    return "OK", 200