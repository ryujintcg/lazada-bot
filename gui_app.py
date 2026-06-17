"""PyQt6 GUI for the Lazada multi-task checkout bot (v2.1)."""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import json
import os
import queue
import subprocess
import threading
from datetime import datetime

from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTableWidget, QTableWidgetItem, QTextEdit, QDialog, QLineEdit,
    QSpinBox, QDoubleSpinBox, QFormLayout, QPlainTextEdit, QInputDialog,
    QMessageBox, QHeaderView, QComboBox, QCheckBox,
)

import engine
import notifier
import updater

PAYMENTS = ["", "Lazada Wallet", "Credit / Debit Card", "Cash on Delivery",
            "PayLater", "GrabPay", "Bank Transfer"]

HERE = os.path.dirname(__file__)
DATA_FILE = os.path.join(HERE, "bot_data.json")
LOG_FILE = os.path.join(HERE, "bot.log")
CHANGELOG = os.path.join(HERE, "CHANGELOG.md")

COLS = ["Name", "Product URL", "Variant", "Qty", "Proxy", "Interval", "Alert", "Status", ""]
C_NAME, C_URL, C_VAR, C_QTY, C_PROXY, C_INT, C_ALERT, C_STATUS, C_ACT = range(9)


def load_phone():
    try:
        from config import LAZADA_PHONE
        return LAZADA_PHONE
    except Exception:
        return ""


class Bridge(QObject):
    log = pyqtSignal(str, str)
    status = pyqtSignal(str, str)
    otp_request = pyqtSignal()
    login_done = pyqtSignal(bool, str)
    needs_login = pyqtSignal(str)
    update_found = pyqtSignal(dict)
    update_done = pyqtSignal(bool, str)


# ─── Task dialog ──────────────────────────────────────────────────

class TaskDialog(QDialog):
    def __init__(self, parent, proxies, task=None):
        super().__init__(parent)
        self.setWindowTitle("Task")
        self.resize(580, 0)
        form = QFormLayout(self)
        t = task or {}
        self.name = QLineEdit(t.get("name", ""))
        self.url = QLineEdit(t.get("url", ""))
        self.variant = QLineEdit(t.get("variant", ""))
        self.variant.setPlaceholderText("exact option text, e.g. Sealed ETB — blank if none")
        self.qty = QSpinBox(); self.qty.setRange(1, 99); self.qty.setValue(int(t.get("quantity", 1)))
        self.interval = QSpinBox(); self.interval.setRange(2, 600); self.interval.setValue(int(t.get("interval", 8)))
        self.maxprice = QDoubleSpinBox(); self.maxprice.setRange(0, 100000); self.maxprice.setDecimals(2)
        self.maxprice.setValue(float(t.get("max_price", 0))); self.maxprice.setSpecialValueText("no limit")
        self.start_at = QLineEdit(t.get("start_at", "")); self.start_at.setPlaceholderText("HH:MM (24h) — blank = now")
        self.alert_only = QCheckBox("Alert only (notify, don't auto-buy)")
        self.alert_only.setChecked(bool(t.get("alert_only")))
        self.payment = QComboBox(); self.payment.setEditable(True)
        for pm in PAYMENTS:
            self.payment.addItem(pm)
        self.payment.setEditText(t.get("payment", ""))
        self.proxy = QComboBox(); self.proxy.setEditable(True); self.proxy.addItem("")
        for px in proxies:
            self.proxy.addItem(px)
        if t.get("proxy"):
            self.proxy.setEditText(t["proxy"])

        form.addRow("Name", self.name)
        form.addRow("Product URL", self.url)
        form.addRow("Variant / Option", self.variant)
        form.addRow("Quantity", self.qty)
        form.addRow("Check interval (s)", self.interval)
        form.addRow("Max price ($)", self.maxprice)
        form.addRow("Scheduled start", self.start_at)
        form.addRow("Payment method", self.payment)
        form.addRow("", self.alert_only)
        form.addRow("Proxy", self.proxy)

        row = QHBoxLayout()
        ok = QPushButton("Save"); cancel = QPushButton("Cancel")
        ok.clicked.connect(self.accept); cancel.clicked.connect(self.reject)
        row.addStretch(1); row.addWidget(cancel); row.addWidget(ok)
        form.addRow(row)

    def get_task(self):
        return {
            "name": self.name.text().strip(),
            "url": self.url.text().strip(),
            "variant": self.variant.text().strip(),
            "quantity": self.qty.value(),
            "interval": self.interval.value(),
            "max_price": self.maxprice.value(),
            "start_at": self.start_at.text().strip(),
            "payment": self.payment.currentText().strip(),
            "alert_only": self.alert_only.isChecked(),
            "proxy": self.proxy.currentText().strip(),
        }


