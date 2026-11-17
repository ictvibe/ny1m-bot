"""داده‌ی ساختگی (فقط برای تست چارت/تلگرام و --test؛ قیمت واقعی نیست)."""
import random

from .engine import scan

_SCALE = {"NAS100": 21000.0, "US30": 43000.0, "SPX500": 6100.0, "XAUUSD": 2650.0, "EURUSD": 1.0850, "GBPUSD": 1.2950}


def demo_zone(sym="NAS100", side="SELL", base_ts=1_794_000_000):
    """یک سری ۱ دقیقه‌ای ساختگی که دقیقاً یک ناحیه‌ی معتبر در آخرین کندل دارد."""
    price0 = _SCALE.get(sym, 100.0)
    vol = price0 * 0.00035
    sgn = 1 if side == "SELL" else -1
    for seed in range(1, 5000):
        r = random.Random(seed)
        p, bars = price0, []
        for _ in range(170):
            o = p
            p += r.gauss(0, vol)
            bars.append((o, max(o, p) + abs(r.gauss(0, vol * .6)), min(o, p) - abs(r.gauss(0, vol * .6)), p))
        if sgn < 0:                                       # آینه برای خرید
            bars = [(2 * price0 - o, 2 * price0 - lo, 2 * price0 - hi, 2 * price0 - c) for o, hi, lo, c in bars]
        o_, h_, l_, c_ = ([b[i] for b in bars] for i in range(4))
        zs = scan(h_, l_, c_, 100, len(bars) - 1)
        for z in zs:
            if z.side == side and z.hunt_i >= z.mss_i - 55 and z.mss_i >= 110:
                n = z.mss_i + 1
                ts = [base_ts - base_ts % 60 + 60 * i for i in range(n)]
                return z, ts, o_[:n], h_[:n], l_[:n], c_[:n]
    raise RuntimeError("demo not found")
