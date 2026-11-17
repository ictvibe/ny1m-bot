"""زمان: نیویورک (با DST) و تهران، قالب‌بندی دوزمانه برای پیام‌ها."""
from datetime import date, datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

from . import config as C

NY = ZoneInfo(C.NY_TZ)
TEH = ZoneInfo(C.TEHRAN_TZ)
WEEKDAYS = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]


def ny_dt(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, NY)


def window_bounds(day: date):
    """(شروع, پایان) بازه‌ی همان روز نیویورک به‌صورت epoch."""
    s = datetime.combine(day, dtime(*C.WINDOW_START), tzinfo=NY).timestamp()
    e = datetime.combine(day, dtime(*C.WINDOW_END), tzinfo=NY).timestamp()
    return s, e


def lookback_start(now: float, trading_days: int = None) -> float:
    """ابتدای (۰۰:۰۰ نیویورک) روزی که N روز معاملاتی (دوشنبه تا جمعه) قبل از امروز است."""
    n = trading_days or C.LOOKBACK_TRADING_DAYS
    d = ny_dt(now).date()
    while n > 0:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return datetime.combine(d, dtime(0, 0), tzinfo=NY).timestamp()


def hm(ts: float, tz, secs: bool = False) -> str:
    d = datetime.fromtimestamp(ts, tz)
    return d.strftime("%H:%M:%S" if secs else "%H:%M")


def both(ts: float, ref_day: date = None, secs: bool = False) -> str:
    """مثال: «09:31 نیویورک | 17:01 تهران» (اگر روز با ref_day فرق کند، روز هفته و تاریخ هم می‌آید)."""
    ny = ny_dt(ts)
    s = f"{hm(ts, NY, secs)} نیویورک | {hm(ts, TEH, secs)} تهران"
    if ref_day is not None and ny.date() != ref_day:
        s = f"{WEEKDAYS[ny.weekday()]} {ny.strftime('%m-%d')} · " + s
    return s
