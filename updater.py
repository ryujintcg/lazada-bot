"""In-app self-update.

You (the dev) host a small JSON manifest somewhere stable (GitHub raw, a gist,
or any URL). When you roll a new version, bump VERSION in engine.py, rebuild the
share zip, upload it, and point the manifest's "url" at it + bump "version".
Every user's bot polls the manifest and offers a one-click update.

Manifest format (version.json):
    {"version": "2.3", "url": "https://.../Lazada-Bot-Share.zip", "notes": "what changed"}

Set the manifest URL below (or override via UPDATE_URL in config.py).
"""
import json
import os
import tempfile
import urllib.request
import zipfile

HERE = os.path.dirname(__file__)

# Dev: set this to your hosted version.json URL. Empty = update checks disabled.
# Concrete default points at the GitHub repo's raw manifest. Change owner/repo or
# branch (main vs master) if yours differs; or override via UPDATE_URL in config.py.
UPDATE_URL = "https://raw.githubusercontent.com/ryujintcg/lazada-bot/main/version.json"
try:
    from config import UPDATE_URL as _CFG_URL
    if _CFG_URL:
        UPDATE_URL = _CFG_URL
except Exception:
    pass

# Only these files are ever overwritten by an update — never config.py,
# bot_data.json, or lazada_session.json (your data/secrets stay put).
UPDATE_FILES = {
    "gui_app.py", "engine.py", "notifier.py", "captcha_solver.py", "updater.py",
    "requirements.txt", "run_gui.bat", "SETUP.md", "CHANGELOG.md", "config.example.py",
}


def _ver(v):
    parts = []
    for x in str(v).split("."):
        try:
            parts.append(int(x))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def check(current_version):
    """Return (update_available: bool, info: dict). info has 'error' on failure."""
    if not UPDATE_URL:
        return (False, {"error": "no update URL configured"})
    try:
        req = urllib.request.Request(UPDATE_URL, headers={"User-Agent": "LazadaBot"})
        with urllib.request.urlopen(req, timeout=10) as r:
            info = json.loads(r.read().decode("utf-8"))
        latest = info.get("version", "")
        info["available"] = _ver(latest) > _ver(current_version)
        return (info["available"], info)
    except Exception as e:
        return (False, {"error": str(e)})


def apply(info, log):
    """Download the update zip and overwrite the whitelisted app files."""
    url = info.get("url")
    if not url:
        log("update has no download URL")
        return False
    try:
        tmp = tempfile.mkdtemp()
        zpath = os.path.join(tmp, "update.zip")
        log("downloading update…")
        req = urllib.request.Request(url, headers={"User-Agent": "LazadaBot"})
        with urllib.request.urlopen(req, timeout=60) as r, open(zpath, "wb") as f:
            f.write(r.read())
        updated = 0
        with zipfile.ZipFile(zpath) as z:
            for member in z.namelist():
                base = os.path.basename(member)
                if base in UPDATE_FILES:
                    with z.open(member) as src, open(os.path.join(HERE, base), "wb") as dst:
                        dst.write(src.read())
                    updated += 1
                    log(f"updated {base}")
        log(f"update complete — {updated} file(s)")
        return updated > 0
    except Exception as e:
        log(f"update failed: {e}")
        return False
