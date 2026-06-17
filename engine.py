"""Core monitoring/checkout engine for the Lazada GUI bot (v2.1).

GUI-agnostic: the UI interacts through plain callbacks. Each task runs in its
own thread with its own Playwright browser context (+ optional proxy), so tasks
run truly in parallel and spread requests across IPs.
"""
import os
import random
import threading
import time

from playwright.sync_api import sync_playwright

import notifier
try:
    import captcha_solver
except Exception:
    captcha_solver = None

VERSION = "2.2"
SESSION_FILE = os.path.join(os.path.dirname(__file__), "lazada_session.json")
CHROME_CHANNEL = "chrome"

# ─── Centralized selectors (#14) — one place to update if Lazada changes ──
SEL = {
    "login_link": "a[data-spm-click*='locaid=login']",
    "account_trigger": "#myAccountTrigger",
    "phone_tab": ["li[data-role='tab'][data-tab='phone']", "[data-tab='phone']"],
    "phone_input": ["input[type='tel']", "input[name='phone']", "input[placeholder*='phone' i]"],
    "send_otp": [".iweb-button-mask"],
    "otp_cell": ".iweb-passcode-input-cell",
    "buy_cart_btns": ".add-to-cart-buy-now-btn",
    "sku_selector": ".sku-selector-v2",
    "sku_selected_header": ".sku-prop-content-header",
    "qty_plus": "i.next-icon-add",
    "captcha": [".nc-container", "#nc_1_wrapper", ".nc_iconfont", "#nocaptcha",
                ".J_MIDDLEWARE_FRAME_WIDGET", "iframe[src*='captcha']", "iframe[name*='captcha']"],
    "place_order_text": "Place Order",
    "thank_you": ".thank-you-heading",
    "thank_you_amount": ".thank-you-amount",
    "thank_you_order": ".thank-you-order-number",
}

