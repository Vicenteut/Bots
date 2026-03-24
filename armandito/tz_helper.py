"""Centralized timezone helper — always use now_bz() instead of datetime.now()"""
from datetime import datetime, timezone, timedelta

BZ_OFFSET = timezone(timedelta(hours=-6))  # America/Belize = CST = UTC-6

def now_bz():
    """Return current datetime in Belize timezone (UTC-6)."""
    return datetime.now(BZ_OFFSET)
