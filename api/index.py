# api/index.py
from flask import Flask, request
import os
import io
import requests
import yfinance as yf
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ---------- Configuração de pares e timeframes ----------

PARES = {
    "EURUSD": {"symbol": "EURUSD=X", "nome": "EUR/USD", "dec": 4},
    "GBPUSD": {"symbol": "GBPUSD=X", "nome": "GBP/USD", "dec": 4},
    "USDJPY": {"symbol": "USDJPY=X", "nome": "USD/JPY", "dec": 2},
    "AUDUSD": {"symbol": "AUDUSD=X", "nome": "AUD/USD", "dec": 4},
    "XAUUSD": {"symbol": "GC=F",     "nome": "Ouro (XAU/USD)", "dec": 2},
    "BTCUSD": {"symbol": "BTC-USD",  "nome": "BTC/USD", "dec": 0},
}

TIMEFRAMES = {
    "M5":  {"interval": "5m",  "period": "5d",  "label": "M5"},
    "M15": {"interval": "15m", "period": "5d",  "label": "M15"},
    "M30": {"interval": "30m", "period": "1mo", "label": "M30"},
    "H1":  {"interval": "1h",  "period": "1mo", "label": "H1"},
    "H4":  {"interval": "1h",  "period": "3mo", "resample": "4h", "label": "H4"},
    "D1":  {"interval": "1d",  "period": "1y",  "label": "D1"},
}


# ---------- Funções de envio para o Telegram ----------

def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    requests.post(f"{TELEGRAM_API}/sendMessage", json=payload)


def edit_message(chat_id, message_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    requests.post(f"{TELEGRAM_API}/editMessageText", json=payload)


def send_photo(chat_id, photo_bytes, caption=""):
    files = {"photo": ("grafico.png", photo_bytes, "image/png")}
    data = {"chat_id": chat_id, "caption": caption, "parse_mode": "Markdown"}
    requests.post(f"{TELEGRAM_API}/sendPhoto", data=data, files=files)


def answer_callback(callback_id, text=""):
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
    requests.post(f"{TELEGRAM_API}/answerCallbackQuery", json=payload)


# ---------- Teclados ----------

def teclado_pares():
    teclas = []
    pares = list(PARES.items())
    for i in range(0, len(pares), 2):
        linha = [{"text": PARES[p[0]]["nome"], "callback_data": f"par:{p[0]}"} for p in pares[i:i+2]]
        teclas.append(linha)
    return {"inline_keyboard": teclas}


def teclado_timeframes(par):
    tfs = list(TIMEFRAMES.keys())
    teclas = []
    for i in range(0, len(tfs), 3):
        linha = [{"text": TIMEFRAMES[t]["label"], "callback_data": f"tf:{par}:{t}"} for t in tfs[i:i+3]]
        teclas.append(linha)
    teclas.append([{"text": "⬅️ Trocar par", "callback_data": "menu"}])
    return {"inline_keyboard": teclas}


def teclado_acoes(par, tf):
    return {
        "inline_keyboard": [
            [
                {"text": "📊 Analisar", "callback_data": f"analisar:{par}:{tf}"},
                {"text": "📈 Gráfico", "callback_data": f"grafico:{par}:{tf}"},
            ],
            [
                {"text": "🔁 Trocar par", "callback_data": "menu"},
                {"text": "⏱️ Trocar TF", "callback_data": f"par:{par}"},
            ],
        ]
    }


# ---------- Obter dados e analisar ----------

def obter_dados(par, tf):
    symbol = PARES[par]["symbol"]
    cfg = TIMEFRAMES[tf]

    data = yf.download(symbol, period=cfg["period"], interval=cfg["interval"], progress=False)
    if data.empty:
        return None

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    data['Close'] = pd.to_numeric(data['Close'], errors='coerce')
    data = data.dropna(subset=['Close'])

    if "resample" in cfg:
        data = data.resample(cfg["resample"]).agg({
            'Open': 'first', 'High': 'max', 'Low': 'min',
            'Close': 'last', 'Volume': 'sum'
        }).dropna()

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


def texto_analise(par, tf, sinal, preco, ema9, ema21, rsi):
    if sinal == "COMPRA":
        emoji = "🟢⬆️ *SINAL DE COMPRA*"
    elif sinal == "VENDA":
        emoji = "🔴⬇️ *SINAL DE VENDA*"
    else:
        emoji = "⚪ *NEUTRO* (sem sinal claro)"
    d = PARES[par]["dec"]
    return (
        f"📊 *{PARES[par]['nome']} — {TIMEFRAMES[tf]['label']}*\n\n"
        f"{emoji}\n\n"
        f"💵 Preço: `{preco:.{d}f}`\n"
        f"📈 EMA 9: `{ema9:.{d}f}`\n"
        f"📉 EMA 21: `{ema21:.{d}f}`\n"
        f"⚡ RSI (14): `{rsi:.2f}`\n\n"
        f"⚠️ _Análise automática. Não é aconselhamento financeiro._"
    )


# ---------- Gráfico ----------

def gerar_grafico(data, sinal, par, tf):
    ultimos = data.tail(60).copy()
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=110)
    fig.patch.set_facecolor('#0e1621')
    ax.set_facecolor('#0e1621')

    x = range(len(ultimos))
    ax.plot(x, ultimos['Close'].values, color='#4da3ff', linewidth=1.8, label='Preço')
    ax.plot(x, ultimos['EMA9'].values, color='#00e676', linewidth=1.2, label='EMA 9')
    ax.plot(x, ultimos['EMA21'].values, color='#ff5252', linewidth=1.2, label='EMA 21')

    ultimo_x = len(ultimos) - 1
    ultimo_y = float(ultimos['Close'].iloc[-1])

    if sinal == "COMPRA":
        ax.annotate('', xy=(ultimo_x, ultimo_y * 1.0008),
                    xytext=(ultimo_x, ultimo_y * 0.9992),
                    arrowprops=dict(facecolor='#00e676', edgecolor='#00e676',
                                    width=6, headwidth=18, headlength=14))
        ax.text(0.02, 0.95, 'COMPRA', color='#00e676', fontsize=16,
                fontweight='bold', transform=ax.transAxes, va='top')
    elif sinal == "VENDA":
        ax.annotate('', xy=(ultimo_x, ultimo_y * 0.9992),
                    xytext=(ultimo_x, ultimo_y * 1.0008),
                    arrowprops=dict(facecolor='#ff5252', edgecolor='#ff5252',
                                    width=6, headwidth=18, headlength=14))
        ax.text(0.02, 0.95, 'VENDA', color='#ff5252', fontsize=16,
                fontweight='bold', transform=ax.transAxes, va='top')
    else:
        ax.text(0.02, 0.95, 'NEUTRO', color='#cccccc', fontsize=16,
                fontweight='bold', transform=ax.transAxes, va='top')

    ax.set_title(f"{PARES[par]['nome']} — {TIMEFRAMES[tf]['label']}",
                 color='white', fontsize=13, pad=10)
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