# ─── Proxy dialog (with health test) ──────────────────────────────

class ProxyDialog(QDialog):
    def __init__(self, parent, proxies):
        super().__init__(parent)
        self.parent_win = parent
        self.setWindowTitle("Proxy pool")
        self.resize(540, 420)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("One per line — host:port or host:port:user:pass"))
        self.text = QPlainTextEdit("\n".join(proxies))
        lay.addWidget(self.text)
        row = QHBoxLayout()
        test = QPushButton("Test all (background)"); test.clicked.connect(self._test)
        ok = QPushButton("Save"); cancel = QPushButton("Cancel")
        ok.clicked.connect(self.accept); cancel.clicked.connect(self.reject)
        row.addWidget(test); row.addStretch(1); row.addWidget(cancel); row.addWidget(ok)
        lay.addLayout(row)

    def _test(self):
        proxies = [ln.strip() for ln in self.text.toPlainText().splitlines() if ln.strip()]
        if not proxies:
            return
        self.parent_win.test_proxies(proxies)
        QMessageBox.information(self, "Testing", "Testing in background — results appear in the log.")

    def get_proxies(self):
        return [ln.strip() for ln in self.text.toPlainText().splitlines() if ln.strip()]


# ─── Discord webhook dialog (with role ping) ──────────────────────

class WebhookDialog(QDialog):
    def __init__(self, parent, url, role):
        super().__init__(parent)
        self.setWindowTitle("Discord notifications")
        self.resize(600, 0)
        form = QFormLayout(self)
        form.addRow(QLabel("Channel → Edit → Integrations → Webhooks → New Webhook → Copy URL"))
        self.url = QLineEdit(url); self.url.setPlaceholderText("https://discord.com/api/webhooks/...")
        self.role = QLineEdit(role); self.role.setPlaceholderText("optional role ID to @ping on stock/order")
        form.addRow("Webhook URL", self.url)
        form.addRow("Ping role ID", self.role)
        row = QHBoxLayout()
        test = QPushButton("Send test"); test.clicked.connect(self._test)
        ok = QPushButton("Save"); cancel = QPushButton("Cancel")
        ok.clicked.connect(self.accept); cancel.clicked.connect(self.reject)
        row.addWidget(test); row.addStretch(1); row.addWidget(cancel); row.addWidget(ok)
        form.addRow(row)

    def _test(self):
        u = self.url.text().strip()
        if not u:
            QMessageBox.warning(self, "No URL", "Enter a webhook URL first."); return
        pw, pr = notifier.get_webhook(), notifier.get_role()
        notifier.set_webhook(u); notifier.set_role(self.role.text().strip())
        ok = notifier.send_event("✅ Lazada Bot test", description="Notifications are working!", color=0x3498DB)
        notifier.set_webhook(pw); notifier.set_role(pr)
        QMessageBox.information(self, "Test", "Sent — check Discord." if ok else "Failed — check the URL.")

    def get(self):
        return self.url.text().strip(), self.role.text().strip()


# ─── Changelog viewer ─────────────────────────────────────────────

class ChangelogDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Changelog / Updates")
        self.resize(560, 480)
        lay = QVBoxLayout(self)
        view = QTextEdit(); view.setReadOnly(True)
        try:
            view.setPlainText(open(CHANGELOG, encoding="utf-8").read())
        except Exception:
            view.setPlainText("No changelog found.")
        lay.addWidget(view)
        close = QPushButton("Close"); close.clicked.connect(self.accept)
        lay.addWidget(close)


