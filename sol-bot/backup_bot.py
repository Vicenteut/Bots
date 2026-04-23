#!/usr/bin/env python3
"""
Sol Bot Backup Script
Backs up critical bot files, rotates old backups, notifies via Telegram.

Cron recommendation (weekly Sunday 3 AM CST):
  0 3 * * 0 /usr/bin/python3 /root/x-bot/backup_bot.py >> /root/x-bot/backups/backup.log 2>&1

Usage:
  python3 backup_bot.py            # run backup
  python3 backup_bot.py --list     # list existing backups
  python3 backup_bot.py --clean    # delete all backups
  python3 backup_bot.py --dry-run  # show what would be included without creating backup
"""

import os
import sys
import glob
import tarfile
import subprocess
import tempfile
import requests
from datetime import datetime
from pathlib import Path

# --- Config ---
# Load .env
from dotenv import load_dotenv
load_dotenv("/root/x-bot/.env")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
BACKUP_DIR = "/root/x-bot/backups"
MAX_BACKUPS = 7
BOT_ROOT = "/root/x-bot"

# Files and patterns to back up
BACKUP_TARGETS = [
    "/root/x-bot/.env",
    "/root/x-bot/package.json",
    "/root/x-bot/images/custom_images.json",
    "/root/.openclaw/workspace/MEMORY.md",
    "/root/.openclaw/workspace/SOUL.md",
    "/root/.openclaw/workspace/USER.md",
    "/root/.openclaw/openclaw.json",
]

BACKUP_GLOBS = [
    "/root/x-bot/*.py",
    "/root/x-bot/*.js",
]


def send_telegram(message):
    """Send a message via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
        }, timeout=15)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"[ERROR] Telegram send failed: {e}")
        return False


def collect_files():
    """Gather all files that exist from the target lists."""
    files = []
    for path in BACKUP_TARGETS:
        if os.path.isfile(path):
            files.append(path)
    for pattern in BACKUP_GLOBS:
        files.extend(sorted(glob.glob(pattern)))
    # deduplicate while preserving order
    seen = set()
    unique = []
    for f in files:
        if f not in seen:
            seen.add(f)
            unique.append(f)
    return unique


def export_crontab():
    """Export current crontab to a temp file, return path or None."""
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", prefix="crontab_", delete=False
            )
            tmp.write(result.stdout)
            tmp.close()
            return tmp.name
    except Exception as e:
        print(f"[WARN] Could not export crontab: {e}")
    return None


def get_existing_backups():
    """Return list of backup files sorted oldest first."""
    pattern = os.path.join(BACKUP_DIR, "xbot-backup-*.tar.gz")
    backups = sorted(glob.glob(pattern))
    return backups


def rotate_backups():
    """Delete oldest backups keeping only MAX_BACKUPS."""
    backups = get_existing_backups()
    to_delete = backups[:-MAX_BACKUPS] if len(backups) > MAX_BACKUPS else []
    for old in to_delete:
        try:
            os.remove(old)
            print(f"[ROTATE] Deleted: {os.path.basename(old)}")
        except OSError as e:
            print(f"[ERROR] Could not delete {old}: {e}")
    return len(to_delete)


def run_backup():
    """Main backup routine."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"xbot-backup-{timestamp}.tar.gz"
    filepath = os.path.join(BACKUP_DIR, filename)

    # Ensure backup dir exists
    os.makedirs(BACKUP_DIR, exist_ok=True)

    # Collect files
    files = collect_files()
    if not files:
        msg = "[ERROR] No files found to back up."
        print(msg)
        send_telegram(f"❌ Backup fallido: no se encontraron archivos.")
        return False

    # Export crontab
    crontab_file = export_crontab()

    # Create tar.gz
    print(f"[BACKUP] Creating {filename}...")
    try:
        with tarfile.open(filepath, "w:gz") as tar:
            for f in files:
                arcname = os.path.relpath(f, "/root")
                tar.add(f, arcname=arcname)
                print(f"  + {f}")
            if crontab_file:
                tar.add(crontab_file, arcname="crontab_export.txt")
                print(f"  + crontab_export.txt")
    except Exception as e:
        msg = f"[ERROR] Failed to create archive: {e}"
        print(msg)
        send_telegram(f"❌ Backup fallido: {e}")
        return False
    finally:
        if crontab_file and os.path.exists(crontab_file):
            os.unlink(crontab_file)

    # Size
    size_bytes = os.path.getsize(filepath)
    size_mb = round(size_bytes / (1024 * 1024), 2)

    # Rotate
    rotate_backups()
    current_count = len(get_existing_backups())

    print(f"[OK] {filename} ({size_mb} MB) - {current_count}/{MAX_BACKUPS} backups")

    # Telegram notification
    send_telegram(
        f"✅ Backup completado: <b>{filename}</b> ({size_mb}MB).\n"
        f"Backups guardados: {current_count}/{MAX_BACKUPS}"
    )
    return True


def cmd_list():
    """List existing backups."""
    backups = get_existing_backups()
    if not backups:
        print("No backups found.")
        return
    print(f"Backups in {BACKUP_DIR} ({len(backups)}/{MAX_BACKUPS}):\n")
    for b in backups:
        size = round(os.path.getsize(b) / (1024 * 1024), 2)
        print(f"  {os.path.basename(b)}  ({size} MB)")


def cmd_clean():
    """Delete all backups."""
    backups = get_existing_backups()
    if not backups:
        print("No backups to delete.")
        return
    for b in backups:
        os.remove(b)
        print(f"Deleted: {os.path.basename(b)}")
    print(f"\nRemoved {len(backups)} backup(s).")


def cmd_dry_run():
    """Show what files would be included."""
    files = collect_files()
    crontab_file = export_crontab()
    print("Files that would be backed up:\n")
    for f in files:
        size = round(os.path.getsize(f) / 1024, 1)
        print(f"  {f}  ({size} KB)")
    if crontab_file:
        print(f"  crontab_export.txt")
        os.unlink(crontab_file)
    else:
        print("  (no crontab found)")
    print(f"\nTotal files: {len(files)} + crontab")


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--list" in args:
        cmd_list()
    elif "--clean" in args:
        cmd_clean()
    elif "--dry-run" in args:
        cmd_dry_run()
    else:
        success = run_backup()
        sys.exit(0 if success else 1)
