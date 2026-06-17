import os
import re
import requests

# Bot-token fields are optional/legacy — webhook is the preferred path.
try:
    from config import DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID
except Exception:
    DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID = "", ""

API = "https://discord.com/api/v10"

_webhook_url = ""
_role_id = ""


def set_webhook(url):
    global _webhook_url
    _webhook_url = (url or "").strip()


def get_webhook():
    return _webhook_url


def set_role(role_id):
    global _role_id
    _role_id = (role_id or "").strip()


def get_role():
    return _role_id


def _to_discord(text):
    """Convert Telegram-style *bold* markup to Discord **bold**."""
    return re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"**\1**", text)


def _bot_configured():
    return (DISCORD_BOT_TOKEN and "your_discord" not in DISCORD_BOT_TOKEN
            and DISCORD_CHANNEL_ID and "your_discord" not in str(DISCORD_CHANNEL_ID))


def _post(payload):
    if _webhook_url:
        try:
            r = requests.post(_webhook_url, json=payload, timeout=10)
            if not r.ok:
                print(f"Discord webhook error {r.status_code}: {r.text}")
            return r.ok
        except Exception as e:
            print(f"Discord webhook error: {e}")
            return False
    if _bot_configured():
        try:
            r = requests.post(
                f"{API}/channels/{DISCORD_CHANNEL_ID}/messages",
                headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}"},
                json=payload, timeout=10,
            )
            if not r.ok:
                print(f"Discord send error {r.status_code}: {r.text}")
            return r.ok
        except Exception as e:
            print(f"Discord send error: {e}")
            return False
    return False


def send_message(text):
    """Plain text notification (no-op if nothing configured)."""
    return _post({"content": _to_discord(text)})


def send_event(title, description="", fields=None, color=0x2ECC71, url=None, ping=False):
    """Rich embed notification with optional product link and role @ping."""
    embed = {"title": title, "color": color}
    if description:
        embed["description"] = _to_discord(description)
    if url:
        embed["url"] = url
    if fields:
        embed["fields"] = [{"name": k, "value": str(v), "inline": True} for k, v in fields.items()]
    payload = {"embeds": [embed]}
    if ping and _role_id:
        payload["content"] = f"<@&{_role_id}>"
        payload["allowed_mentions"] = {"roles": [_role_id]}
    return _post(payload)


def send_file(path, content=""):
    """Upload an image/file to the webhook (e.g. a PayNow QR screenshot)."""
    if not _webhook_url or not os.path.exists(path):
        return False
    try:
        with open(path, "rb") as fh:
            files = {"file": (os.path.basename(path), fh, "image/png")}
            data = {}
            if content:
                data["content"] = _to_discord(content)[:1900]
            if _role_id and content:
                data["content"] = f"<@&{_role_id}> " + data["content"]
            r = requests.post(_webhook_url, data=data, files=files, timeout=20)
            if not r.ok:
                print(f"Discord file error {r.status_code}: {r.text}")
            return r.ok
    except Exception as e:
        print(f"Discord file error: {e}")
        return False
