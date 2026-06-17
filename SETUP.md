# Lazada Bot (GUI) — Setup Guide

A desktop bot that watches Lazada SG product pages and automatically checks out
when an item comes back in stock. It can monitor multiple products at once (each
in its own browser, with an optional proxy) and enter the OTP right in the app.

---

## 1. Requirements
- **Windows 10/11**
- **Python 3.10+** — get it from https://python.org, or run `winget install Python.Python.3.12`
- **Google Chrome** installed (the bot drives your installed Chrome)

## 2. Install
Open a terminal **in this folder** and run:

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## 3. Configure
Make your own config file from the template:

```
copy config.example.py config.py
```

Open `config.py` and set **`LAZADA_PHONE`** to **YOUR** Lazada account phone number
(e.g. `91234567`). The Discord fields are **optional** — leave the placeholder text
if you don't use Discord notifications; the app works without them.

## 4. Run
Double-click **`run_gui.bat`** (or run `python gui_app.py`).

## 5. Use it
1. **🔐 Login** → an OTP is texted to your phone → type it into the popup →
   wait for **"✅ Logged in — session saved"**.
2. **➕ Add Task** → paste a product URL.
   - If the product has options, put the **exact option text** in
     **"Variant / Option"** (e.g. `Sealed ETB`). Leave blank if it has no options.
   - Set quantity, check interval, and (optionally) a proxy `host:port:user:pass`.
3. **▶ Start** the task (or **Start All**) and watch the Status column + Log.
   - When it's in stock the bot selects the variant, clicks Buy Now, and places the
     order using your default address + payment. A **buy-once guard** stops it from
     ordering the same item twice.

## Discord notifications (optional)
Get a ping when an item goes in stock / an order is placed:
1. In Discord: **Channel → Edit Channel → Integrations → Webhooks → New Webhook → Copy Webhook URL**.
2. In the bot, click **🔔 Discord…**, paste the URL, hit **Send test**, then **Save**.

No bot token or Discord developer setup needed — just the webhook URL.

---

## Important notes
- **It places REAL orders automatically.** Make sure your default shipping address
  and payment method (the bot expects **Lazada Wallet**) are set up first.
- **Use your own account.** The bot logs in with whatever phone is in `config.py`
  and uses your OTP.
- **Proxies + login:** a task running through a proxy may show "not logged in"
  because your Lazada session is tied to your login IP. Keep checkout tasks
  **proxy-free**; use proxies mainly to spread out extra monitor tasks.

## ⚠️ NEVER share these files
- **`config.py`** — contains your phone number / tokens
- **`lazada_session.json`** — this is your live logged-in Lazada session;
  sharing it literally hands someone access to your account
