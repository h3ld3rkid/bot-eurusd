# api/index.py
import os

# --- CORREÇÕES PARA O VERCEL ---
os.environ['MPLCONFIGDIR'] = '/tmp'
os.environ['YF_CACHE_DIR'] = '/tmp'

from flask import Flask, request
import io
import json
import base64
import requests
import yfinance as yf
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from google import genai

yf.set_tz_cache_location("/tmp")

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Cliente Gemini (só é inicializado se a chave existir)
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

URL_IMAGEM_BOAS_VINDAS = ""  # opcional: cola aqui um URL público

# ---------- Configuração de pares e timeframes ----------

PARES = {
    "EURUSD": {"symbol": "EURUSD=X", "nome": "EUR/USD", "dec": 4, "emoji": "🇪🇺🇺🇸"},
    "GBPUSD": {"symbol": "GBPUSD=X", "nome": "GBP/USD", "dec": 4, "emoji": "🇬🇧🇺🇸"},
    "USDJPY": {"symbol": "USDJPY=X", "nome": "USD/JPY", "dec": 2, "emoji": "🇺🇸🇯🇵"},
    "AUDUSD": {"symbol": "AUDUSD=X", "nome": "AUD/USD", "dec": 4, "emoji": "🇦🇺🇺🇸"},
    "XAUUSD": {"symbol": "GC=F",     "nome": "Ouro (XAU)", "dec": 2, "emoji": "🥇"},
    "BTCUSD": {"symbol": "BTC-USD",  "nome": "Bitcoin", "dec": 0, "emoji": "₿"},
}

TIMEFRAMES = {
    "M5":  {"interval": "5m",  "period": "5d",  "label": "M5"},
    "M15": {"interval": "15m", "period": "5d",  "label": "M15"},
    "M30": {"interval": "30m", "period": "1mo", "label": "M30"},
    "H1":  {"interval": "1h",  "period": "1mo", "label": "H1"},
    "H4":  {"interval": "1h",  "period": "3mo", "resample": "4h", "label": "H4"},
    "D1":  {"interval": "1d",  "period": "1y",  "label": "D1"},
}


# ---------- Funções Telegram ----------

def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=8)
    except Exception:
        pass


def edit_message(chat_id, message_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(f"{TELEGRAM_API}/editMessageText", json=payload, timeout=8)
    except Exception:
        pass


def send_photo(chat_id, photo, caption="", reply_markup=None, is_url=False):
    data = {"chat_id": chat_id, "caption": caption, "parse_mode": "Markdown"}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    try:
        if is_url:
            data["photo"] = photo
            requests.post(f"{TELEGRAM_API}/sendPhoto", data=data, timeout=8)
        else:
            files = {"photo": ("grafico.png", photo, "image/png")}
            requests.post(f"{TELEGRAM_API}/sendPhoto", data=data, files=files, timeout=8)
    except Exception:
        pass


def answer_callback(callback_id, text=""):
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
    try:
        requests.post(f"{TELEGRAM_API}/answerCallbackQuery", json=payload, timeout=5)
    except Exception:
        pass


def descarregar_foto_telegram(file_id):
    """Descarrega a foto do Telegram e devolve bytes."""
    try:
        url = f"{TELEGRAM_API}/getFile?file_id={file_id}"
        resp = requests.get(url, timeout=8).json()
        if not resp.get("ok"):
            return None
        file_path = resp["result"]["file_path"]
        img_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
        img_resp = requests.get(img_url, timeout=10)
        return img_resp.content
    except Exception:
        return None


# ---------- Análise por Screenshot (Gemini) ----------

def analisar_screenshot(img_bytes, contexto=""):
    """Envia a imagem ao Gemini e devolve análise técnica estruturada."""
    if not gemini_client:
        return "⚠️ A análise de screenshots não está configurada. Falta a variável GEMINI_API_KEY no Vercel."

    prompt = f"""És um analista técnico profissional de trading. Analisa este gráfico com rigor.

Contexto fornecido pelo utilizador: {contexto if contexto else "Nenhum."}

Responde em português de Portugal, de forma estruturada e curta (máx. 300 palavras):

📊 *Par e Timeframe*: Identifica o que vês.
📈 *Tendência*: Alta, baixa ou lateral. Justifica com o que observas.
🎯 *Zonas-chave*: Suportes e resistências relevantes (valores concretos).
🚪 *Entrada sugerida*: Preço ou zona.
🛑 *Stop Loss*: Valor concreto e justificação.
✅ *Take Profit*: Valor concreto e justificação.
⚖️ *Rácio Risco/Retorno*: Calcula (ex: 1:2).
⚠️ *Aviso*: Se não tiveres informação suficiente (sem preços visíveis, gráfico cortado, etc.), diz claramente.

Sê honesto. Não inventes valores que não consegues ver no gráfico."""

    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": base64.b64encode(img_bytes).decode(),
                            }
                        },
                    ],
                }
            ],
        )
        return response.text
    except Exception as e:
        return f"❌ Erro ao analisar a imagem: {str(e)}"


