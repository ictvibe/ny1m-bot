"""بک‌تست روی داده‌ی ۱ دقیقه‌ای: همان موتور و همان منطق ربات، روز به روز (فقط بازه‌ی ۰۸:۳۰–۱۱:۳۰ نیویورک).

اجرا:  python tools/backtest.py --days 20             (داده‌ی واقعی Yahoo؛ حداکثر ~۲۹ روز اخیر)
       python tools/backtest.py --source synthetic     (آزمایش آفلاین ابزار)
خروجی در پوشه‌ی backtest_out: zones.csv, report.md, charts/*.png (نمونه‌ی چارت‌ها برای مقایسه با چارت خودتان)
"""
import argparse
import csv
import os
import random
import sys
import time
from bisect import bisect_left, bisect_right
from collections import Counter
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bot import config as C  # noqa: E402
from bot import data as D  # noqa: E402
from bot.chart import render_chart  # noqa: E402
from bot.engine import find_entry, scan  # noqa: E402
from bot.timeutil import TEH, lookback_start, ny_dt, window_bounds  # noqa: E402


def fetch_yahoo(sym, days):
    feed = D.Feed(sym)
    now = time.time()
    start = now - days * 86400
    for tk in C.YAHOO[sym]:
        try:
            bars = feed._yahoo_range(tk, start, now + 120)
        except Exception as e:
            print(f"  {sym} {tk}: {e}")
            continue
        if len(bars) > 500:
            return tk, [(t, o + C.PRICE_OFFSET.get(sym, 0), h + C.PRICE_OFFSET.get(sym, 0),
                         l + C.PRICE_OFFSET.get(sym, 0), c + C.PRICE_OFFSET.get(sym, 0)) for t, o, h, l, c in bars]
    return None, []