# ─── Main window ──────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Lazada Bot — Multi-Task  v{engine.VERSION}")
        self.resize(1180, 680)

        self.tasks = []
        self.proxies = []
        self.workers = {}
        self.row_for = {}
        self.logged_in = False
        self.webhook_url = ""
        self.role_id = ""
        self.otp_queue = queue.Queue()
        self._login_busy = False

        self.bridge = Bridge()
        self.bridge.log.connect(self.on_log)
        self.bridge.status.connect(self.on_status)
        self.bridge.otp_request.connect(self.on_otp_request)
        self.bridge.login_done.connect(self.on_login_done)
        self.bridge.needs_login.connect(self.on_needs_login)
        self.bridge.update_found.connect(self.on_update_found)
        self.bridge.update_done.connect(self._finish_update)

        self._build_ui()
        self._load()
        # Check for updates in the background on startup.
        threading.Thread(target=self._check_updates_bg, args=(False,), daemon=True).start()

    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        root = QVBoxLayout(central)

        bar = QHBoxLayout()
        self.login_btn = QPushButton("🔐 Login"); self.login_btn.clicked.connect(self.do_login)
        self.login_lbl = QLabel("Not logged in")
        bar.addWidget(self.login_btn); bar.addWidget(self.login_lbl); bar.addStretch(1)
        for text, fn in [
            ("➕ Add", self.add_task), ("✎ Edit", self.edit_task), ("🗑 Remove", self.remove_task),
            ("🌐 Proxies…", self.manage_proxies), ("🔔 Discord…", self.manage_webhook),
            ("🧪 Self-test", self.run_self_test), ("📋 Changelog", self.show_changelog),
            ("⬇ Updates", self.check_updates),
            ("▶ Start All", self.start_all), ("■ Stop All", self.stop_all),
        ]:
            b = QPushButton(text); b.clicked.connect(fn); bar.addWidget(b)
        root.addLayout(bar)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.horizontalHeader().setSectionResizeMode(C_URL, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        root.addWidget(self.table, 3)

        root.addWidget(QLabel("Log"))
        self.logview = QTextEdit(); self.logview.setReadOnly(True)
        root.addWidget(self.logview, 2)

    # ---- persistence ----
    def _load(self):
        if os.path.exists(DATA_FILE):
            try:
                data = json.load(open(DATA_FILE, encoding="utf-8"))
                self.tasks = data.get("tasks", [])
                self.proxies = data.get("proxies", [])
                self.webhook_url = data.get("webhook", "")
                self.role_id = data.get("role", "")
                notifier.set_webhook(self.webhook_url); notifier.set_role(self.role_id)
            except Exception:
                pass
        if os.path.exists(engine.SESSION_FILE):
            self.logged_in = True
            self.login_lbl.setText("Session found (login to refresh)")
        self._refresh_table()

    def _save(self):
        json.dump({"tasks": self.tasks, "proxies": self.proxies,
                   "webhook": self.webhook_url, "role": self.role_id},
                  open(DATA_FILE, "w", encoding="utf-8"), indent=2)

    def _refresh_table(self):
        self.table.setRowCount(0); self.row_for.clear()
        for t in self.tasks:
            r = self.table.rowCount(); self.table.insertRow(r)
            self.row_for[t["name"]] = r
            self.table.setItem(r, C_NAME, QTableWidgetItem(t["name"]))
            self.table.setItem(r, C_URL, QTableWidgetItem(t["url"]))
            self.table.setItem(r, C_VAR, QTableWidgetItem(t.get("variant", "") or "—"))
            self.table.setItem(r, C_QTY, QTableWidgetItem(str(t.get("quantity", 1))))
            self.table.setItem(r, C_PROXY, QTableWidgetItem(t.get("proxy", "") or "—"))
            self.table.setItem(r, C_INT, QTableWidgetItem(str(t.get("interval", 8)) + "s"))
            self.table.setItem(r, C_ALERT, QTableWidgetItem("alert" if t.get("alert_only") else "buy"))
            self.table.setItem(r, C_STATUS, QTableWidgetItem("idle"))
            btn = QPushButton("▶ Start")
            btn.clicked.connect(lambda _, n=t["name"]: self.toggle_task(n))
            self.table.setCellWidget(r, C_ACT, btn)

    # ---- logging ----
    def log_line(self, who, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] [{who}] {msg}"
        self.logview.append(line)
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def on_log(self, name, msg):
        self.log_line(name, msg)

    def on_status(self, name, status):
        r = self.row_for.get(name)
        if r is not None:
            self.table.setItem(r, C_STATUS, QTableWidgetItem(status))
        self.log_line(name, f"status → {status}")
        if status.startswith("purchased") or status.startswith("checkout") or status.startswith("error"):
            self._set_row_button(name, start=True)
            self.workers.pop(name, None)

    def _set_row_button(self, name, start):
        r = self.row_for.get(name)
        if r is None:
            return
        btn = self.table.cellWidget(r, C_ACT)
        if btn:
            btn.setText("▶ Start" if start else "■ Stop")

    # ---- login ----
    def do_login(self):
        if self._login_busy:
            return
        phone = load_phone()
        if not phone:
            QMessageBox.warning(self, "No phone", "Set LAZADA_PHONE in config.py first."); return
        self._login_busy = True
        self.login_btn.setEnabled(False); self.login_lbl.setText("Logging in…")

        def get_otp():
            while not self.otp_queue.empty():
                try: self.otp_queue.get_nowait()
                except Exception: break
            self.bridge.otp_request.emit()
            try:
                return self.otp_queue.get(timeout=300)
            except Exception:
                return None

        def run():
            ok = engine.LoginManager(phone=phone, get_otp=get_otp,
                                     log=lambda m: self.bridge.log.emit("login", m)).run()
            self.bridge.login_done.emit(ok, "")

        threading.Thread(target=run, daemon=True).start()

    def on_otp_request(self):
        otp, ok = QInputDialog.getText(self, "OTP", "Enter the SMS code:")
        self.otp_queue.put(otp.strip() if ok else None)

    def on_login_done(self, ok, _msg):
        self._login_busy = False
        self.login_btn.setEnabled(True)
        self.logged_in = ok
        self.login_lbl.setText("✅ Logged in — session saved" if ok else "❌ Login failed (see log)")

    def on_needs_login(self, name):
        # Session expired for a task — auto-trigger one login.
        self.log_line(name, "requested re-login")
        if not self._login_busy:
            self.do_login()

    # ---- task CRUD ----
    def _selected_name(self):
        r = self.table.currentRow()
        if r < 0:
            return None
        item = self.table.item(r, C_NAME)
        return item.text() if item else None

    def add_task(self):
        dlg = TaskDialog(self, self.proxies)
        if dlg.exec():
            t = dlg.get_task()
            if not t["name"] or not t["url"]:
                QMessageBox.warning(self, "Missing", "Name and URL are required."); return
            if any(x["name"] == t["name"] for x in self.tasks):
                QMessageBox.warning(self, "Duplicate", "A task with that name exists."); return
            self.tasks.append(t); self._save(); self._refresh_table()

    def edit_task(self):
        name = self._selected_name()
        if not name:
            return
        if name in self.workers:
            QMessageBox.information(self, "Running", "Stop the task before editing."); return
        t = next(x for x in self.tasks if x["name"] == name)
        dlg = TaskDialog(self, self.proxies, t)
        if dlg.exec():
            t.update(dlg.get_task()); self._save(); self._refresh_table()

    def remove_task(self):
        name = self._selected_name()
        if not name:
            return
        if name in self.workers:
            self.stop_task(name)
        self.tasks = [x for x in self.tasks if x["name"] != name]
        self._save(); self._refresh_table()

    def manage_proxies(self):
        dlg = ProxyDialog(self, self.proxies)
        if dlg.exec():
            self.proxies = dlg.get_proxies(); self._save()
            self.log_line("proxies", f"{len(self.proxies)} saved")

    def test_proxies(self, proxies):
        def run():
            for px in proxies:
                ok, msg = engine.test_proxy(px)
                self.bridge.log.emit("proxy-test", f"{'✓' if ok else '✗'} {px} — {msg}")
        threading.Thread(target=run, daemon=True).start()

    def manage_webhook(self):
        dlg = WebhookDialog(self, self.webhook_url, self.role_id)
        if dlg.exec():
            self.webhook_url, self.role_id = dlg.get()
            notifier.set_webhook(self.webhook_url); notifier.set_role(self.role_id)
            self._save()
            self.log_line("discord", "settings saved")

    def run_self_test(self):
        name = self._selected_name()
        default = next((x["url"] for x in self.tasks if x["name"] == name), "") if name else ""
        url, ok = QInputDialog.getText(self, "Self-test", "Product URL to validate selectors:", text=default)
        if not ok or not url.strip():
            return
        threading.Thread(target=lambda: engine.self_test(
            url.strip(), lambda m: self.bridge.log.emit("self-test", m)), daemon=True).start()

    def show_changelog(self):
        ChangelogDialog(self).exec()

    # ---- run control ----
    def toggle_task(self, name):
        if name in self.workers:
            self.stop_task(name)
        else:
            self.start_task(name)

    def start_task(self, name):
        if name in self.workers:
            return
        if not self.logged_in and not os.path.exists(engine.SESSION_FILE):
            QMessageBox.warning(self, "Not logged in", "Login first so tasks can check out."); return
        task = next(x for x in self.tasks if x["name"] == name)
        worker = engine.TaskWorker(
            task,
            on_log=lambda n, m: self.bridge.log.emit(n, m),
            on_status=lambda n, s: self.bridge.status.emit(n, s),
            on_needs_login=lambda n: self.bridge.needs_login.emit(n),
        )
        self.workers[name] = worker
        worker.start()
        self._set_row_button(name, start=False)
        self.log_line(name, "started")

    def stop_task(self, name):
        w = self.workers.pop(name, None)
        if w:
            w.stop(); self.log_line(name, "stopping…")
        self._set_row_button(name, start=True)
        r = self.row_for.get(name)
        if r is not None:
            self.table.setItem(r, C_STATUS, QTableWidgetItem("idle"))

    def start_all(self):
        for t in self.tasks:
            self.start_task(t["name"])

    def stop_all(self):
        for name in list(self.workers.keys()):
            self.stop_task(name)

    # ---- updates ----
    def check_updates(self):
        """Manual check (toolbar button)."""
        threading.Thread(target=self._check_updates_bg, args=(True,), daemon=True).start()

    def _check_updates_bg(self, manual):
        available, info = updater.check(engine.VERSION)
        if available:
            self.bridge.update_found.emit(info)
        elif manual:
            err = info.get("error")
            msg = f"Update check failed: {err}" if err else f"You're up to date (v{engine.VERSION})."
            self.bridge.log.emit("update", msg)

    def on_update_found(self, info):
        latest = info.get("version", "?")
        notes = info.get("notes", "")
        ans = QMessageBox.question(
            self, "Update available",
            f"Version {latest} is available (you have {engine.VERSION}).\n\n{notes}\n\nUpdate now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        def run():
            ok = updater.apply(info, lambda m: self.bridge.log.emit("update", m))
            self.bridge.update_done.emit(ok, latest)

        threading.Thread(target=run, daemon=True).start()

    def _finish_update(self, ok, latest):
        if ok:
            r = QMessageBox.question(
                self, "Updated", f"Updated to v{latest}. Restart now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if r == QMessageBox.StandardButton.Yes:
                self._restart()
        else:
            QMessageBox.warning(self, "Update failed", "Could not apply the update — see the log.")

    def _restart(self):
        try:
            subprocess.Popen([sys.executable, os.path.join(HERE, "gui_app.py")])
        except Exception as e:
            self.log_line("update", f"restart failed: {e}")
        self.close()

    def closeEvent(self, event):
        self.stop_all(); self._save(); event.accept()


def main():
    app = QApplication(sys.argv)
    w = MainWindow(); w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
