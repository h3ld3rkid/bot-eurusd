# api/index.py
import os

# --- Configurações essenciais para o Vercel ---
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
from PIL import Image

yf.set_tz_cache_location("/tmp")

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# ---------- Configuração de Mercados ----------
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

PERFIS = {
    "padrao": ["EMA9", "EMA21", "RSI"],
    "tendencia": ["EMA9", "EMA21", "MACD"],
    "reversao": ["RSI", "BB"],
    "todos": ["EMA9", "EMA21", "RSI", "MACD", "BB", "VRVP"]
}

# ---------- Funções Telegram ----------
def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup: payload["reply_markup"] = reply_markup
    try: requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=8)
    except Exception: pass

def edit_message(chat_id, message_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup: payload["reply_markup"] = reply_markup
    try: requests.post(f"{TELEGRAM_API}/editMessageText", json=payload, timeout=8)
    except Exception: pass

def send_photo(chat_id, photo_bytes, caption="", reply_markup=None):
    data = {"chat_id": chat_id, "caption": caption, "parse_mode": "Markdown"}
    if reply_markup: data["reply_markup"] = json.dumps(reply_markup)
    try:
        files = {"photo": ("grafico.png", photo_bytes, "image/png")}
        requests.post(f"{TELEGRAM_API}/sendPhoto", data=data, files=files, timeout=10)
    except Exception: pass

def answer_callback(callback_id, text=""):
    payload = {"callback_query_id": callback_id}
    if text: payload["text"] = text
    try: requests.post(f"{TELEGRAM_API}/answerCallbackQuery", json=payload, timeout=5)
    except Exception: pass

def descarregar_foto_telegram(file_id):
    try:
        url = f"{TELEGRAM_API}/getFile?file_id={file_id}"
        resp = requests.get(url, timeout=8).json()
        if not resp.get("ok"): return None
        file_path = resp["result"]["file_path"]
        img_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
        img_resp = requests.get(img_url, timeout=10)
        return img_resp.content
    except Exception: return None

# ---------- Gemini Vision (Screenshots para Opções Binárias) ----------
def analisar_screenshot(img_bytes, contexto=""):
    if not gemini_client:
        return "⚠️ Falta a chave GEMINI_API_KEY no Vercel."

    try:
        img = Image.open(io.BytesIO(img_bytes))
        if img.width > 1024:
            ratio = 1024 / img.width
            img = img.resize((1024, int(img.height * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=85)
        img_bytes = buf.getvalue()
    except Exception: pass

    prompt = f"""És um trader profissional especialista em opções binárias (Pocket Option). Analisa este gráfico.
Contexto fornecido pelo utilizador: {contexto if contexto else "Nenhum."}

Responde em português de Portugal, de forma direta e curta (máx. 150 palavras):

📊 Ativo e Timeframe: Identifica o que vês.
📈 Tendência: Alta, baixa ou lateral.
🕯️ Análise de Velas: O que as últimas 3 velas mostram? (ex: força, rejeição, exaustão).
🚦 SINAL PARA O PRÓXIMO CANDLE: CALL (COMPRA), PUT (VENDA) ou ESPERAR.
🔮 Nível de Confiança: (0% a 100%).
🛑 Suportes e Resistências: Valores visíveis no gráfico.
💡 Justificação: O porquê do sinal ou do ESPERAR.

Se não tiveres a certeza, recomenda ESPERAR. Os gráficos OTC são imprevisíveis."""

    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[{"role": "user", "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(img_bytes).decode()}}
            ]}],
        )
        return response.text
    except Exception as e:
        return f"❌ Erro no Gemini: {str(e)}"

def acao_screenshot(chat_id, img_bytes, contexto=""):
    send_message(chat_id, "🔍 A analisar o teu gráfico... ⏳")
    send_message(chat_id, analisar_screenshot(img_bytes, contexto))

# ---------- Teclados ----------
def teclado_inicial():
    return {"inline_keyboard": [
        [{"text": "🚀   C O M E Ç A R   A N Á L I S E   🚀", "callback_data": "menu"}],
        [{"text": "⚙️ Indicadores de Análise", "callback_data": "indicadores"}],
        [{"text": "━━━━━━━━━━━━━━━━━━━━", "callback_data": "noop"}],
        [{"text": "🇪🇺 EUR/USD", "callback_data": "par:EURUSD:padrao"}, {"text": "🥇 OURO", "callback_data": "par:XAUUSD:padrao"}],
        [{"text": "₿ BITCOIN", "callback_data": "par:BTCUSD:padrao"}, {"text": "❓ AJUDA", "callback_data": "ajuda"}],
    ]}

def teclado_indicadores():
    return {"inline_keyboard": [
        [{"text": "📊 Padrão (EMA + RSI)", "callback_data": "set_ind:padrao"}],
        [{"text": "📈 Tendência (EMA + MACD)", "callback_data": "set_ind:tendencia"}],
        [{"text": "🔄 Reversão (RSI + Bollinger)", "callback_data": "set_ind:reversao"}],
        [{"text": "🧠 Todos os Indicadores (c/ VRVP)", "callback_data": "set_ind:todos"}],
        [{"text": "⬅️ Voltar", "callback_data": "inicio"}],
    ]}

def teclado_pares(perfil="padrao"):
    return {"inline_keyboard": [
        [{"text": "🇪🇺 EUR/USD", "callback_data": f"par:EURUSD:{perfil}"}, {"text": "🇬🇧 GBP/USD", "callback_data": f"par:GBPUSD:{perfil}"}],
        [{"text": "🇺🇸 USD/JPY", "callback_data": f"par:USDJPY:{perfil}"}, {"text": "🇦🇺 AUD/USD", "callback_data": f"par:AUDUSD:{perfil}"}],
        [{"text": "🥇 Ouro (XAU)", "callback_data": f"par:XAUUSD:{perfil}"}, {"text": "₿ BTC/USD", "callback_data": f"par:BTCUSD:{perfil}"}],
        [{"text": "⬅️ Voltar", "callback_data": "inicio"}],
    ]}

def teclado_timeframes(par, perfil):
    tfs = list(TIMEFRAMES.keys())
    teclas = []
    for i in range(0, len(tfs), 3):
        linha = [{"text": f"⏱️ {TIMEFRAMES[t]['label']}", "callback_data": f"tf:{par}:{t}:{perfil}"} for t in tfs[i:i+3]]
        teclas.append(linha)
    teclas.append([{"text": "⬅️ Trocar par", "callback_data": f"menu_ind:{perfil}"}])
    return {"inline_keyboard": teclas}

def teclado_acoes(par, tf, perfil):
    return {"inline_keyboard": [
        [{"text": "📊   A N A L I S A R   📊", "callback_data": f"analisar:{par}:{tf}:{perfil}"}],
        [{"text": "📈   G R Á F I C O   📈", "callback_data": f"grafico:{par}:{tf}:{perfil}"}],
        [{"text": "🔁 Trocar par", "callback_data": f"menu_ind:{perfil}"}, {"text": "⏱️ Trocar TF", "callback_data": f"par:{par}:{perfil}"}],
    ]}

# ---------- Motor de Análise (Forex) ----------
def calcular_vrvp(data, num_bins=20):
    visivel = data.tail(100).copy()
    if len(visivel) < 20: return None
    preco_min, preco_max = visivel['Low'].min(), visivel['High'].max()
    if pd.isna(preco_min) or preco_min == preco_max: return None
    
    weights = visivel['Volume'] if visivel['Volume'].sum() > 0 else pd.Series(1, index=visivel.index)
    bins = pd.cut(visivel['Close'], bins=num_bins, labels=False)
    vol_por_bin = weights.groupby(bins).sum()
    if vol_por_bin.empty: return None

    poc_bin = vol_por_bin.idxmax()
    edges = pd.cut(visivel['Close'], bins=num_bins, retbins=True)[1]
    poc_price = (edges[poc_bin] + edges[poc_bin+1]) / 2

    total_vol, target_vol, vol_acum = vol_por_bin.sum(), vol_por_bin.sum() * 0.70, 0
    vah, val = poc_price, poc_price
    
    for b in vol_por_bin.sort_values(ascending=False).index:
        vol_acum += vol_por_bin[b]
        preco_bin = (edges[b] + edges[b+1]) / 2
        vah, val = max(vah, preco_bin), min(val, preco_bin)
        if vol_acum >= target_vol: break

    return {"poc": poc_price, "vah": vah, "val": val}

def obter_dados(par, tf):
    symbol, cfg = PARES[par]["symbol"], TIMEFRAMES[tf]
    data = yf.download(symbol, period=cfg["period"], interval=cfg["interval"], progress=False)
    if data.empty: return None
    
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    data['Close'] = pd.to_numeric(data['Close'], errors='coerce')
    data = data.dropna(subset=['Close'])

    if "resample" in cfg:
        data = data.resample(cfg["resample"]).agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
    if data.empty: return None

    # Cálculo de Indicadores
    data['EMA9'] = data['Close'].ewm(span=9, adjust=False).mean()
    data['EMA21'] = data['Close'].ewm(span=21, adjust=False).mean()
    
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    data['RSI'] = 100 - (100 / (1 + (gain / loss)))
    
    data['MACD'] = data['Close'].ewm(span=12, adjust=False).mean() - data['Close'].ewm(span=26, adjust=False).mean()
    data['MACD_Signal'] = data['MACD'].ewm(span=9, adjust=False).mean()
    
    data['BB_Mid'] = data['Close'].rolling(window=20).mean()
    data['BB_Std'] = data['Close'].rolling(window=20).std()
    data['BB_Upper'] = data['BB_Mid'] + (data['BB_Std'] * 2)
    data['BB_Lower'] = data['BB_Mid'] - (data['BB_Std'] * 2)
    
    data.attrs['vrvp'] = calcular_vrvp(data)
    return data

def calcular_sinal(data, perfil):
    ultimo, preco, vrvp = data.iloc[-1], float(data.iloc[-1]['Close']), data.attrs.get('vrvp')
    vc, vv, ativos = 0, 0, PERFIS[perfil]
    
    if "EMA9" in ativos and ultimo['EMA9'] > ultimo['EMA21']: vc += 1
    elif "EMA9" in ativos: vv += 1
    
    if "RSI" in ativos and ultimo['RSI'] > 50: vc += 1
    elif "RSI" in ativos: vv += 1
    
    if "MACD" in ativos and ultimo['MACD'] > ultimo['MACD_Signal']: vc += 1
    elif "MACD" in ativos: vv += 1
        
    if "BB" in ativos and preco > ultimo['BB_Mid']: vc += 1
    elif "BB" in ativos: vv += 1

    if "VRVP" in ativos and vrvp:
        if preco > vrvp["vah"]: vc += 1
        elif preco < vrvp["val"]: vv += 1

    sinal = "COMPRA" if vc > vv else "VENDA" if vv > vc else "NEUTRO"
    return sinal, vc, vv, ultimo, vrvp

def texto_analise(par, tf, perfil, sinal, vc, vv, ultimo, vrvp):
    emoji = "🟢⬆️ COMPRA" if sinal == "COMPRA" else "🔴⬇️ VENDA" if sinal == "VENDA" else "⚪ NEUTRO"
    d, ativos = PARES[par]["dec"], PERFIS[perfil]
    
    txt = f"┌─────────────────────────┐\n   {PARES[par]['emoji']} *{PARES[par]['nome']}* — *{TIMEFRAMES[tf]['label']}*\n└─────────────────────────┘\n\n"
    txt += f"Sinal: *{emoji}*\nVotação: {vc} Compra / {vv} Venda\n\n"
    txt += f"💵 Preço: `{ultimo['Close']:.{d}f}`\n"
    
    if "EMA9" in ativos: txt += f"📈 EMA 9: `{ultimo['EMA9']:.{d}f}` | EMA 21: `{ultimo['EMA21']:.{d}f}`\n"
    if "RSI" in ativos: txt += f"⚡ RSI(14): `{ultimo['RSI']:.2f}`\n"
    if "MACD" in ativos: txt += f"📊 MACD: `{ultimo['MACD']:.{d}f}` | Sinal: `{ultimo['MACD_Signal']:.{d}f}`\n"
    if "BB" in ativos: txt += f"🎈 BB Sup: `{ultimo['BB_Upper']:.{d}f}` | Inf: `{ultimo['BB_Lower']:.{d}f}`\n"
    if "VRVP" in ativos and vrvp:
        txt += f"📊 VRVP: `POC: {vrvp['poc']:.{d}f}` | `VAH: {vrvp['vah']:.{d}f}` | `VAL: {vrvp['val']:.{d}f}`\n"
        
    txt += f"\n⚠️ _Perfil: {perfil.capitalize()}. Não é aconselhamento financeiro._"
    return txt

def gerar_grafico(data, sinal, par, tf):
    ultimos = data.tail(60).copy()
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=110)
    fig.patch.set_facecolor('#0e1621'); ax.set_facecolor('#0e1621')

    x = range(len(ultimos))
    ax.plot(x, ultimos['Close'].values, color='#4da3ff', linewidth=1.8, label='Preço')
    ax.plot(x, ultimos['EMA9'].values, color='#00e676', linewidth=1.0, label='EMA 9')
    ax.plot(x, ultimos['EMA21'].values, color='#ff5252', linewidth=1.0, label='EMA 21')
    ax.fill_between(x, ultimos['BB_Upper'].values, ultimos['BB_Lower'].values, color='#4da3ff', alpha=0.1, label='Bollinger')

    vrvp = data.attrs.get('vrvp')
    if vrvp:
        ax.axhline(y=vrvp['poc'], color='#ffcc00', linestyle='--', linewidth=1.2, label='POC')
        ax.axhline(y=vrvp['vah'], color='#00e676', linestyle=':', linewidth=1.0, label='VAH')
        ax.axhline(y=vrvp['val'], color='#ff5252', linestyle=':', linewidth=1.0, label='VAL')

    ultimo_x, ultimo_y = len(ultimos) - 1, float(ultimos['Close'].iloc[-1])
    cor = '#00e676' if sinal == "COMPRA" else '#ff5252' if sinal == "VENDA" else '#cccccc'
    
    ax.scatter([ultimo_x], [ultimo_y], color=cor, s=150, zorder=5)
    ax.text(0.02, 0.95, sinal, color=cor, fontsize=16, fontweight='bold', transform=ax.transAxes, va='top')

    ax.set_title(f"{PARES[par]['nome']} — {TIMEFRAMES[tf]['label']}", color='white', fontsize=13, pad=10)
    ax.tick_params(colors='#aaaaaa', labelsize=8)
    for spine in ax.spines.values(): spine.set_color('#2a3a4a')
    ax.grid(True, alpha=0.15, color='#8899aa')
    
    legend = ax.legend(loc='lower right', fontsize=8, facecolor='#1a2433', edgecolor='#2a3a4a')
    for t in legend.get_texts(): t.set_color('white')

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', facecolor=fig.get_facecolor())
    plt.close(fig); buf.seek(0)
    return buf.getvalue()