def fetch_synthetic(sym, days):
    r = random.Random(sum(map(ord, sym)))
    now = time.time()
    t0 = int((now - days * 86400) // 60 * 60)
    p, out = 100.0, []
    for t in range(t0, int(now), 60):
        if ny_dt(t).weekday() >= 5:
            continue
        o = p
        p += r.gauss(0, 1)
        out.append((t, o, max(o, p) + abs(r.gauss(0, .7)), min(o, p) - abs(r.gauss(0, .7)), p))
    return "synthetic", out


def run(sym, tk, bars, max_charts, outdir, charts_done):
    ts = [b[0] for b in bars]
    o, h, l, c = ([b[i] for b in bars] for i in (1, 2, 3, 4))
    days = sorted({ny_dt(t).date() for t in ts})
    rows = []
    for d in days:
        if d.weekday() > 4:
            continue
        ws, we = window_bounds(d)
        if bisect_left(ts, ws) >= len(ts) or ts[bisect_right(ts, we - 60) - 1] < we - 300:
            continue                                                       # داده‌ی کامل آن روز موجود نیست
        a = bisect_left(ts, lookback_start(ws) - 3600)                     # همان تاریخچه‌ی ربات (۵ روز معاملاتی)
        e = bisect_right(ts, we - 60)                                      # آخرین کندلی که تا ۱۱:۳۰ بسته می‌شود
        i0 = bisect_left(ts, ws) - a
        t_, o_, h_, l_, c_ = ts[a:e], o[a:e], h[a:e], l[a:e], c[a:e]
        if i0 < 0 or len(t_) - 1 < i0:
            continue
        for z in scan(h_, l_, c_, i0, len(t_) - 1, 0 if C.ALLOW_HUNT_BEFORE_WINDOW else i0):
            ek2 = find_entry(z, h[a:e], l[a:e], z.mss_i + 1, e - a - 1)      # اولین لمس لبه تا ۱۱:۳۰
            rows.append(dict(date=d.isoformat(), symbol=sym, ticker=tk, side=z.side, type=z.ztype,
                             hunted=z.hunted, broken=z.broken, wick=z.wick,
                             hunt_ny=ny_dt(t_[z.hunt_i]).strftime("%m-%d %H:%M"),
                             swing_ny=ny_dt(t_[z.swing_i]).strftime("%m-%d %H:%M"),
                             close_ny=ny_dt(t_[z.mss_i] + 60).strftime("%H:%M"),
                             close_tehran=datetime.fromtimestamp(t_[z.mss_i] + 60, TEH).strftime("%H:%M"),
                             hunt_age_h=round((t_[z.hunt_i] - t_[z.swing_i]) / 3600, 1),
                             entered="yes" if ek2 is not None else "no",
                             entry_after_min="" if ek2 is None else ek2 - z.mss_i,
                             height=round(abs(z.hunted - z.broken), 6)))
            if charts_done[0] < max_charts:
                png = render_chart(sym, z, t_, o_, h_, l_, c_, len(t_))
                name = f"{d.isoformat()}_{sym}_{z.side}_{ny_dt(t_[z.mss_i] + 60):%H%M}.png"
                open(os.path.join(outdir, "charts", name), "wb").write(png)
                charts_done[0] += 1
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=20)
    ap.add_argument("--source", default="yahoo", choices=["yahoo", "synthetic"])
    ap.add_argument("--charts", type=int, default=12)
    ap.add_argument("--out", default="backtest_out")
    a = ap.parse_args()
    os.makedirs(os.path.join(a.out, "charts"), exist_ok=True)
    allrows, info, charts_done = [], {}, [0]
    for sym in C.SYMBOLS:
        t0 = time.time()
        tk, bars = (fetch_yahoo if a.source == "yahoo" else fetch_synthetic)(sym, min(a.days, 29))
        if not bars:
            info[sym] = "بدون داده"
            continue
        t1 = time.time()
        rows = run(sym, tk, bars, a.charts, a.out, charts_done)
        info[sym] = f"{tk} · کندل‌ها {len(bars)} · دانلود {t1 - t0:.1f}s · پردازش {time.time() - t1:.1f}s · ناحیه {len(rows)}"
        print(sym, info[sym], flush=True)
        allrows += rows
    with open(os.path.join(a.out, "zones.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(allrows[0].keys()) if allrows else ["empty"])
        w.writeheader()
        w.writerows(allrows)
    days = sorted({r["date"] for r in allrows})
    L = ["# گزارش بک‌تست", f"منبع: {a.source} | روزها: {a.days} | بازه: ۰۸:۳۰–۱۱:۳۰ نیویورک | تاریخچه‌ی هانت: {C.LOOKBACK_TRADING_DAYS} روز معاملاتی", "",
         "| نماد | جزئیات داده |", "|---|---|"] + [f"| {s} | {v} |" for s, v in info.items()]
    L += ["", f"**مجموع ناحیه‌ها: {len(allrows)}** در {len(days)} روز دارای سیگنال"]
    if allrows:
        L += ["", "| نماد | فروش | خرید | نوع ۱ | نوع ۲ | ۱+۲ | ورود خورده | میانه‌ی دقیقه تا ورود |", "|---|---|---|---|---|---|---|---|"]
        for s in C.SYMBOLS:
            rs = [r for r in allrows if r["symbol"] == s]
            if not rs:
                continue
            ent = sorted(r["entry_after_min"] for r in rs if r["entered"] == "yes")
            cnt = Counter(r["type"] for r in rs)
            L.append(f"| {s} | {sum(r['side'] == 'SELL' for r in rs)} | {sum(r['side'] == 'BUY' for r in rs)} | "
                     f"{cnt['1']} | {cnt['2']} | {cnt['1+2']} | {len(ent)}/{len(rs)} | {ent[len(ent) // 2] if ent else '—'} |")
        L += ["", f"میانگین ناحیه در هر روزِ دارای سیگنال (هر ۶ نماد): {len(allrows) / max(1, len(days)):.1f}",
              f"ناحیه‌ای که هانتش قدیمی‌تر از ۳ ساعت بوده: {sum(float(r['hunt_age_h']) > 3 for r in allrows)}",
              "", "فایل zones.csv همه‌ی ناحیه‌ها را دارد و پوشه‌ی charts نمونه‌ی چارت‌ها را؛ چند مورد را با چارت خودتان مقایسه کنید."]
    txt = "\n".join(L)
    open(os.path.join(a.out, "report.md"), "w", encoding="utf-8").write(txt)
    print("\n" + txt)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write(txt + "\n")


if __name__ == "__main__":
    main()
