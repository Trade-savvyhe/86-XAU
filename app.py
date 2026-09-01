import os
from datetime import datetime
import numpy as np
import pandas as pd
import requests
import streamlit as st
import MetaTrader5 as mt5
import plotly.express as px
from streamlit_autorefresh import st_autorefresh

# 1. Page Setup
st.set_page_config(
    page_title="XAUUSD 15M SMC Scanner (MT5 Live)",
    page_icon="⚡",
    layout="wide"
)

# 1-second auto-refresh for live price
st_autorefresh(interval=1000, key="auto_scan_refresher")

# ============================================================
# CONFIGURATION & CONSTANTS
# ============================================================
DEFAULT_WEBHOOK = "https://discord.com/api/webhooks/1544230745063559232/X6qlCgQFvZuVNLd3u0hEFZN7avsk3uTOpgJC1Tqh2zvHCG8du8kpxpEi3Fou-1z08S-M"

SYMBOL = "XAUUSDm"
LIVE_CANDLE_COUNT = 100
HISTORICAL_CANDLE_COUNT = 2500  # ~5-6 weeks of 15M data

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
            {"name": "Session", "value": "`Active Killzone (UTC)`", "inline": True},
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
# FAST LIVE TICK FETCHER (Zero lag on 1s loop)
# ============================================================
def fetch_live_candles_fast(symbol_name: str, count: int = 100):
    if not get_mt5_connection():
        return None, None

    mt5.symbol_select(symbol_name, True)
    tick = mt5.symbol_info_tick(symbol_name)

    rates = mt5.copy_rates_from_pos(symbol_name, mt5.TIMEFRAME_M15, 0, count)
    if rates is None or len(rates) == 0:
        return None, tick

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.rename(columns={"tick_volume": "volume"})
    
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        
    return df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True), tick

# ============================================================
# CACHED HISTORICAL SCANNER (Runs once every 5 minutes)
# ============================================================
@st.cache_data(ttl=300)
def compute_weekly_historical_record(symbol_name: str, count: int = 2500):
    if not get_mt5_connection():
        return []

    mt5.symbol_select(symbol_name, True)
    rates = mt5.copy_rates_from_pos(symbol_name, mt5.TIMEFRAME_M15, 0, count)
    if rates is None or len(rates) == 0:
        return []

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)

    signals = []
    for i in range(30, len(df)):
        current_time = df["time"].iloc[i]
        curr_open = float(df["open"].iloc[i])
        curr_high = float(df["high"].iloc[i])
        curr_low = float(df["low"].iloc[i])

        if not (7 <= current_time.hour <= 18):
            continue

        res_level = df["high"].iloc[i - 25 : i - 5].max()
        sup_level = df["low"].iloc[i - 25 : i - 5].min()

        swept_support = df["low"].iloc[i - 5 : i - 1].min() < sup_level
        bull_fvg = df["low"].iloc[i - 1] > df["high"].iloc[i - 3]
        closed_strong = df["close"].iloc[i - 1] > df["open"].iloc[i - 1]

        if swept_support and bull_fvg and closed_strong:
            fvg_top = float(df["low"].iloc[i - 1])
            fvg_bottom = float(df["high"].iloc[i - 3])
            if (fvg_top - fvg_bottom) >= 0.40 and curr_low <= fvg_top:
                entry = min(curr_open, fvg_top) + SPREAD_POINTS
                signals.append({
                    "time": current_time,
                    "direction": "BUY",
                    "entry": entry,
                    "sl": entry - SL_DISTANCE,
                    "tp1": entry + TP1_DISTANCE,
                    "tp2": entry + TP2_DISTANCE,
                })
                continue

        swept_res = df["high"].iloc[i - 5 : i - 1].max() > res_level
        bear_fvg = df["high"].iloc[i - 1] < df["low"].iloc[i - 3]
        closed_weak = df["close"].iloc[i - 1] < df["open"].iloc[i - 1]

        if swept_res and bear_fvg and closed_weak:
            fvg_bottom = float(df["high"].iloc[i - 1])
            if (df["low"].iloc[i - 3] - fvg_bottom) >= 0.40 and curr_high >= fvg_bottom:
                entry = max(curr_open, fvg_bottom)
                signals.append({
                    "time": current_time,
                    "direction": "SELL",
                    "entry": entry,
                    "sl": entry + SL_DISTANCE + SPREAD_POINTS,
                    "tp1": entry - TP1_DISTANCE,
                    "tp2": entry - TP2_DISTANCE,
                })

    return signals

def scan_latest_signal_fast(df: pd.DataFrame):
    if len(df) < 35:
        return None

    i = len(df) - 1
    current_time = df["time"].iloc[i]
    curr_open = float(df["open"].iloc[i])
    curr_high = float(df["high"].iloc[i])
    curr_low = float(df["low"].iloc[i])

    if not (7 <= current_time.hour <= 18):
        return None

    res_level = df["high"].iloc[i - 25 : i - 5].max()
    sup_level = df["low"].iloc[i - 25 : i - 5].min()

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

