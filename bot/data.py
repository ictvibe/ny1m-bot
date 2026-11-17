"""دریافت داده‌ی ۱ دقیقه‌ای: Yahoo Finance (اصلی) + Twelve Data (پشتیبان اختیاری برای فارکس/طلا).

هر نماد یک Feed دارد که سری کندل‌ها را نگه می‌دارد، فقط تکه‌ی تازه را می‌گیرد (حجم کم، فشار کم روی منبع)
و در صورت خطای پیاپی (مثلاً 429) خودکار به پشتیبان می‌رود.
"""
import calendar
import threading
import time
from urllib.parse import quote

import requests

from . import config as C
from .timeutil import lookback_start

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")
HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")
_tl = threading.local()


class FetchError(Exception):
    pass


def _sess() -> requests.Session:
    s = getattr(_tl, "s", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Accept": "application/json,text/plain,*/*",
                          "Accept-Language": "en-US,en;q=0.9"})
        _tl.s = s
    return s


def yahoo_bars(ticker: str, p1: float, p2: float, host: str = HOSTS[0]):
    r = _sess().get(
        f"https://{host}/v8/finance/chart/{quote(ticker, safe='=')}",
        params={"interval": "1m", "period1": int(p1), "period2": int(p2),
                "includePrePost": "true", "events": "history"},
        timeout=(4, 9))
    if r.status_code != 200:
        raise FetchError(f"HTTP {r.status_code}")
    try:
        j = r.json()["chart"]
        res = j["result"][0]
    except Exception:
        raise FetchError("no result: " + str((r.json().get("chart") or {}).get("error"))[:80])
    ts = res.get("timestamp") or []
    if not ts:
        return []
    q = res["indicators"]["quote"][0]
    return [(int(t), o, h, l, c) for t, o, h, l, c in zip(ts, q["open"], q["high"], q["low"], q["close"])
            if None not in (o, h, l, c)]


def twelve_bars(symbol: str, key: str, n: int):
    r = _sess().get("https://api.twelvedata.com/time_series",
                    params={"symbol": symbol, "interval": "1min", "outputsize": n, "timezone": "UTC", "apikey": key},
                    timeout=(4, 12))
    j = r.json()
    if j.get("status") == "error" or "values" not in j:
        raise FetchError("twelve: " + str(j.get("message", r.status_code))[:80])
    out = []
    for v in j["values"]:
        t = calendar.timegm(time.strptime(v["datetime"], "%Y-%m-%d %H:%M:%S"))
        out.append((t, float(v["open"]), float(v["high"]), float(v["low"]), float(v["close"])))
    return out


class Series:
    """کندل‌ها با کلید زمان شروع (epoch ثانیه). کندل همان دقیقه با مقدار تازه جایگزین می‌شود."""

    def __init__(self):
        self.b = {}
        self._arr = None

    def __len__(self):
        return len(self.b)

    def merge(self, bars, offset: float = 0.0):
        new = []
        for t, o, h, l, c in bars:
            if t not in self.b:
                new.append(t)
            self.b[t] = (o + offset, h + offset, l + offset, c + offset)
        self._arr = None
        return new

    def trim(self, cutoff: float):
        old = [t for t in self.b if t < cutoff]
        for t in old:
            del self.b[t]
        if old:
            self._arr = None

    def last_t(self):
        return max(self.b) if self.b else None

    def arrays(self):
        """(t, o, h, l, c) به‌صورت لیست‌های مرتب."""
        if self._arr is None:
            ts = sorted(self.b)
            v = [self.b[t] for t in ts]
            self._arr = (ts, [x[0] for x in v], [x[1] for x in v], [x[2] for x in v], [x[3] for x in v])
        return self._arr


class Feed:
    def __init__(self, sym: str, twelve_key: str = None):
        self.sym = sym
        self.twelve_key = twelve_key
        self.series = Series()
        self.source = "yahoo"
        self.ticker_i = 0
        self.host_i = 0
        self.fail = 0
        self.fail_since = None
        self.last_ok = None
        self.last_bar_t = None
        self.backoff = 0.0
        self.retry_k = 0
        self.retry_min = 0
        self.last_err = ""
        self.next_preload = 0.0

    @property
    def ticker(self) -> str:
        return C.YAHOO[self.sym][self.ticker_i] if self.source == "yahoo" else C.TWELVE[self.sym]

    def label(self) -> str:
        if self.source == "yahoo":
            return f"Yahoo Finance · {self.ticker} — " + ("فیوچرز" if self.ticker.endswith("=F") else "اسپات")
        return f"Twelve Data · {self.ticker} — اسپات"

    # ---------- Yahoo ----------
    def _yahoo_call(self, ticker, p1, p2):
        last = None
        for k in range(2):                       # اگر host اول خطا داد، یک‌بار host دوم
            host = HOSTS[(self.host_i + k) % 2]
            try:
                b = yahoo_bars(ticker, p1, p2, host)
                self.host_i = (self.host_i + k) % 2
                return b
            except FetchError as e:
                last = e
                if "429" in str(e):
                    break
            except requests.RequestException as e:
                last = FetchError("net: " + type(e).__name__)
        raise last

    def _yahoo_range(self, ticker, start, end):
        bars, hi = [], end
        while True:
            lo = max(start, hi - 6.5 * 86400)    # Yahoo برای ۱ دقیقه حداکثر ~۷ روز در هر درخواست می‌دهد
            bars += self._yahoo_call(ticker, lo, hi)
            if lo <= start:
                break
            hi = lo
        bars.sort()
        return bars

    # ---------- عملیات اصلی ----------
    def preload(self, now: float):
        off = C.PRICE_OFFSET.get(self.sym, 0.0)
        need = lookback_start(now) - 3600
        if self.source == "twelve":
            bars = twelve_bars(self.ticker, self.twelve_key, 5000)
        else:
            best = None
            for i, tk in enumerate(C.YAHOO[self.sym]):
                try:
                    bars = self._yahoo_range(tk, need, now + 120)
                except FetchError:
                    if best is None and i == len(C.YAHOO[self.sym]) - 1:
                        raise
                    continue
                if best is None or len(bars) > len(best[1]):
                    best = (i, bars)
                if len(bars) >= 1000 and now - bars[-1][0] < 900:    # تیکر سالم: تاریخچه‌ی کافی و تازه
                    best = (i, bars)
                    break
            if best is None:
                raise FetchError("no data")
            self.ticker_i, bars = best
        self.series = Series()
        self.series.merge(bars, off)

    def poll(self, now: float) -> dict:
        t0 = time.time()
        try:
            new = []
            if len(self.series) < 300:                  # تاریخچه نیامده → بارگذاری کامل (حداکثر هر ۹۰ ثانیه)
                if now < self.next_preload:
                    raise FetchError("history not ready")
                self.next_preload = now + 90
                self.preload(now)
            else:
                p1 = max(self.series.last_t() - 600, now - 6 * 86400)
                if self.source == "yahoo":
                    bars = self._yahoo_call(self.ticker, p1, now + 120)
                else:
                    bars = twelve_bars(self.ticker, self.twelve_key, 12)
                new = self.series.merge(bars, C.PRICE_OFFSET.get(self.sym, 0.0))
            self.series.trim(lookback_start(now) - 3600)
            self.fail, self.fail_since, self.last_ok, self.last_err = 0, None, now, ""
            self.last_bar_t = self.series.last_t()
            return {"ok": True, "new": new, "rtt": time.time() - t0}
        except (FetchError, requests.RequestException, ValueError, KeyError) as e:
            self.fail += 1
            self.fail_since = self.fail_since or now
            self.last_err = f"{type(e).__name__}: {e}"[:100]
            if (self.fail >= 3 and self.source == "yahoo" and self.twelve_key and self.sym in C.TWELVE):
                self.source, self.series, self.fail = "twelve", Series(), 0     # عبور به پشتیبان
            return {"ok": False, "err": self.last_err, "rtt": time.time() - t0}
