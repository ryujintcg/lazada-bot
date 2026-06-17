# Changelog

## v2.2 — payment + auto-update
- **Payment method per task** — choose Lazada Wallet, Credit/Debit Card, Cash on
  Delivery, PayLater, etc. (or leave blank to use whatever's pre-selected).
  Checkout is no longer locked to Lazada Wallet.
- **In-app auto-update** — the bot checks a version manifest you host and offers a
  one-click "Update now?" that downloads + swaps the app files (your config,
  tasks, and session are never touched), then restarts. Manual check via the
  ⬇ Updates button.

## v2.1 — feature update
- **Faster, lighter monitoring** — images, fonts and media are blocked, so each
  product check loads quicker and uses less bandwidth.
- **Session auto-recovery** — if the Lazada login expires while monitoring, the
  task pauses and the app auto-prompts a re-login, then resumes (no silent death).
- **Checkout retries** — a failed checkout step is retried up to 3× before the
  task stops, instead of giving up on the first hiccup.
- **Proxy health check** — "Test all" button in the proxy dialog reports which
  proxies actually work (and how fast), in the log.
- **Stealth fingerprinting** — masks `navigator.webdriver` and related signals to
  lower the CAPTCHA rate.
- **CAPTCHA auto-solve (optional)** — set `CAPTCHA_API_KEY` (2captcha) to auto-solve
  reCAPTCHA. The Lazada slider still needs a manual solve in the window.
- **Alert-only mode** — per task: get a Discord ping on restock without auto-buying.
- **Scheduled start** — per task: start monitoring at a set HH:MM (e.g. a drop time).
- **Richer Discord alerts** — embeds with product link + optional role @ping on
  stock / order events.
- **Price guard** — per-task max price; aborts checkout if the total is higher.
- **UI** — Variant and Alert columns, per-row Start/Stop, Self-test button,
  in-app Changelog viewer.
- **Centralized selectors + Self-test** — all Lazada selectors live in one place;
  the Self-test button validates them against a live product page.
- **Order log** — placed orders are recorded to `orders.log`.

## v2.0 — GUI rebuild
- Replaced the single-product CLI bot with a PyQt6 desktop app.
- Multiple products monitored in parallel, each in its own browser + proxy.
- One shared login (OTP entered in-app), session reused across tasks.
- Variant/option selection, buy-once guard, no-buy-loop safety.
- Discord webhook notifications (no bot token needed).
- Uses installed Google Chrome (fixed broken bundled Chromium).
