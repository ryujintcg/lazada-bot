# Lazada Bot (GUI)

A PyQt6 desktop bot that watches Lazada SG product pages and automatically checks
out when an item comes back in stock. It monitors multiple products at once — each
in its own browser context with an optional proxy — and you enter the login OTP
right in the app.

## Features
- **Multi-task** — monitor many products in parallel, each in its own browser
- **Per-task proxies** — `host:port` or `host:port:user:pass` (datacenter / ISP)
- **One shared login** — log in once (OTP in a popup), session reused by all tasks
- **Variant/option selection** — picks the right option (e.g. `Sealed ETB`) before buying
- **Auto-checkout** — selects variant → Buy Now → Place Order
- **Buy-once guard** — won't re-order the same item; failed checkouts stop (no buy loop)
- **Discord notifications via webhook** — paste a webhook URL (🔔 Discord… button); no bot token needed. Optional.

## Requirements
- **Windows 10/11**
- **Python 3.10+** (`winget install Python.Python.3.12`)
- **Google Chrome** installed (the bot drives your installed Chrome via `channel="chrome"`)

## Setup

### 1. Create a virtual environment
```
python -m venv venv
venv\Scripts\activate
```

### 2. Install dependencies
```
pip install -r requirements.txt
```
(No `playwright install chromium` needed — the bot uses your installed Google Chrome.)

### 3. Create your config.py
```
copy config.example.py config.py
```
Edit `config.py`:
- `LAZADA_PHONE` — your Lazada account phone number (required)
- `DISCORD_*` — optional; leave the placeholders if you don't use Discord

### 4. Run
Double-click **`run_gui.bat`** (or `python gui_app.py`).

## Using it
1. **🔐 Login** → enter the OTP texted to your phone in the popup → wait for
   **"✅ Logged in — session saved"**.
2. **➕ Add Task** → paste a product URL.
   - Put the exact option text in **Variant / Option** if the product has options.
   - Set quantity, check interval, and (optionally) a proxy.
3. **▶ Start** the task (or **Start All**) and watch the Status column + Log.

## Notes
- It places **real orders** automatically when an item is in stock — make sure your
  default address and payment (the checkout step expects **Lazada Wallet**) are set up.
- **Proxies + login:** a proxied task may show "not logged in" because your session is
  tied to your login IP. Keep checkout tasks **proxy-free**.
- **Never share** `config.py` (your phone/tokens) or `lazada_session.json` (your live
  logged-in session). Use `Lazada-Bot-Share.zip` when sending the bot to others.

## File structure
```
gui_app.py         # PyQt6 GUI (entry point)
engine.py          # parallel task workers, login, variants, checkout
notifier.py        # optional Discord notifications
config.py          # YOUR private settings (not shared)
config.example.py  # template to copy
bot_data.json      # saved tasks + proxy pool
run_gui.bat        # double-click launcher
requirements.txt   # Python dependencies
SETUP.md           # setup guide for new users
```
