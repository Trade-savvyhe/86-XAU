# ⚡ XAUUSD 15M Live SMC Scanner (Exness MT5 Sync)

Institutional Fair Value Gap (FVG) and Liquidity Sweep scanner for Gold (`XAUUSDm`) synced directly to MetaTrader 5 with 1-second auto-refresh and Discord webhook dispatches.

---

## 🚀 Features
* **Zero Delay:** Syncs tick-by-tick directly with Exness MetaTrader 5 terminal.
* **1s Auto-Refresh:** Non-blocking UI updates via `streamlit-autorefresh`.
* **SMC Logic:** Scans for liquidity sweeps and 15-minute FVG mitigations.
* **Discord Alerts:** Sends instant rich embeds on validated trade entries.

---

## 🛠️ Setup & Execution

### 1. Prerequisites
* Windows 10/11
* [MetaTrader 5](https://www.exness.com/) (Logged into your Exness account)
* Python 3.10+

### 2. Installation
```bash
git clone [https://github.com/Trade-savvyhe/86-XAU.git](https://github.com/Trade-savvyhe/86-XAU.git)
cd 86-XAU
pip install -r requirements.txt