# ---------- Ações ----------
def acao_inicio(chat_id, nome=""):
    send_message(chat_id, f"👋 *Olá, {nome}!*\n\nBem-vindo ao AI Trading Bot 🤖\nEscolhe uma opção:", teclado_inicial())

def acao_analisar(chat_id, par, tf, perfil):
    data = obter_dados(par, tf)
    if not data:
        send_message(chat_id, "❌ Não consegui obter dados. Tenta outro par ou timeframe.")
        return
    sinal, vc, vv, ultimo, vrvp = calcular_sinal(data, perfil)
    send_message(chat_id, texto_analise(par, tf, perfil, sinal, vc, vv, ultimo, vrvp), teclado_acoes(par, tf, perfil))

def acao_grafico(chat_id, par, tf, perfil):
    data = obter_dados(par, tf)
    if not data:
        send_message(chat_id, "❌ Não consegui obter dados.")
        return
    sinal, _, _, ultimo, _ = calcular_sinal(data, perfil)
    img = gerar_grafico(data, sinal, par, tf)
    d = PARES[par]["dec"]
    emoji = {"COMPRA": "🟢⬆️", "VENDA": "🔴⬇️", "NEUTRO": "⚪"}[sinal]
    send_photo(chat_id, img, caption=f"{emoji} *{sinal}* | Preço: `{ultimo['Close']:.{d}f}`", reply_markup=teclado_acoes(par, tf, perfil))

