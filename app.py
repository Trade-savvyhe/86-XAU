import time
from datetime import datetime
import numpy as np
import pandas as pd
import requests
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="XAUUSD SMC Scanner", page_icon="⚡", layout="wide")

# ============================================================
# CONFIGURATION & CONSTANTS
# ============================================================
DEFAULT_WEBHOOK = "https://discord.com/api/webhooks/1543551750647062558/AvecdYeit6FzvlHM64r_d-nkL-Vho2YifxA4ROp16MB6OhkmlNj1UDlvFeW_BnWrgYdV"

SYMBOL = "GC=F"  # Gold Futures (XAU/USD equivalent)
INTERVAL = "15m"
PERIOD = "5d"
REFRESH_SECONDS = 5  # 5-second polling interval

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
    color = 0x2ECC71 if is_buy else 0xE74C3C  # Emerald Green or Crimson Red

    embed = {
        "title": f"🚨 NEW GOLD (15M) SMC SETUP: {signal['direction']}",
        "description": "High-confluence Liquidity Sweep + FVG Mitigation triggered.",
        "color": color,
        "fields": [
            {"name": "Pair", "value": "`XAUUSD / Gold`", "inline": True},
            {"name": "Session", "value": "`Active Killzone`", "inline": True},
            {"name": "Entry Price", "value": f"**${signal['entry']:.2f}**", "inline": True},
            {"name": "Stop Loss (50p)", "value": f"**${signal['sl']:.2f}**", "inline": True},
            {"name": "TP 1 (40p - 50% & BE)", "value": f"**${signal['tp1']:.2f}**", "inline": True},
            {"name": "TP 2 (80p - Runner)", "value": f"**${signal['tp2']:.2f}**", "inline": True},
        ],
        "footer": {"text": "XAUUSD SMC Institutional Scanner • 5s Real-Time"},
        "timestamp": datetime.utcnow().isoformat(),
    }

    payload = {"username": "Gold SMC Bot", "embeds": [embed]}
    try:
        response = requests.post(webhook_url, json=payload, timeout=5)
        if response.status_code == 204:
            return True, "Alert sent successfully!"
        return False, f"Discord error code: {response.status_code}"
    except Exception as e:
        return False, str(e)


# ============================================================
# DATA FETCHER & STRATEGY SCANNER
# ============================================================
def fetch_live_candles():
    try:
        ticker = yf.Ticker(SYMBOL)
        df = ticker.history(period=PERIOD, interval=INTERVAL)
        if df is None or df.empty:
            return None
        df = df.reset_index()
        if "Datetime" in df.columns:
            df = df.rename(columns={"Datetime": "time"})
        elif "Date" in df.columns:
            df = df.rename(columns={"Date": "time"})
            
        df.columns = [c.lower() for c in df.columns]
        df["time"] = pd.to_datetime(df["time"])
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    except Exception:
        time.sleep(2)
        return None


def scan_latest_signal(df: pd.DataFrame):
    if len(df) < 35:
        return None

    i = len(df) - 1
    current_time = df["time"].iloc[i]
    curr_open = float(df["open"].iloc[i])
    curr_high = float(df["high"].iloc[i])
    curr_low = float(df["low"].iloc[i])

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
st.title("⚡ XAUUSD 15M Live SMC Scanner (5s Interval)")

if "last_alert_id" not in st.session_state:
    st.session_state.last_alert_id = None
if "signals_history" not in st.session_state:
    st.session_state.signals_history = []

# --- SIDEBAR CONTROLS ---
st.sidebar.header("⚙️ Configuration")
webhook_url = st.sidebar.text_input("Discord Webhook URL", value=DEFAULT_WEBHOOK, type="password")

# Test Discord Button
if st.sidebar.button("🧪 Send Test Alert to Discord", use_container_width=True):
    sample_signal = {
        "candle_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "direction": "BUY (TEST)",
        "entry": 2735.40,
        "sl": 2730.40,
        "tp1": 2739.40,
        "tp2": 2743.40,
    }
    success, msg = send_discord_alert(webhook_url, sample_signal)
    if success:
        st.sidebar.success("✅ Test alert sent! Check your Discord.")
    else:
        st.sidebar.error(f"❌ Failed: {msg}")

st.sidebar.markdown("---")
auto_scan = st.sidebar.toggle("Auto-Refresh Scanner (Every 5s)", value=True)

# --- MAIN DASHBOARD ---
df = fetch_live_candles()

if df is not None:
    latest_candle = df.iloc[-1]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Current Gold Price", f"${latest_candle['close']:.2f}")
    col2.metric("Candle High", f"${latest_candle['high']:.2f}")
    col3.metric("Candle Low", f"${latest_candle['low']:.2f}")
    col4.metric("Last Check (UTC)", datetime.utcnow().strftime("%H:%M:%S"))

    signal = scan_latest_signal(df)

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
        st.info("Scanning every 5s... No active mitigation setup on current candle.")

    st.subheader("Recent 15M Market Data")
    st.dataframe(df[["time", "open", "high", "low", "close", "volume"]].tail(10), use_container_width=True)

    if st.session_state.signals_history:
        st.subheader("Triggered Alerts Log")
        st.dataframe(pd.DataFrame(st.session_state.signals_history), use_container_width=True)
else:
    st.warning("Fetching real-time tick...")

if auto_scan:
    time.sleep(REFRESH_SECONDS)
    st.rerun()