def acao_analisar(chat_id, par, tf):
    data = obter_dados(par, tf)
    if data is None:
        send_message(chat_id, "❌ Não consegui obter dados. Tenta outro par ou timeframe.")
        return
    sinal, preco, ema9, ema21, rsi = calcular_sinal(data)
    send_message(chat_id, texto_analise(par, tf, sinal, preco, ema9, ema21, rsi),
                 teclado_acoes(par, tf))


def acao_grafico(chat_id, par, tf):
    data = obter_dados(par, tf)
    if data is None:
        send_message(chat_id, "❌ Não consegui obter dados.")
        return
    sinal, preco, ema9, ema21, rsi = calcular_sinal(data)
    img = gerar_grafico(data, sinal, par, tf)
    d = PARES[par]["dec"]
    emoji = {"COMPRA": "🟢⬆️", "VENDA": "🔴⬇️", "NEUTRO": "⚪"}[sinal]
    caption = f"{emoji} *{sinal}* | Preço: `{preco:.{d}f}` | RSI: `{rsi:.1f}`"
    send_photo(chat_id, img, caption=caption)


# ---------- Webhook ----------

@app.route('/api/index', methods=['POST'])
def webhook():
    update = request.get_json()

    # --- Cliques nos botões ---
    if "callback_query" in update:
        cq = update["callback_query"]
        chat_id = cq["message"]["chat"]["id"]
        msg_id = cq["message"]["message_id"]
        data_btn = cq["data"]
        answer_callback(cq["id"])

        partes = data_btn.split(":")

        # Abrir menu principal (escolher par)
        if data_btn == "menu":
            edit_message(chat_id, msg_id,
                         "💱 *Escolhe o par que queres analisar:*",
                         teclado_pares())

        # Escolher timeframe para um par
        elif partes[0] == "par":
            par = partes[1]
            edit_message(chat_id, msg_id,
                         f"⏱️ *Escolhe o timeframe para {PARES[par]['nome']}:*",
                         teclado_timeframes(par))

        # Timeframe escolhido → mostra menu de ações
        elif partes[0] == "tf":
            par, tf = partes[1], partes[2]
            edit_message(chat_id, msg_id,
                         f"✅ *{PARES[par]['nome']} — {TIMEFRAMES[tf]['label']}*\n\nO que queres fazer?",
                         teclado_acoes(par, tf))

        # Analisar
        elif partes[0] == "analisar":
            par, tf = partes[1], partes[2]
            acao_analisar(chat_id, par, tf)

        # Gráfico
        elif partes[0] == "grafico":
            par, tf = partes[1], partes[2]
            acao_grafico(chat_id, par, tf)

    # --- Mensagens de texto ---
    elif "message" in update and "text" in update["message"]:
        chat_id = update["message"]["chat"]["id"]
        texto = update["message"]["text"].strip().lower()

        if texto in ("/start", "ola", "olá", "oi", "/menu"):
            send_message(chat_id,
                         "👋 Olá! Sou o teu bot de trading.\n\n💱 *Escolhe o par que queres analisar:*",
                         teclado_pares())
        elif texto in ("/ajuda", "ajuda", "help"):
            send_message(chat_id,
                         "🤖 *Como usar:*\n\n"
                         "1️⃣ Escolhe o par\n"
                         "2️⃣ Escolhe o timeframe\n"
                         "3️⃣ Clica em 📊 Analisar ou 📈 Gráfico\n\n"
                         "⚠️ _Ferramenta educacional. Não é aconselhamento financeiro._",
                         teclado_pares())
        else:
            send_message(chat_id,
                         "Escolhe um par para começar 👇",
                         teclado_pares())

    return "OK", 200git add .
git commit -m "Adicionar selecao de par e timeframe"
git push