# Fast Live Data Fetch (100 candles only)
df_live, live_tick = fetch_live_candles_fast(target_symbol, LIVE_CANDLE_COUNT)

if df_live is not None and live_tick is not None:
    latest_candle = df_live.iloc[-1]
    
    # 1. Top Price Strip
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("MT5 Live Bid", f"${live_tick.bid:.2f}", f"Ask: ${live_tick.ask:.2f}")
    col2.metric("Candle High (M15)", f"${latest_candle['high']:.2f}")
    col3.metric("Candle Low (M15)", f"${latest_candle['low']:.2f}")
    col4.metric("Last Sync (UTC)", datetime.utcnow().strftime("%H:%M:%S"))

    # 2. Check Live Signal
    signal = scan_latest_signal_fast(df_live)

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

    st.markdown("---")

    # ========================================================
    # 3. FAST CACHED WEEKLY SUMMARY
    # ========================================================
    st.subheader("📅 Weekly Strategy Setups Record (Cached History)")
    
    historical_setups = compute_weekly_historical_record(target_symbol, HISTORICAL_CANDLE_COUNT)

    if historical_setups:
        sig_df = pd.DataFrame(historical_setups)
        sig_df["time"] = pd.to_datetime(sig_df["time"])
        
        sig_df["Week_Start"] = sig_df["time"].dt.to_period("W-SUN").apply(lambda r: r.start_time.strftime('%Y-%m-%d'))
        sig_df["Week_Label"] = "Week of " + sig_df["Week_Start"]

        # Safe aggregation
        weekly_summary = sig_df.groupby(["Week_Start"]).agg(
            Total_Setups=("direction", "count"),
            Buy_Setups=("direction", lambda x: (x == "BUY").sum()),
            Sell_Setups=("direction", lambda x: (x == "SELL").sum())
        ).reset_index().sort_values(by="Week_Start", ascending=False)

        if "Buy_Setups" not in weekly_summary.columns:
            weekly_summary["Buy_Setups"] = 0
        if "Sell_Setups" not in weekly_summary.columns:
            weekly_summary["Sell_Setups"] = 0

        curr_week_total = int(weekly_summary.iloc[0]["Total_Setups"]) if len(weekly_summary) > 0 else 0
        prev_week_total = int(weekly_summary.iloc[1]["Total_Setups"]) if len(weekly_summary) > 1 else 0
        avg_weekly_setups = round(weekly_summary["Total_Setups"].mean(), 1)

        m1, m2, m3 = st.columns(3)
        m1.metric("Current Week Setups", f"{curr_week_total} setups", f"{curr_week_total - prev_week_total:+d} vs last week")
        m2.metric("Previous Week Setups", f"{prev_week_total} setups")
        m3.metric("Average Setups / Week", f"{avg_weekly_setups} setups")

        tab1, tab2, tab3 = st.tabs(["📊 Weekly Bar Chart", "📋 Weekly Summary Table", "📜 All Identified Setups"])

        with tab1:
            chart_df = weekly_summary.sort_values(by="Week_Start", ascending=True)
            fig = px.bar(
                chart_df,
                x="Week_Start",
                y=["Buy_Setups", "Sell_Setups"],
                title="15M SMC Strategy Setups Formed Per Week",
                labels={"Week_Start": "Week Starting (Monday)", "value": "Number of Setups", "variable": "Setup Type"},
                color_discrete_map={"Buy_Setups": "#10b981", "Sell_Setups": "#ef4444"},
                barmode="group",
                text_auto=True
            )
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#f1f5f9"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            st.plotly_chart(fig, use_container_width=True)

        with tab2:
            display_table = weekly_summary.rename(columns={
                "Week_Start": "Week Start Date",
                "Total_Setups": "Total Setups Built",
                "Buy_Setups": "Bullish (BUY)",
                "Sell_Setups": "Bearish (SELL)"
            })
            st.dataframe(
                display_table[["Week Start Date", "Total Setups Built", "Bullish (BUY)", "Bearish (SELL)"]],
                use_container_width=True,
                hide_index=True
            )

        with tab3:
            st.dataframe(
                sig_df[["time", "direction", "entry", "sl", "tp1", "tp2"]].sort_values(by="time", ascending=False),
                use_container_width=True,
                hide_index=True
            )

    else:
        st.info("No setups found across the historical window.")

    st.markdown("---")

    # 4. Recent Raw 15M Data
    st.subheader(f"Recent 15M Market Data ({target_symbol})")
    st.dataframe(df_live[["time", "open", "high", "low", "close", "volume"]].tail(10), use_container_width=True)

else:
    st.warning("⚠️ Connecting to MT5... Ensure your MetaTrader 5 desktop application is open and logged in.")
