"""تست یکپارچه با ساعت و منبع داده‌ی ساختگی: یک روز کامل (۰۸:۳۰–۱۱:۳۰ نیویورک) را «بازپخش» می‌کند.
بررسی: ناحیه‌ها = نتیجه‌ی موتور روی کل داده، ورود (ریپلای)، بدون ارسال تکراری، قطع داده + هشدار، ری‌استارت وسط بازه، تأخیر پیام.
اجرا:  python tests/replay_test.py
"""
import os
import random
import sys
import tempfile
from bisect import bisect_left, bisect_right, insort
from datetime import datetime
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bot import config as C  # noqa: E402
from bot import runner  # noqa: E402
from bot.data import Feed, Series  # noqa: E402
from bot.engine import find_entry, scan  # noqa: E402
from bot.state import State  # noqa: E402
from bot.timeutil import NY, lookback_start, window_bounds  # noqa: E402

DAY = datetime(2026, 11, 16, tzinfo=NY).date()                     # دوشنبه
WS, WE = window_bounds(DAY)
FAILS = 0


def check(name, cond, info=""):
    global FAILS
    print(("  OK   " if cond else "  FAIL ") + name, "" if cond else info)
    FAILS += 0 if cond else 1


def make_bars(seed):
    r = random.Random(seed)
    t0 = int(lookback_start(WS) - 3600)
    t0 -= t0 % 60
    p, bars = 100.0, []
    for t in range(t0, int(WE) + 60, 60):
        if datetime.fromtimestamp(t, NY).weekday() >= 5:
            continue
        o = p
        p += r.gauss(0, 1.0)
        bars.append((t, o, max(o, p) + abs(r.gauss(0, .7)), min(o, p) - abs(r.gauss(0, .7)), p))
    return bars


def partial(bar, frac):
    t, o, h, l, c = bar
    pts = [o, l, h, c] if c >= o else [o, h, l, c]
    seg = min(int(frac * 3), 2)
    cur = pts[seg] + (pts[seg + 1] - pts[seg]) * (frac * 3 - seg)
    vis = pts[:seg + 1] + [cur]
    return (t, o, max(vis), min(vis), cur)


class FakeFeed(Feed):
    """منبع ساختگی: کندل t بعد از t+delay دیده می‌شود؛ کندل در حال تشکیل ناقص است؛ بازه‌ی قطعی اختیاری."""
    DATA, OUTAGE, DELAY = {}, {}, 4.0

    def __init__(self, sym, key=None):
        super().__init__(sym, key)
        self.bars = self.DATA[sym]
        self.ts_all = [b[0] for b in self.bars]

    def _visible(self, now, since):
        vis_now = now - self.DELAY
        i0, i1 = bisect_left(self.ts_all, since), bisect_right(self.ts_all, vis_now)
        return [self.bars[i] if vis_now >= self.bars[i][0] + 60 else partial(self.bars[i], (vis_now - self.bars[i][0]) / 60)
                for i in range(i0, i1)]

    def label(self):
        return "منبع آزمایشی"

    def preload(self, now):
        self.series = Series()
        self.series.merge(self._visible(now, lookback_start(now) - 3600))

    def poll(self, now):
        o = self.OUTAGE.get(self.sym)
        if o and o[0] <= now < o[1]:
            self.fail += 1
            self.fail_since = self.fail_since or now
            self.last_err = "HTTP 429"
            return {"ok": False, "err": "HTTP 429", "rtt": 0.0}
        if len(self.series) < 300:
            self.preload(now)
            new = []
        else:
            new = self.series.merge(self._visible(now, self.series.last_t() - 600))
        self.fail, self.fail_since, self.last_ok, self.last_err = 0, None, now, ""
        self.last_bar_t = self.series.last_t()
        return {"ok": True, "new": new, "rtt": 0.05}


class FakeTG:
    def __init__(self, clock):
        self.clock, self.msgs, self.n = clock, [], 500

    def send_text(self, text, reply_to=None, silent=False):
        self.n += 1
        self.msgs.append(dict(t=self.clock.t, kind="text", text=text, reply=reply_to, silent=silent, id=self.n))
        return self.n

    def send_photo(self, png, caption, silent=False):
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        self.n += 1
        self.msgs.append(dict(t=self.clock.t, kind="photo", text=caption, reply=None, silent=silent, id=self.n))
        return self.n


class Clock:
    def __init__(self, t):
        self.t = t

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s


class StopBot(runner.Bot):
    stop_at = None

    def loop(self):
        if self.stop_at is None:
            return super().loop()
        for s in C.SYMBOLS:
            self.next_poll[s] = max(runner.time.time(), self.ws + C.FIRST_POLL_DELAY_S)
        while runner.time.time() < self.stop_at:
            now = runner.time.time()
            due = [s for s in C.SYMBOLS if self.next_poll[s] <= now]
            for s in due:
                self.after_poll(s, self.feeds[s].poll(now), runner.time.time())
            self.check_stale(runner.time.time())
            runner.time.sleep(0.25)
        raise KeyboardInterrupt


