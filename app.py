import os
from datetime import datetime
import numpy as np
import pandas as pd
import requests
import streamlit as st
import MetaTrader5 as mt5
from streamlit_autorefresh import st_autorefresh

# 1. Page Setup
st.set_page_config(page_title="XAUUSD SMC Scanner (MT5 Sync)", page_icon="⚡", layout="wide")

# 1-second auto-refresh (1000 ms)
st_autorefresh(interval=1000, key="auto_scan_refresher")

# ============================================================
# CONFIGURATION & CONSTANTS
# ============================================================
DEFAULT_WEBHOOK = "https://discord.com/api/webhooks/1543551750647062558/AvecdYeit6FzvlHM64r_d-nkL-Vho2YifxA4ROp16MB6OhkmlNj1UDlvFeW_BnWrgYdV"

SYMBOL = "XAUUSDm"
CANDLE_COUNT = 100

SL_PIPS = 50
TP1_PIPS = 40
TP2_PIPS = 80
SL_DISTANCE = SL_PIPS * 0.10   # $5.00
TP1_DISTANCE = TP1_PIPS * 0.10 # $4.00
TP2_DISTANCE = TP2_PIPS * 0.10 # $8.00
SPREAD_POINTS = 0.30

# ============================================================
# MT5 CONNECTION
# ============================================================
def get_mt5_connection():
    if not mt5.initialize():
        return False
    return True

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
        "description": "High-confluence Liquidity Sweep + FVG Mitigation triggered directly from Exness MT5.",
        "color": color,
        "fields": [
            {"name": "Pair", "value": f"`{SYMBOL}`", "inline": True},
            {"name": "Session", "value": "`Active Killzone`", "inline": True},
            {"name": "Entry Price", "value": f"**${signal['entry']:.2f}**", "inline": True},
            {"name": "Stop Loss (50p)", "value": f"**${signal['sl']:.2f}**", "inline": True},
            {"name": "TP 1 (40p - 50% & BE)", "value": f"**${signal['tp1']:.2f}**", "inline": True},
            {"name": "TP 2 (80p - Runner)", "value": f"**${signal['tp2']:.2f}**", "inline": True},
        ],
        "footer": {"text": "XAUUSD SMC Institutional Scanner • Exness MT5 Live"},
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
# MT5 DATA FETCHER & STRATEGY SCANNER
# ============================================================
def fetch_live_candles_mt5(symbol_name: str):
    if not get_mt5_connection():
        return None, None

    mt5.symbol_select(symbol_name, True)
    tick = mt5.symbol_info_tick(symbol_name)

    rates = mt5.copy_rates_from_pos(symbol_name, mt5.TIMEFRAME_M15, 0, CANDLE_COUNT)
    if rates is None or len(rates) == 0:
        return None, tick

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.rename(columns={"tick_volume": "volume"})
    
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        
    return df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True), tick


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
st.title("⚡ XAUUSD 15M Live SMC Scanner (1s Interval)")

if "last_alert_id" not in st.session_state:
    st.session_state.last_alert_id = None
if "signals_history" not in st.session_state:
    st.session_state.signals_history = []

# Sidebar Controls
st.sidebar.header("⚙️ Configuration")
target_symbol = st.sidebar.text_input("MT5 Symbol Name", value=SYMBOL)
webhook_url = st.sidebar.text_input("Discord Webhook URL", value=DEFAULT_WEBHOOK, type="password")

if st.sidebar.button("🧪 Send Test Alert to Discord", use_container_width=True):
    sample_signal = {
        "candle_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "direction": "BUY (TEST)",
        "entry": 4443.50,
        "sl": 4438.50,
        "tp1": 4447.50,
        "tp2": 4451.50,
    }
    success, msg = send_discord_alert(webhook_url, sample_signal)
    if success:
        st.sidebar.success("✅ Test alert sent!")
    else:
        st.sidebar.error(f"❌ Failed: {msg}")

# Main Data Fetch
df, live_tick = fetch_live_candles_mt5(target_symbol)

if df is not None and live_tick is not None:
    latest_candle = df.iloc[-1]
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("MT5 Live Bid", f"${live_tick.bid:.2f}", f"Ask: ${live_tick.ask:.2f}")
    col2.metric("Candle High (M15)", f"${latest_candle['high']:.2f}")
    col3.metric("Candle Low (M15)", f"${latest_candle['low']:.2f}")
    col4.metric("Last Sync (UTC)", datetime.utcnow().strftime("%H:%M:%S"))

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
        st.info("⚡ Live feed active (updating every 1s)... No active mitigation setup on current candle.")

    st.subheader(f"Recent 15M Market Data ({target_symbol})")
    st.dataframe(df[["time", "open", "high", "low", "close", "volume"]].tail(10), use_container_width=True)

    if st.session_state.signals_history:
        st.subheader("Triggered Alerts Log")
        st.dataframe(pd.DataFrame(st.session_state.signals_history), use_container_width=True)
else:
    st.warning("⚠️ Connecting to MT5... Ensure your MetaTrader 5 desktop application is open and logged in.")
