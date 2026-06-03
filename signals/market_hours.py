import logging
import os
from datetime import datetime, timedelta, timezone

import pandas_market_calendars as mcal
import pytz

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")
_CALENDAR = mcal.get_calendar("NYSE")

_NYSE_OPEN_HOUR = 9
_NYSE_OPEN_MINUTE = 30
_NYSE_CLOSE_HOUR = 16


def _et_now(now: datetime | None = None) -> datetime:
    ts = now or datetime.now(tz=timezone.utc)
    return ts.astimezone(ET)


def _is_trading_day(date_str: str) -> bool:
    schedule = _CALENDAR.schedule(start_date=date_str, end_date=date_str)
    return not schedule.empty


def _next_market_open(from_dt: datetime) -> datetime | None:
    from_et = from_dt.astimezone(ET)
    check_date = from_et.date()

    for _ in range(15):
        date_str = check_date.strftime("%Y-%m-%d")
        schedule = _CALENDAR.schedule(start_date=date_str, end_date=date_str)
        if not schedule.empty:
            raw_open = schedule.iloc[0]["market_open"]
            market_open = raw_open.astimezone(ET)
            if market_open > from_et:
                return market_open
        check_date += timedelta(days=1)

    return None


class MarketHoursGuard:
    def is_open(self, now: datetime | None = None) -> bool:
        now_et = _et_now(now)

        if now_et.weekday() >= 5:
            return False

        open_boundary = now_et.replace(
            hour=_NYSE_OPEN_HOUR, minute=_NYSE_OPEN_MINUTE, second=0, microsecond=0
        )
        close_boundary = now_et.replace(
            hour=_NYSE_CLOSE_HOUR, minute=0, second=0, microsecond=0
        )
        if not (open_boundary <= now_et < close_boundary):
            return False

        return _is_trading_day(now_et.strftime("%Y-%m-%d"))

    def minutes_to_open(self, now: datetime | None = None) -> float | None:
        ts = now or datetime.now(tz=timezone.utc)
        if self.is_open(ts):
            return None

        next_open = _next_market_open(ts)
        if next_open is None:
            return None

        now_et = _et_now(ts)
        delta = next_open - now_et
        return delta.total_seconds() / 60.0

    def edge_decay_factor(self, signal_timestamp: datetime) -> float:
        if self.is_open(signal_timestamp):
            return 1.0

        half_life_hours = float(os.getenv("EDGE_HALF_LIFE_HOURS", "1.0"))
        mins = self.minutes_to_open(signal_timestamp)
        if mins is None:
            return 0.0

        hours_to_open = mins / 60.0
        return max(0.0, 1.0 - hours_to_open / half_life_hours)
