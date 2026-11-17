"""سنجش واقعی منابع داده — از همان سرور GitHub که ربات روی آن اجرا می‌شود.

می‌سنجد: سرعت پاسخ، کامل بودن کندل‌ها، «تأخیر دیده‌شدن کندل جدید» (چند ثانیه بعد از شروع هر دقیقه کندل تازه در API پیدا می‌شود)،
خطاها و محدودیت نرخ (429). گزارش: probe_report.md (و در صفحه‌ی خلاصه‌ی GitHub Actions).
اجرا:  python tools/probe.py --minutes 10 --interval 3
نکته: وقتی بازار بسته است (آخر هفته) تأخیر قابل سنجش نیست؛ فقط دسترسی و ساختار داده بررسی می‌شود.
"""
import argparse
import os
import statistics
import sys
import threading
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bot import config as C  # noqa: E402
from bot import data as D  # noqa: E402
from bot.timeutil import NY  # noqa: E402

EXTRA_STATIC = ["^NDX", "^DJI", "^GSPC"]        # شاخص‌های نقدی: فقط برای مقایسه (تست ایستا)


def pct(xs, p):
    xs = sorted(xs)
    return xs[int(p * (len(xs) - 1))] if xs else None


def f1(x):
    return "—" if x is None else f"{x:.1f}"


