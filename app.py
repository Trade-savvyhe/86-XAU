import os
from datetime import datetime
import numpy as np
import pandas as pd
import requests
import streamlit as st
import yfinance as yf
from streamlit_autorefresh import st_autorefresh

# 1. Page Setup
st.set_page_config(page_title="XAUUSD Live SMC Scanner", page_icon="⚡", layout="wide")

# Real-time 1-second auto-refresh
st_autorefresh(interval=1000, key="auto_scan_refresher")

# ============================================================
# CONFIGURATION & CONSTANTS
# ============================================================
DEFAULT_WEBHOOK = "https://discord.com/api/webhooks/1543551750647062558/AvecdYeit6FzvlHM64r_d-nkL-Vho2YifxA4ROp16MB6OhkmlNj1UDlvFeW_BnWrgYdV"
GOLD_API_KEY = "goldapi-c19928895f4d2b08f77ae252be11fb79-io"

SL_PIPS = 50
TP1_PIPS = 40
TP2_PIPS = 80
SL_DISTANCE = SL_PIPS * 0.10   # $5.00
TP1_DISTANCE = TP1_PIPS * 0.10 # $4.00
TP2_DISTANCE = TP2_PIPS * 0.10 # $8.00
SPREAD_POINTS = 0.30

# ============================================================
# DISCORD DISPATCHER
# ============================================================
def send_discord_alert(webhook_url: str, signal: dict):
    if not webhook_url:
        return False, "No webhook URL provided."

    is_buy = signal["direction"] == "BUY"
    color = 0x2ECC71 if is_buy else 0xE74C3C

    embed = {
        "title": f"🚨 NEW GOLD (15M) SMC SETUP: {signal['direction']}",
        "description": "High-confluence Liquidity Sweep + FVG Mitigation triggered.",
        "color": color,
        "fields": [
            {"name": "Pair", "value": "`XAUUSD / Gold (Live Spot)`", "inline": True},
            {"name": "Session", "value": "`Active Killzone`", "inline": True},
            {"name": "Entry Price", "value": f"**${signal['entry']:.2f}**", "inline": True},
            {"name": "Stop Loss (50p)", "value": f"**${signal['sl']:.2f}**", "inline": True},
            {"name": "TP 1 (40p - 50% & BE)", "value": f"**${signal['tp1']:.2f}**", "inline": True},
            {"name": "TP 2 (80p - Runner)", "value": f"**${signal['tp2']:.2f}**", "inline": True},
        ],
        "footer": {"text": "XAUUSD Institutional Scanner • Live Feed"},
        "timestamp": datetime.utcnow().isoformat(),
    }

    payload = {"username": "Gold SMC Bot", "embeds": [embed]}
    try:
        response = requests.post(webhook_url, json=payload, timeout=3)
        if response.status_code in [200, 204]:
            return True, "Alert sent successfully!"
        return False, f"Discord error code: {response.status_code}"
    except Exception as e:
        return False, str(e)


# ============================================================
# LIVE SPOT DATA FETCHER (GOLDAPI.IO DIRECT OTC FEED)
# ============================================================
@st.cache_data(ttl=1)
def fetch_exact_spot_price(api_key: str):
    # 1. Direct Real-Time OTC Spot Feed
    if api_key:
        try:
            headers = {
                "x-access-token": api_key.strip(),
                "Content-Type": "application/json"
            }
            res = requests.get("https://www.goldapi.io/api/XAU/USD", headers=headers, timeout=2)
            if res.status_code == 200:
                data = res.json()
                price = float(data.get("price", 0.0))
                bid = float(data.get("bid", price - 0.15))
                ask = float(data.get("ask", price + 0.15))
                if price > 0:
                    return price, bid, ask
        except Exception:
            pass

    # 2. Fast Spot 1-Minute Tick Fallback
    try:
        t = yf.Ticker("XAUUSD=X")
        df_1m = t.history(period="1d", interval="1m")
        if not df_1m.empty:
            p = float(df_1m['Close'].iloc[-1])
            return p, p - 0.15, p + 0.15
    except Exception:
        pass

    return 0.0, 0.0, 0.0


@st.cache_data(ttl=5)
def fetch_15m_candles():
    try:
        t = yf.Ticker("XAUUSD=X")
        df = t.history(period="5d", interval="15m")
        if df is None or df.empty:
            t = yf.Ticker("GC=F")
            df = t.history(period="5d", interval="15m")

        if df is not None and not df.empty:
            df = df.reset_index()
            time_col = "Datetime" if "Datetime" in df.columns else "Date"
            df = df.rename(columns={time_col: "time"})
            df.columns = [c.lower() for c in df.columns]
            df["time"] = pd.to_datetime(df["time"])
            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            return df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    except Exception:
        pass
    return None