def acao_screenshot(chat_id, img_bytes, contexto=""):
    send_message(chat_id, "🔍 A analisar o teu gráfico... ⏳")
    analise = analisar_screenshot(img_bytes, contexto)
    send_message(chat_id, analise)


# ---------- Teclados ----------

def teclado_inicial():
    return {
        "inline_keyboard": [
            [{"text": "🚀   C O M E Ç A R   A N Á L I S E   🚀", "callback_data": "menu"}],
            [{"text": "━━━━━━━━━━━━━━━━━━━━", "callback_data": "noop"}],
            [
                {"text": "🇪🇺 EUR/USD", "callback_data": "par:EURUSD"},
                {"text": "🥇 OURO",     "callback_data": "par:XAUUSD"},
            ],
            [
                {"text": "₿ BITCOIN",  "callback_data": "par:BTCUSD"},
                {"text": "❓ AJUDA",   "callback_data": "ajuda"},
            ],
        ]
    }


def teclado_pares():
    return {
        "inline_keyboard": [
            [
                {"text": "🇪🇺 EUR/USD", "callback_data": "par:EURUSD"},
                {"text": "🇬🇧 GBP/USD", "callback_data": "par:GBPUSD"},
            ],
            [
                {"text": "🇺🇸 USD/JPY", "callback_data": "par:USDJPY"},
                {"text": "🇦🇺 AUD/USD", "callback_data": "par:AUDUSD"},
            ],
            [
                {"text": "🥇 Ouro (XAU)", "callback_data": "par:XAUUSD"},
                {"text": "₿ BTC/USD",     "callback_data": "par:BTCUSD"},
            ],
            [{"text": "⬅️ Voltar", "callback_data": "inicio"}],
        ]
    }


def teclado_timeframes(par):
    tfs = list(TIMEFRAMES.keys())
    teclas = []
    for i in range(0, len(tfs), 3):
        linha = [{"text": f"⏱️ {TIMEFRAMES[t]['label']}", "callback_data": f"tf:{par}:{t}"} for t in tfs[i:i+3]]
        teclas.append(linha)
    teclas.append([{"text": "⬅️ Trocar par", "callback_data": "menu"}])
    return {"inline_keyboard": teclas}


def teclado_acoes(par, tf):
    return {
        "inline_keyboard": [
            [{"text": "📊   A N A L I S A R   📊", "callback_data": f"analisar:{par}:{tf}"}],
            [{"text": "📈   G R Á F I C O   📈", "callback_data": f"grafico:{par}:{tf}"}],
            [
                {"text": "🔁 Trocar par", "callback_data": "menu"},
                {"text": "⏱️ Trocar TF", "callback_data": f"par:{par}"},
            ],
        ]
    }


# ---------- Análise EMA/RSI (já existente) ----------

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
        emoji = "🟢⬆️  *S I N A L   D E   C O M P R A*"
    elif sinal == "VENDA":
        emoji = "🔴⬇️  *S I N A L   D E   V E N D A*"
    else:
        emoji = "⚪  *N E U T R O*  (sem sinal claro)"
    d = PARES[par]["dec"]
    return (
        f"┌─────────────────────────┐\n"
        f"   {PARES[par]['emoji']} *{PARES[par]['nome']}* — *{TIMEFRAMES[tf]['label']}*\n"
        f"└─────────────────────────┘\n\n"
        f"{emoji}\n\n"
        f"💵 Preço:  `{preco:.{d}f}`\n"
        f"📈 EMA 9:  `{ema9:.{d}f}`\n"
        f"📉 EMA 21: `{ema21:.{d}f}`\n"
        f"⚡ RSI(14): `{rsi:.2f}`\n\n"
        f"⚠️ _Análise automática. Não é aconselhamento financeiro._"
    )


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