# Anti-automation init script (#8 stealth).
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-SG','en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
window.chrome = window.chrome || {runtime: {}};
"""

_BLOCK_TYPES = {"image", "media", "font"}


def notify(text):
    try:
        notifier.send_message(text)
    except Exception:
        pass


# ─── Proxy parsing + health check (#7) ────────────────────────────

def parse_proxy(raw):
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    scheme = "http"
    if "://" in raw:
        scheme, raw = raw.split("://", 1)
    parts = raw.split(":")
    if len(parts) == 2:
        return {"server": f"{scheme}://{parts[0]}:{parts[1]}"}
    if len(parts) == 4:
        return {"server": f"{scheme}://{parts[0]}:{parts[1]}", "username": parts[2], "password": parts[3]}
    return None


def test_proxy(raw, timeout_ms=15000):
    """Return (ok, message) after trying to load a page through the proxy."""
    proxy = parse_proxy(raw)
    if not proxy:
        return (False, "unparseable")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel=CHROME_CHANNEL, headless=True)
            ctx = browser.new_context(proxy=proxy)
            page = ctx.new_page()
            t0 = time.time()
            page.goto("https://www.lazada.sg", wait_until="domcontentloaded", timeout=timeout_ms)
            ms = int((time.time() - t0) * 1000)
            browser.close()
            return (True, f"ok ({ms} ms)")
    except Exception as e:
        return (False, str(e).splitlines()[0][:80])


def human_pause(min_s=0.3, max_s=0.7):
    time.sleep(random.uniform(min_s, max_s))


# ─── CAPTCHA / login / stock / variant helpers ────────────────────

def check_for_captcha(page):
    try:
        url = (page.url or "").lower()
        if any(t in url for t in ["/punish", "captcha", "sec.lazada"]):
            return True
        for sel in SEL["captcha"]:
            el = page.query_selector(sel)
            if el and el.is_visible():
                return True
    except Exception:
        pass
    return False


def handle_captcha(page, log):
    """Try auto-solve (#9); returns True if solved, else False (manual needed)."""
    if captcha_solver and captcha_solver.available():
        log("attempting CAPTCHA auto-solve…")
        try:
            if captcha_solver.try_solve(page, log):
                return True
        except Exception as e:
            log(f"captcha solver error: {e}")
    return False


def is_logged_in(page):
    try:
        link = page.query_selector(SEL["login_link"])
        if link and link.is_visible():
            return False
        trig = page.query_selector(SEL["account_trigger"])
        if trig:
            return (trig.inner_text() or "").strip() != ""
        return False
    except Exception:
        return False


def _first(page, selectors):
    for s in selectors:
        el = page.query_selector(s)
        if el:
            return el
    return None


def select_variant(page, variant, log):
    if not variant:
        return True
    try:
        scope = page.locator(SEL["sku_selector"])
        loc = scope.get_by_text(variant, exact=True).first
        if loc.count() == 0:
            loc = page.get_by_text(variant, exact=True).first
        loc.wait_for(state="visible", timeout=5000)
        handle = loc.element_handle()
        if not handle:
            log(f"variant {variant!r} not found")
            return False
        page.evaluate(
            "(el) => { const w = el.closest('.sku-variable-img-wrap') || el.parentElement || el; w.click(); }",
            handle,
        )
        log(f"selected variant: {variant}")
        human_pause(0.6, 1.0)
        return True
    except Exception as e:
        log(f"could not select variant {variant!r}: {e}")
        return False


def select_payment(page, payment, log):
    """Select the payment method on the checkout page by its visible text
    (e.g. 'Lazada Wallet', 'Credit / Debit Card', 'Cash on Delivery'). Best-effort."""
    if not payment:
        return True
    try:
        loc = page.get_by_text(payment, exact=False).first
        loc.wait_for(state="visible", timeout=6000)
        try:
            loc.click(timeout=4000)
        except Exception:
            h = loc.element_handle()
            if h:
                page.evaluate(
                    "(el) => { const c = el.closest('label, [role=\"radio\"], li, div') || el; c.click(); }",
                    h,
                )
        log(f"selected payment: {payment}")
        human_pause(0.6, 1.2)
        return True
    except Exception as e:
        log(f"could not select payment {payment!r}: {e}")
        return False


def check_stock(page, url, variant, log):
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_selector(SEL["buy_cart_btns"], timeout=8000)
        except Exception:
            pass
        human_pause()
        if variant:
            select_variant(page, variant, log)
        if check_for_captcha(page):
            return ("captcha", None)

        buttons = page.query_selector_all(SEL["buy_cart_btns"])
        add_to_cart_btn = None
        buy_now_btn = None
        for btn in buttons:
            try:
                if not btn.is_visible():
                    continue
                text = btn.inner_text().strip().lower()
                if "add to cart" in text:
                    add_to_cart_btn = btn
                elif "buy now" in text:
                    buy_now_btn = btn
                elif "add to wishlist" in text:
                    return ("out_of_stock", None)
            except Exception:
                continue
        if add_to_cart_btn:
            return ("in_stock", buy_now_btn)
        return ("out_of_stock", None)
    except Exception as e:
        log(f"stock check error: {e}")
        return ("error", None)


def set_quantity(page, quantity, log):
    if quantity <= 1:
        return
    plus = page.query_selector(SEL["qty_plus"])
    if not plus:
        log("+ button not found — buying quantity 1")
        return
    for _ in range(quantity - 1):
        try:
            page.evaluate("(el) => el.click()", plus)
            human_pause(0.2, 0.4)
        except Exception:
            break


def complete_checkout(page, name, url, max_price, payment, log):
    """On the checkout page: wait for load, optional price guard, choose payment,
    Place Order, confirm. Returns 'ok' / 'retry' / 'stop'."""
    try:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        deadline = time.time() + 12
        while time.time() < deadline:
            try:
                probe = page.inner_text("body").lower()
            except Exception:
                probe = ""
            if "place order" in probe or "lazada wallet" in probe:
                break
            time.sleep(0.5)

        if check_for_captcha(page):
            if not handle_captcha(page, log):
                return "retry"

        safe = "".join(c if c.isalnum() else "_" for c in name)[:30]
        try:
            page.screenshot(path=os.path.join(os.path.dirname(__file__), f"checkout_{safe}.png"))
        except Exception:
            pass
        log(f"checkout page url: {page.url}")

        body = page.inner_text("body").lower()

        # Price guard (#1, kept): abort if total exceeds max_price.
        if max_price and max_price > 0:
            import re
            nums = [float(x.replace(",", "")) for x in re.findall(r"\$?\s*([\d,]+\.\d{2})", body)]
            total = max(nums) if nums else 0
            if total and total > max_price:
                log(f"ABORT: total {total} exceeds max price {max_price}")
                notify(f"⛔ *{name}* aborted — total ${total} over max ${max_price}")
                return "stop"

        # Select the chosen payment method, or keep whatever is pre-selected.
        if payment:
            select_payment(page, payment, log)

        place = page.get_by_text(SEL["place_order_text"], exact=False).first
        try:
            place.wait_for(state="visible", timeout=5000)
        except Exception:
            btns = []
            for b in page.query_selector_all("button, [role='button']"):
                try:
                    if b.is_visible():
                        t = b.inner_text().strip()
                        if t and len(t) < 50:
                            btns.append(t)
                except Exception:
                    pass
            log("Place Order not found. visible buttons: " + " | ".join(btns[:15]))
            return "retry"
        try:
            place.click(timeout=5000)
        except Exception:
            h = place.element_handle()
            if h:
                page.evaluate("(el) => el.click()", h)

        human_pause(3.0, 5.0)
        if check_for_captcha(page):
            handle_captcha(page, log)
        page.wait_for_timeout(2500)

        if page.query_selector(SEL["thank_you"]):
            amount = ""
            el = page.query_selector(SEL["thank_you_amount"])
            if el:
                amount = el.inner_text().strip()
            order_no = ""
            el = page.query_selector(SEL["thank_you_order"])
            if el:
                order_no = el.inner_text().strip()
            log(f"ORDER PLACED #{order_no} SGD {amount}")
            notifier.send_event(
                "🎉 Order Placed!", description=name, color=0x2ECC71, url=url,
                fields={"Order": order_no or "—", "Amount": f"SGD {amount or '?'}"}, ping=True,
            )
            _record_order(name, order_no, amount)
            return "ok"

        log("clicked Place Order but could not confirm")
        notify(f"⚠️ *Check your order* for *{name}* — clicked Place Order, unconfirmed.\n{url}")
        return "stop"
    except Exception as e:
        log(f"checkout error: {e}")
        return "retry"


def _record_order(name, order_no, amount):
    try:
        with open(os.path.join(os.path.dirname(__file__), "orders.log"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{name}\t{order_no}\t{amount}\n")
    except Exception:
        pass


# ─── Context builders ─────────────────────────────────────────────

def _decorate(context):
    try:
        context.add_init_script(_STEALTH_JS)
    except Exception:
        pass
    try:
        context.route("**/*", lambda route: (
            route.abort() if route.request.resource_type in _BLOCK_TYPES else route.continue_()
        ))
    except Exception:
        pass


def _new_context(playwright, proxy_dict, load_session=True):
    browser = playwright.chromium.launch(
        channel=CHROME_CHANNEL, headless=False,
        args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"],
    )
    ctx_args = {
        "viewport": {"width": 1280, "height": 800},
        "user_agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
        "locale": "en-SG", "timezone_id": "Asia/Singapore",
    }
    if proxy_dict:
        ctx_args["proxy"] = proxy_dict
    if load_session and os.path.exists(SESSION_FILE):
        ctx_args["storage_state"] = SESSION_FILE
    context = browser.new_context(**ctx_args)
    _decorate(context)
    return browser, context


# ─── Shared login ─────────────────────────────────────────────────

class LoginManager:
    def __init__(self, phone, get_otp, log, proxy_raw=""):
        self.phone = phone
        self.get_otp = get_otp
        self.log = log
        self.proxy = parse_proxy(proxy_raw)

    def run(self):
        with sync_playwright() as p:
            browser, context = _new_context(p, self.proxy, load_session=False)
            try:
                context.add_init_script(_STEALTH_JS)
            except Exception:
                pass
            page = context.new_page()
            try:
                self.log("Opening Lazada…")
                page.goto("https://www.lazada.sg/#?", wait_until="domcontentloaded", timeout=30000)
                human_pause(1.5, 2.5)
                if is_logged_in(page):
                    self.log("Already logged in (saved session).")
                    context.storage_state(path=SESSION_FILE)
                    return True

                self.log("Clicking Login…")
                btn = page.query_selector(SEL["login_link"])
                if not btn:
                    self.log("Login button not found.")
                    return False
                btn.click(); human_pause(1.5, 2.5)

                self.log("Selecting phone tab…")
                tab = _first(page, SEL["phone_tab"]) or page.get_by_text("Phone Number", exact=False)
                if tab:
                    try:
                        tab.click()
                    except Exception:
                        pass
                human_pause(1, 1.5)

                self.log("Entering phone number…")
                pin = _first(page, SEL["phone_input"])
                if not pin:
                    self.log("Phone input not found.")
                    return False
                pin.click(); human_pause(0.4, 0.8); pin.fill(self.phone); human_pause(1, 1.5)

                self.log("Requesting SMS code…")
                send = _first(page, SEL["send_otp"]) or page.get_by_text("Send code via SMS", exact=False)
                if send:
                    try:
                        send.click()
                    except Exception:
                        pass
                human_pause(2, 3)

                self.log("Waiting for OTP…")
                otp = self.get_otp()
                if not otp:
                    self.log("No OTP received — login aborted.")
                    return False

                cells = page.query_selector_all(SEL["otp_cell"])
                if cells:
                    for i, digit in enumerate(otp):
                        if i >= len(cells):
                            break
                        cells[i].click(); human_pause(0.15, 0.3)
                        page.keyboard.type(digit); human_pause(0.1, 0.25)
                human_pause(3, 4)

                if check_for_captcha(page):
                    handle_captcha(page, self.log)
                    self.log("If a CAPTCHA is shown, solve it in the window…")
                    for _ in range(60):
                        if is_logged_in(page):
                            break
                        time.sleep(2)

                page.wait_for_timeout(2500)
                if not is_logged_in(page):
                    self.log("Login FAILED — still showing logged-out (check OTP / CAPTCHA).")
                    return False

                trig = page.query_selector(SEL["account_trigger"])
                who = trig.inner_text().strip() if trig else "account"
                self.log(f"Logged in as: {who}")
                notifier.send_event("✅ Logged in", description=who, color=0x3498DB)
                context.storage_state(path=SESSION_FILE)
                return True
            except Exception as e:
                self.log(f"login error: {e}")
                return False
            finally:
                try:
                    browser.close()
                except Exception:
                    pass


# ─── Per-product task worker ──────────────────────────────────────

class TaskWorker(threading.Thread):
    def __init__(self, task, on_log, on_status, on_needs_login=None):
        super().__init__(daemon=True)
        self.task = task
        self.on_log = on_log
        self.on_status = on_status
        self.on_needs_login = on_needs_login or (lambda name: None)
        self._stop = threading.Event()
        self.purchased = False

    def log(self, m):
        self.on_log(self.task["name"], m)

    def status(self, s):
        self.on_status(self.task["name"], s)

    def stop(self):
        self._stop.set()

    # -- scheduled start (#11) --
    def _await_schedule(self):
        start_at = (self.task.get("start_at") or "").strip()
        if not start_at:
            return
        try:
            import datetime as dt
            hh, mm = [int(x) for x in start_at.split(":")]
            now = dt.datetime.now()
            target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if target <= now:
                target += dt.timedelta(days=1)
            self.status(f"scheduled {start_at}")
            self.log(f"waiting until {target.strftime('%Y-%m-%d %H:%M')}")
            while not self._stop.is_set() and dt.datetime.now() < target:
                time.sleep(1)
        except Exception as e:
            self.log(f"bad start time {start_at!r}: {e}")

    # -- session auto-recovery (#4): wait for the session file to refresh --
    def _wait_for_relogin(self, prev_mtime):
        self.status("session expired — re-login needed")
        self.on_needs_login(self.task["name"])
        notify(f"🔑 *{self.task['name']}*: session expired — please re-login.")
        waited = 0
        while not self._stop.is_set() and waited < 300:
            try:
                if os.path.exists(SESSION_FILE) and os.path.getmtime(SESSION_FILE) > prev_mtime:
                    self.log("session refreshed — resuming")
                    return True
            except Exception:
                pass
            time.sleep(2); waited += 2
        return False

    def run(self):
        name = self.task["name"]
        url = self.task["url"]
        qty = int(self.task.get("quantity", 1) or 1)
        interval = float(self.task.get("interval", 8) or 8)
        variant = (self.task.get("variant") or "").strip()
        proxy = parse_proxy(self.task.get("proxy", ""))
        alert_only = bool(self.task.get("alert_only"))
        max_price = float(self.task.get("max_price") or 0)
        payment = (self.task.get("payment") or "").strip()

        self._await_schedule()
        login_verified = False
        announced_stock = False
        fails = 0

        while not self._stop.is_set() and not self.purchased:
            try:
                with sync_playwright() as p:
                    browser, context = _new_context(p, proxy)
                    page = context.new_page()
                    rebuild = False
                    try:
                        while not self._stop.is_set() and not self.purchased:
                            self.status("checking")
                            result, buy_btn = check_stock(page, url, variant, self.log)

                            if result == "captcha":
                                self.status("CAPTCHA")
                                if not handle_captcha(page, self.log):
                                    notify(f"⚠️ *CAPTCHA* on *{name}* — solve in window.")
                                    self._wait(30)
                                continue

                            if result in ("in_stock", "out_of_stock") and not login_verified:
                                if is_logged_in(page):
                                    login_verified = True
                                    self.log("session authenticated ✓")
                                else:
                                    prev = os.path.getmtime(SESSION_FILE) if os.path.exists(SESSION_FILE) else 0
                                    rebuild = self._wait_for_relogin(prev)
                                    break  # leave inner loop to rebuild context

                            if result == "in_stock":
                                if alert_only:
                                    if not announced_stock:
                                        announced_stock = True
                                        self.status("IN STOCK (alert only)")
                                        notifier.send_event("🟢 In Stock", description=name, url=url,
                                                            color=0x2ECC71, ping=True)
                                    self._wait(interval); continue
                                announced_stock = False
                                self.status("IN STOCK — buying")
                                notifier.send_event("🟢 In Stock — buying", description=name, url=url,
                                                    color=0xF1C40F, fields={"Qty": qty}, ping=True)
                                if not buy_btn:
                                    self.log("Buy Now missing despite stock")
                                    self._wait(interval); continue
                                set_quantity(page, qty, self.log)
                                human_pause(0.5, 1.0)
                                try:
                                    buy_btn.click()
                                except Exception as e:
                                    self.log(f"buy click failed: {e}")
                                    self._wait(interval); continue
                                human_pause(2, 3)

                                self.status("checking out")
                                outcome = complete_checkout(page, name, url, max_price, payment, self.log)
                                if outcome == "ok":
                                    self.purchased = True
                                    self.status("purchased ✓")
                                    self.log("done — buy-once guard engaged")
                                    return
                                elif outcome == "stop":
                                    self.status("checkout stopped")
                                    return
                                else:  # retry (#6)
                                    fails += 1
                                    if fails >= 3:
                                        self.status("checkout failed — stopped")
                                        self.log("3 checkout attempts failed — stopping.")
                                        notify(f"⚠️ *{name}*: checkout failed 3× — stopped.")
                                        return
                                    self.log(f"checkout retry {fails}/3")
                                    self._wait(min(interval, 5)); continue
                            else:
                                announced_stock = False
                                self.status("out of stock")
                                self._wait(interval)
                    finally:
                        try:
                            browser.close()
                        except Exception:
                            pass
                    if not rebuild:
                        break
                    if not self._wait_for_relogin_done():
                        break
                    login_verified = False
            except Exception as e:
                self.log(f"worker error: {e}; retrying in 15s")
                self._wait(15)

    def _wait_for_relogin_done(self):
        # _wait_for_relogin already blocked until refresh; just confirm not stopped.
        return not self._stop.is_set()

    def _wait(self, seconds):
        seconds = seconds + random.uniform(0, max(0.0, seconds * 0.25))
        end = time.time() + seconds
        while time.time() < end and not self._stop.is_set():
            time.sleep(0.2)


# ─── Self-test (#14): validate selectors against a live PDP ────────

def self_test(url, log):
    log("self-test: launching…")
    report = []
    try:
        with sync_playwright() as p:
            browser, context = _new_context(p, None)
            page = context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2500)
                checks = {
                    "buy/cart buttons": SEL["buy_cart_btns"],
                    "account trigger": SEL["account_trigger"],
                    "sku selector": SEL["sku_selector"],
                }
                for label, sel in checks.items():
                    ok = page.query_selector(sel) is not None
                    report.append(f"{'✓' if ok else '✗'} {label} ({sel})")
                report.append(f"logged in: {is_logged_in(page)}")
            finally:
                browser.close()
    except Exception as e:
        report.append(f"self-test error: {e}")
    for line in report:
        log("self-test: " + line)
    return report