def scan_latest_signal(df: pd.DataFrame, current_live_price: float):
    if len(df) < 35 or current_live_price <= 0:
        return None

    i = len(df) - 1
    current_time = df["time"].iloc[i]
    curr_open = float(df["open"].iloc[i])
    curr_high = max(float(df["high"].iloc[i]), current_live_price)
    curr_low = min(float(df["low"].iloc[i]), current_live_price)

    # Active Session Window (07:00 - 18:00 UTC)
    if not (7 <= current_time.hour <= 18):
        return None

    res_level = df["high"].iloc[i - 25 : i - 5].max()
    sup_level = df["low"].iloc[i - 25 : i - 5].min()

    # 1. Bullish Setup
    swept_support = df["low"].iloc[i - 5 : i - 1].min() < sup_level
    bull_fvg = df["low"].iloc[i - 1] > df["high"].iloc[i - 3]
    closed_strong = df["close"].iloc[i - 1] > df["open"].iloc[i - 1]

    if swept_support and bull_fvg and closed_strong:
        fvg_top = float(df["low"].iloc[i - 1])
        fvg_bottom = float(df["high"].iloc[i - 3])
        if (fvg_top - fvg_bottom) >= 0.40 and curr_low <= fvg_top:
            entry = min(curr_open, fvg_top) + SPREAD_POINTS
            return {
                "candle_time": str(current_time),
                "direction": "BUY",
                "entry": entry,
                "sl": entry - SL_DISTANCE,
                "tp1": entry + TP1_DISTANCE,
                "tp2": entry + TP2_DISTANCE,
            }

    # 2. Bearish Setup
    swept_res = df["high"].iloc[i - 5 : i - 1].max() > res_level
    bear_fvg = df["high"].iloc[i - 1] < df["low"].iloc[i - 3]
    closed_weak = df["close"].iloc[i - 1] < df["open"].iloc[i - 1]

    if swept_res and bear_fvg and closed_weak:
        fvg_bottom = float(df["high"].iloc[i - 1])
        if (df["low"].iloc[i - 3] - fvg_bottom) >= 0.40 and curr_high >= fvg_bottom:
            entry = max(curr_open, fvg_bottom)
            return {
                "candle_time": str(current_time),
                "direction": "SELL",
                "entry": entry,
                "sl": entry + SL_DISTANCE + SPREAD_POINTS,
                "tp1": entry - TP1_DISTANCE,
                "tp2": entry - TP2_DISTANCE,
            }

    return None


# ============================================================
# STREAMLIT DASHBOARD INTERFACE
# ============================================================
st.title("⚡ XAUUSD 15M Live SMC Scanner (Real-Time Spot)")

if "last_alert_id" not in st.session_state:
    st.session_state.last_alert_id = None
if "signals_history" not in st.session_state:
    st.session_state.signals_history = []

# Sidebar Controls
st.sidebar.header("⚙️ Configuration")
gold_key = st.sidebar.text_input("GoldAPI.io API Key", value=GOLD_API_KEY, type="password")
webhook_url = st.sidebar.text_input("Discord Webhook URL", value=DEFAULT_WEBHOOK, type="password")

if st.sidebar.button("🧪 Send Test Alert to Discord", use_container_width=True):
    sample_signal = {
        "candle_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "direction": "BUY (TEST)",
        "entry": 4447.23,
        "sl": 4442.23,
        "tp1": 4451.23,
        "tp2": 4455.23,
    }
    success, msg = send_discord_alert(webhook_url, sample_signal)
    if success:
        st.sidebar.success("✅ Test alert sent!")
    else:
        st.sidebar.error(f"❌ Failed: {msg}")

# Fetch Data
live_price, bid, ask = fetch_exact_spot_price(gold_key)
df = fetch_15m_candles()

if df is not None and not df.empty and live_price > 0:
    # Synchronize latest bar's close and extremes with live spot tick
    df.iloc[-1, df.columns.get_loc('close')] = live_price
    df.iloc[-1, df.columns.get_loc('high')] = max(df['high'].iloc[-1], live_price)
    df.iloc[-1, df.columns.get_loc('low')] = min(df['low'].iloc[-1], live_price)
    
    latest_candle = df.iloc[-1]
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Live Gold Spot Price", f"${live_price:,.2f}", f"Bid: ${bid:.2f} | Ask: ${ask:.2f}")
    col2.metric("Candle High (15M)", f"${latest_candle['high']:.2f}")
    col3.metric("Candle Low (15M)", f"${latest_candle['low']:.2f}")
    col4.metric("Last Sync (UTC)", datetime.utcnow().strftime("%H:%M:%S"))

    signal = scan_latest_signal(df, live_price)

    if signal:
        sig_id = f"{signal['candle_time']}_{signal['direction']}"
        st.success(
            f"🎯 **ACTIVE SETUP FOUND: {signal['direction']}** | Entry: ${signal['entry']:.2f} | SL: ${signal['sl']:.2f} | TP1: ${signal['tp1']:.2f} | TP2: ${signal['tp2']:.2f}"
        )

        if st.session_state.last_alert_id != sig_id:
            st.session_state.last_alert_id = sig_id
            st.session_state.signals_history.append(signal)
            if webhook_url:
                send_discord_alert(webhook_url, signal)
                st.toast("✅ Alert sent to Discord instantly!")
    else:
        st.info("⚡ Live feed active (updating every 1s)... No active mitigation setup on current candle.")

    st.subheader("Recent 15M Market Data (XAUUSD Spot)")
    st.dataframe(df[["time", "open", "high", "low", "close", "volume"]].tail(10), use_container_width=True)

    if st.session_state.signals_history:
        st.subheader("Triggered Alerts Log")
        st.dataframe(pd.DataFrame(st.session_state.signals_history), use_container_width=True)
else:
    st.warning("⚠️ Connecting to live spot stream...")