def acao_inicio(chat_id, nome=""):
    saudacao = f"Olá, {nome}!" if nome else "Olá!"
    caption = (
        f"👋 *{saudacao}*\n\n"
        f"Bem-vindo ao *AI Trading Bot* 🤖\n\n"
        f"🔹 Análise automática (EMA/RSI)\n"
        f"🔹 Análise de screenshots (IA Gemini)\n\n"
        f"Usa os botões abaixo 👇"
    )
    if URL_IMAGEM_BOAS_VINDAS.startswith("http"):
        send_photo(chat_id, URL_IMAGEM_BOAS_VINDAS, caption=caption,
                   reply_markup=teclado_inicial(), is_url=True)
    else:
        send_message(chat_id, caption, teclado_inicial())


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
    send_photo(chat_id, img, caption=caption, reply_markup=teclado_acoes(par, tf))


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

        if data_btn == "noop":
            return "OK", 200

        partes = data_btn.split(":")

        if data_btn == "inicio":
            edit_message(chat_id, msg_id,
                         "🏠 *Menu principal*\n\nO que queres fazer?",
                         teclado_inicial())

        elif data_btn == "menu":
            edit_message(chat_id, msg_id,
                         "💱 *Escolhe o par que queres analisar:*",
                         teclado_pares())

        elif data_btn == "ajuda":
            edit_message(chat_id, msg_id,
                         "🤖 *Como usar o bot:*\n\n"
                         "*📊 Análise automática:*\n"
                         "Escolhe par → timeframe → Analisar/Gráfico.\n\n"
                         "*🖼️ Análise por screenshot:*\n"
                         "Envia uma *foto do teu gráfico* (do MT5, TradingView, etc.) e a IA vai analisá-la com tendência, entrada, SL e TP.\n\n"
                         "*💡 Dicas para o screenshot:*\n"
                         "• Mostra os preços nos eixos\n"
                         "• Inclui o par e timeframe visíveis\n"
                         "• Podes adicionar uma legenda com contexto\n\n"
                         "⚠️ _Ferramenta educacional. Não é aconselhamento financeiro._",
                         {"inline_keyboard": [[{"text": "⬅️ Voltar", "callback_data": "inicio"}]]})

        elif partes[0] == "par":
            par = partes[1]
            edit_message(chat_id, msg_id,
                         f"⏱️ *Escolhe o timeframe para {PARES[par]['emoji']} {PARES[par]['nome']}:*",
                         teclado_timeframes(par))

        elif partes[0] == "tf":
            par, tf = partes[1], partes[2]
            edit_message(chat_id, msg_id,
                         f"✅ *{PARES[par]['emoji']} {PARES[par]['nome']} — {TIMEFRAMES[tf]['label']}*\n\nO que queres fazer?",
                         teclado_acoes(par, tf))

        elif partes[0] == "analisar":
            par, tf = partes[1], partes[2]
            acao_analisar(chat_id, par, tf)

        elif partes[0] == "grafico":
            par, tf = partes[1], partes[2]
            acao_grafico(chat_id, par, tf)

    # --- Foto enviada pelo utilizador (screenshot para análise) ---
    elif "message" in update and "photo" in update["message"]:
        chat_id = update["message"]["chat"]["id"]
        foto = update["message"]["photo"][-1]  # maior resolução
        contexto = update["message"].get("caption", "")

        img_bytes = descarregar_foto_telegram(foto["file_id"])
        if img_bytes:
            acao_screenshot(chat_id, img_bytes, contexto)
        else:
            send_message(chat_id, "❌ Não consegui descarregar a imagem. Tenta novamente.")

    # --- Mensagens de texto ---
    elif "message" in update and "text" in update["message"]:
        chat_id = update["message"]["chat"]["id"]
        nome = update["message"]["chat"].get("first_name", "")
        texto = update["message"]["text"].strip().lower()

        if texto in ("/start", "ola", "olá", "oi", "/menu"):
            acao_inicio(chat_id, nome)
        elif texto in ("/ajuda", "ajuda", "help"):
            send_message(chat_id,
                         "🤖 Envia /start para começar, ou envia um *screenshot* do teu gráfico.",
                         teclado_inicial())
        else:
            send_message(chat_id,
                         "👋 Usa os botões abaixo ou envia um *screenshot* do teu gráfico 👇",
                         teclado_inicial())

    return "OK", 200