# ---------- Webhook ----------
@app.route('/api/index', methods=['POST'])
def webhook():
    update = request.get_json()

    if "callback_query" in update:
        cq = update["callback_query"]
        chat_id, msg_id, data_btn = cq["message"]["chat"]["id"], cq["message"]["message_id"], cq["data"]
        answer_callback(cq["id"])
        partes = data_btn.split(":")

        if data_btn == "noop": return "OK", 200
        if data_btn == "inicio":
            edit_message(chat_id, msg_id, "🏠 *Menu principal*\n\nO que queres fazer?", teclado_inicial())
        elif data_btn == "indicadores":
            edit_message(chat_id, msg_id, "⚙️ *Escolhe o perfil de indicadores:*\n\nO bot vai calcular o sinal com base nos indicadores do perfil.", teclado_indicadores())
        elif partes[0] == "set_ind":
            perfil = partes[1]
            edit_message(chat_id, msg_id, f"✅ Perfil *{perfil.capitalize()}* selecionado!\n\nAgora escolhe o par:", teclado_pares(perfil))
        elif partes[0] == "menu_ind":
            edit_message(chat_id, msg_id, "💱 *Escolhe o par:*", teclado_pares(partes[1]))
        elif partes[0] == "par":
            par, perfil = partes[1], partes[2]
            edit_message(chat_id, msg_id, f"⏱️ *Escolhe o timeframe para {PARES[par]['nome']}:*", teclado_timeframes(par, perfil))
        elif partes[0] == "tf":
            par, tf, perfil = partes[1], partes[2], partes[3]
            edit_message(chat_id, msg_id, f"✅ *{PARES[par]['nome']} — {TIMEFRAMES[tf]['label']}*\nPerfil: {perfil.capitalize()}\n\nO que queres fazer?", teclado_acoes(par, tf, perfil))
        elif partes[0] == "analisar":
            acao_analisar(chat_id, partes[1], partes[2], partes[3])
        elif partes[0] == "grafico":
            acao_grafico(chat_id, partes[1], partes[2], partes[3])
        elif data_btn == "ajuda":
            edit_message(chat_id, msg_id, "🤖 *Como usar:*\n\n1. Escolhe um perfil de indicadores (opcional).\n2. Escolhe o par e o timeframe.\n3. Clica em Analisar ou Gráfico.\n\n📸 *Screenshot:* Envia uma foto de um gráfico (Pocket Option, MT5, etc.) para a IA analisar.", {"inline_keyboard": [[{"text": "⬅️ Voltar", "callback_data": "inicio"}]]})

    elif "message" in update and "photo" in update["message"]:
        chat_id = update["message"]["chat"]["id"]
        foto = update["message"]["photo"][-1]
        contexto = update["message"].get("caption", "")
        img_bytes = descarregar_foto_telegram(foto["file_id"])
        if img_bytes: acao_screenshot(chat_id, img_bytes, contexto)
        else: send_message(chat_id, "❌ Não consegui descarregar a imagem.")

    elif "message" in update and "text" in update["message"]:
        chat_id = update["message"]["chat"]["id"]
        nome = update["message"]["chat"].get("first_name", "")
        texto = update["message"]["text"].strip().lower()
        if texto in ("/start", "ola", "olá", "oi", "/menu"): acao_inicio(chat_id, nome)
        else: send_message(chat_id, "👋 Usa os botões para começar ou envia um *screenshot*.", teclado_inicial())

    return "OK", 200