def static_test(ticker):
    now = time.time()
    t0 = time.time()
    try:
        bars = D.yahoo_bars(ticker, now - 6.5 * 86400, now + 120)
    except Exception as e:
        return dict(ticker=ticker, ok=False, err=f"{type(e).__name__}: {e}"[:60])
    rtt = (time.time() - t0) * 1000
    if not bars:
        return dict(ticker=ticker, ok=True, rtt=rtt, n=0, age=None, gaps=None)
    last = bars[-1][0]
    recent = [b[0] for b in bars if b[0] >= now - 3 * 3600]
    gaps = sum(max(0, (b - a) // 60 - 1) for a, b in zip(recent, recent[1:]))
    return dict(ticker=ticker, ok=True, rtt=rtt, n=len(bars), age=now - last, gaps=gaps, recent=len(recent))


def live_test(ticker, minutes, interval, out):
    """هر دقیقه از ثانیه‌ی ۰.۵ شروع می‌کند و هر `interval` ثانیه می‌پرسد تا کندلِ همان دقیقه ظاهر شود (حداکثر ۴۵ ثانیه)،
    بعد تا دقیقه‌ی بعد درخواستی نمی‌فرستد. فشار روی منبع تقریباً برابر خود ربات است (۱ تا ۳ درخواست در دقیقه برای هر تیکر)."""
    seen, rtts, errs = {}, [], {}
    start = time.time()
    end = start + minutes * 60
    minute = int(start // 60) * 60
    while True:
        minute += 60                                   # دقیقه‌ی بعد؛ منتظر شروعش می‌مانیم
        wait = minute + 0.5 - time.time()
        if wait > 0:
            time.sleep(wait)
        if time.time() >= end:
            break
        while minute not in seen and time.time() < min(minute + 45, end):
            t0 = time.time()
            try:
                bars = D.yahoo_bars(ticker, t0 - 600, t0 + 120)
                rtts.append((time.time() - t0) * 1000)
                ts = time.time()
                for b in bars:
                    if b[0] not in seen:
                        seen[b[0]] = ts
            except Exception as e:
                k = "429" if "429" in str(e) else type(e).__name__
                errs[k] = errs.get(k, 0) + 1
            if minute not in seen:
                time.sleep(max(0.2, interval - (time.time() - t0)))
    lags = [seen[t] - t for t in seen if t > start and 0 <= seen[t] - t < 300]     # فقط کندل‌هایی که بعد از شروع آزمون ظاهر شدند
    out[ticker] = dict(lags=lags, rtts=rtts, errs=errs, polls=len(rtts) + sum(errs.values()))


def twelve_live(sym, key, minutes, out):
    seen, errs, polls = {}, {}, 0
    start = time.time()
    while time.time() - start < minutes * 60:
        t0 = time.time()
        try:
            for b in D.twelve_bars(sym, key, 5):
                seen.setdefault(b[0], time.time())
        except Exception as e:
            errs[str(e)[:30]] = errs.get(str(e)[:30], 0) + 1
        polls += 1
        time.sleep(max(1, 25 - (time.time() - t0)))                  # ~۲ درخواست در دقیقه برای هر نماد (سقف رایگان ۸ در دقیقه)
    lags = [seen[t] - t for t in seen if t > start and 0 <= seen[t] - t < 300]
    out["TD:" + sym] = dict(lags=lags, rtts=[], errs=errs, polls=polls)


def verdict(lags):
    if len(lags) < 3:
        return "داده‌ی کافی نیست"
    m, p9 = statistics.median(lags), pct(lags, .9)
    return "عالی" if m <= 8 and p9 <= 15 else ("قابل قبول" if m <= 20 and p9 <= 40 else "کند")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--interval", type=float, default=3)
    ap.add_argument("--out", default="probe_report.md")
    a = ap.parse_args()
    now = datetime.now(timezone.utc)
    ny = now.astimezone(NY)
    tickers = sorted({t for v in C.YAHOO.values() for t in v})
    key = os.getenv("TWELVEDATA_API_KEY")
    L = [f"# گزارش سنجش منابع داده", f"زمان اجرا: {now:%Y-%m-%d %H:%M} UTC = {ny:%a %H:%M} نیویورک",
         f"مدت نمونه‌گیری زنده: {a.minutes:g} دقیقه. هر دقیقه از ثانیه‌ی ۰.۵ شروع و هر {a.interval:g} ثانیه یک درخواست برای هر تیکر "
         f"تا دیده‌شدن کندل همان دقیقه (حداکثر ۴۵ ثانیه)؛ یعنی فشار درخواست مثل خود ربات است.", ""]
    live_out, threads = {}, []
    if a.minutes > 0:
        for t in tickers:
            th = threading.Thread(target=live_test, args=(t, a.minutes, a.interval, live_out))
            th.start()
            threads.append(th)
        if key:
            for s in C.TWELVE.values():
                th = threading.Thread(target=twelve_live, args=(s, key, a.minutes, live_out))
                th.start()
                threads.append(th)
    st = [static_test(t) for t in tickers + EXTRA_STATIC]
    L += ["## ۱) درخواست تکی (تاریخچه‌ی ~۷ روز)", "",
          "| تیکر | وضعیت | پاسخ (ms) | تعداد کندل | سن آخرین کندل (ثانیه) | کندل‌های گم‌شده در ۳ ساعت اخیر |", "|---|---|---|---|---|---|"]
    for r in st:
        if not r["ok"]:
            L.append(f"| {r['ticker']} | ❌ {r['err']} | | | | |")
        else:
            L.append(f"| {r['ticker']} | ✅ | {r['rtt']:.0f} | {r['n']} | {f1(r['age'])} | {r['gaps']} |")
    for th in threads:
        th.join()
    if live_out:
        L += ["", "## ۲) نمونه‌گیری زنده: تأخیر دیده‌شدن کندل جدید (ثانیه بعد از شروع دقیقه)", "",
              "| منبع | کندل نمونه | میانه | ۹۰٪ | بیشینه | پاسخ میانه (ms) | خطاها | ارزیابی |", "|---|---|---|---|---|---|---|---|"]
        for t, r in sorted(live_out.items()):
            lg = r["lags"]
            L.append(f"| {t} | {len(lg)} | {f1(statistics.median(lg) if lg else None)} | {f1(pct(lg, .9))} | "
                     f"{f1(max(lg) if lg else None)} | {f1(statistics.median(r['rtts']) if r['rtts'] else None)} | "
                     f"{r['errs'] or 0} از {r['polls']} | {verdict(lg)} |")
        L += ["", "تعریف: تأخیر = (لحظه‌ای که کندل جدید برای اولین بار در پاسخ API دیده شد) − (لحظه‌ی شروع آن دقیقه). "
              f"دقت اندازه‌گیری برای Yahoo حدود {a.interval:g} ثانیه است؛ تأخیر واقعی ربات تقریباً همین مقدار است."]
        if any(t.startswith("TD:") for t in live_out):
            L += ["", "نکته: برای Twelve Data فاصله‌ی نمونه‌گیری ۲۵ ثانیه است (سقف رایگان ۸ درخواست در دقیقه)، پس تأخیرش تا ۲۵ ثانیه بیشتر از مقدار واقعی نشان داده می‌شود."]
    else:
        L += ["", "نمونه‌گیری زنده انجام نشد (minutes=0)."]
    if ny.weekday() >= 5:
        L += ["", "⚠️ امروز آخر هفته است؛ بازار بسته است و تأخیر زنده معنی ندارد. این آزمون را دوشنبه تا جمعه (ترجیحاً ۰۸:۳۰–۱۱:۳۰ نیویورک) دوباره اجرا کنید."]
    txt = "\n".join(L)
    print(txt)
    open(a.out, "w", encoding="utf-8").write(txt)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write(txt + "\n")


if __name__ == "__main__":
    main()
