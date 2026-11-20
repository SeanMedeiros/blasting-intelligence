"""Operational date and time.

Production: the real local date/time in BI_TIMEZONE (naive local datetimes are stored).
Demo: the date is fixed at BI_DEMO_TODAY; the time of day is real, so new records sort naturally.
Always call today()/now() at the moment of use — never capture them at import time.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import config

try:
    _TZ = ZoneInfo(config.TIMEZONE)
except ZoneInfoNotFoundError as e:  # Windows needs the tzdata package (in requirements)
    raise RuntimeError(f"Unknown time zone BI_TIMEZONE={config.TIMEZONE!r}") from e


def is_demo() -> bool:
    return config.IS_DEMO


def now() -> datetime:
    local = datetime.now(_TZ).replace(tzinfo=None, microsecond=0)
    return datetime.combine(config.DEMO_TODAY, local.time()) if config.IS_DEMO else local


def today() -> date:
    return now().date()


def banner() -> str | None:
    """Text stamped on exports and reports in demo mode; None in production."""
    return config.DATA_DISCLAIMER or None