def expected():
    """نتیجه‌ی مرجع: موتور روی کل داده‌ی نهایی + اولین لمس لبه."""
    exp = {}
    for sym, bars in FakeFeed.DATA.items():
        ts = [b[0] for b in bars]
        h, l, c = [b[2] for b in bars], [b[3] for b in bars], [b[4] for b in bars]
        i0 = bisect_left(ts, WS)
        jl = bisect_right(ts, WE - 60) - 1
        for z in scan(h, l, c, i0, jl):
            last = bisect_left(ts, WE) - 1
            k = find_entry(z, h, l, z.mss_i + 1, last)
            exp[(sym, z.side, ts[z.mss_i], round(z.hunted, 6), round(z.broken, 6))] = None if k is None else ts[k]
    return exp


def run_day(clock_start, tmp, outage=None, restart_at=None):
    FakeFeed.OUTAGE = outage or {}
    clock = Clock(clock_start)
    runner.time = SimpleNamespace(time=clock.time, sleep=clock.sleep)
    tg = FakeTG(clock)
    state = State(tmp)
    bot = StopBot(tg, state, feed_factory=FakeFeed)
    if restart_at:
        bot.stop_at = restart_at
        try:
            bot.run()
        except KeyboardInterrupt:
            pass
        clock.t = restart_at + 420                     # ۷ دقیقه خاموشی
        bot = StopBot(tg, State(tmp), feed_factory=FakeFeed)
    bot.run()
    return bot, tg


def summarize(bot, tg):
    got = {}
    for z in bot.state.zones.values():
        got[(z["symbol"], z["side"], z["mss_t"], round(z["hunted"], 6), round(z["broken"], 6))] = \
            (int(z["entry_t"] // 60 * 60) if z["entered"] else None)
    return got


def common_checks(bot, tg, exp, label):
    got = summarize(bot, tg)
    check(f"{label}: مجموعه‌ی ناحیه‌ها = مرجع ({len(exp)} ناحیه)", set(got) == set(exp), (set(got) ^ set(exp)))
    check(f"{label}: ورود هر ناحیه در همان کندلِ مرجع", all(got[k] == exp[k] for k in exp if k in got),
          [(k, got.get(k), exp[k]) for k in exp if got.get(k) != exp[k]][:3])
    photos = [m for m in tg.msgs if m["kind"] == "photo"]
    check(f"{label}: هر ناحیه دقیقاً یک پیام (بدون تکرار)", len(photos) == len(exp), (len(photos), len(exp)))
    entries = [m for m in tg.msgs if m["reply"]]
    ids = {z["msg"] for z in bot.state.zones.values()}
    check(f"{label}: پیام‌های ورود همه ریپلای روی پیام ناحیه‌اند", all(m["reply"] in ids for m in entries) and
          len(entries) == sum(1 for v in exp.values() if v is not None), (len(entries),))
    check(f"{label}: همه‌ی پیام‌های ناحیه/ورود داخل بازه (+مهلت پایان)", all(WS <= m["t"] <= WE + C.END_GRACE_S for m in tg.msgs))
    starts = [m for m in tg.msgs if "ربات روشن است" in m["text"]]
    ends = [m for m in tg.msgs if "پایان بازه" in m["text"]]
    check(f"{label}: یک پیام شروع (بی‌صدا) و یک پیام پایان", len(starts) == 1 and starts[0]["silent"] and len(ends) == 1)
    check(f"{label}: هر خط پیام‌ها با RLM شروع می‌شود", all(ln.startswith("‏") for m in tg.msgs for ln in m["text"].split("\n")))


print("== ساخت داده‌ی ساختگی ۶ نماد ==")
FakeFeed.DATA = {s: make_bars(100 + i) for i, s in enumerate(C.SYMBOLS)}
EXP = expected()
print("   ناحیه‌ی مورد انتظار در بازه:", len(EXP), "| با ورود:", sum(v is not None for v in EXP.values()))
check("داده‌ی آزمایشی حداقل چند ناحیه دارد", len(EXP) >= 5)

print("== سناریو A: روز عادی (تأخیر منبع ۴ ثانیه) ==")
with tempfile.TemporaryDirectory() as tmp:
    t_start = datetime(2026, 11, 16, 7, 50, tzinfo=NY).timestamp()
    bot, tg = run_day(t_start, tmp)
    common_checks(bot, tg, EXP, "A")
    lag = bot.state.data["lag_send"]
    check("A: تأخیر پیام ناحیه پس از کلوز ≤ ۲۰ ثانیه (max=%.1f)" % (max(lag) if lag else 0), not lag or max(lag) <= 20)
    for m in tg.msgs[:1] + [m for m in tg.msgs if m["kind"] == "photo"][:1]:
        pass

print("== سناریو B: قطع داده ۶ دقیقه‌ای برای NAS100 + ری‌استارت وسط بازه ==")
with tempfile.TemporaryDirectory() as tmp:
    t_start = datetime(2026, 11, 16, 7, 50, tzinfo=NY).timestamp()
    out = {"NAS100": (WS + 40 * 60, WS + 47 * 60)}
    bot, tg = run_day(t_start, tmp, outage=out, restart_at=WS + 75 * 60)
    common_checks(bot, tg, EXP, "B")
    warn = [m for m in tg.msgs if "قطع داده" in m["text"]]
    check("B: هشدار قطع داده ارسال شد", len(warn) >= 1)
    check("B: پیام پایان با آمار", any("تعداد ناحیه‌ها" in m["text"] for m in tg.msgs))

print("\nنتیجه:", "همه موفق" if not FAILS else f"{FAILS} مورد ناموفق")
sys.exit(1 if FAILS else 0)
