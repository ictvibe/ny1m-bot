"""حلقه‌ی اصلی: صبر تا شروع بازه → بارگذاری تاریخچه → رصد پیوسته ۰۸:۳۰–۱۱:۳۰ نیویورک → پیام پایان.

اجرا:  python -m bot.runner            (اجرای واقعی؛ در GitHub Actions)
       python -m bot.runner --test     (پیام آزمایشی + نمونه‌ی چارت به تلگرام)
       python -m bot.runner --demo     (بدون تلگرام؛ فقط چاپ و ذخیره‌ی نمونه در پوشه‌ی out)
"""
import argparse
import concurrent.futures as cf
import os
import time
import traceback
from bisect import bisect_left, bisect_right
from datetime import datetime, timezone
from types import SimpleNamespace

from . import config as C
from . import messages as M
from .chart import render_chart
from .data import Feed
from .engine import find_entry, scan
from .state import State
from .telegram import Telegram
from .timeutil import ny_dt, window_bounds


def log(*a):
    print(datetime.now(timezone.utc).strftime("%H:%M:%S"), *a, flush=True)


class Bot:
    def __init__(self, tg, state=None, feed_factory=Feed):
        self.tg = tg
        key = os.getenv("TWELVEDATA_API_KEY") or None
        self.feeds = {s: feed_factory(s, key) for s in C.SYMBOLS}
        self.state = state or State()
        self.next_poll, self.last_eval, self.stale = {}, {}, {}
        self.pool = cf.ThreadPoolExecutor(max_workers=len(C.SYMBOLS))

    # ---------------------------------------------------------------- اجرای روزانه
    def run(self):
        now = time.time()
        day = ny_dt(now).date()
        if day.weekday() > 4:
            log("آخر هفته است؛ کاری نیست")
            return 0
        self.day = day
        self.ws, self.we = window_bounds(day)
        if now > self.we + C.END_GRACE_S + 60:
            log("بازه‌ی امروز تمام شده؛ خروج")
            return 0
        self.state.load(day.isoformat())
        if self.state.data.get("end_sent"):
            log("پیام پایانِ امروز قبلاً ارسال شده؛ خروج")
            return 0
        self.sleep_until(self.ws - C.PRELOAD_LEAD_S)
        self.preload()
        self.sleep_until(self.ws)
        if not self.state.data["start_sent"]:
            self.tg.send_text(M.start_text(self.day, self.ws, self.we), silent=True)
            self.state.data["start_sent"] = True
            self.state.save()
        self.loop()
        self.finish()
        return 0

    def sleep_until(self, t):
        last = 0.0
        while True:
            left = t - time.time()
            if left <= 0:
                return
            if time.time() - last > 900:
                log(f"تا مرحله‌ی بعد {left / 60:.0f} دقیقه")
                last = time.time()
            time.sleep(min(left, 30))

    def preload(self):
        now = time.time()

        def one(s):
            try:
                self.feeds[s].preload(now)
                return s, ""
            except Exception as e:
                return s, f"{type(e).__name__}: {e}"

        with cf.ThreadPoolExecutor(max_workers=3) as ex:
            for s, err in ex.map(one, C.SYMBOLS):
                f = self.feeds[s]
                f.last_bar_t = f.series.last_t()
                log(f"preload {s}: {'FAIL ' + err if err else 'ok'} | کندل‌ها={len(f.series)} | {f.label()}")

    def loop(self):
        for s in C.SYMBOLS:
            self.next_poll[s] = max(time.time(), self.ws + C.FIRST_POLL_DELAY_S)
        while time.time() < self.we + C.END_GRACE_S:
            try:
                now = time.time()
                due = [s for s in C.SYMBOLS if self.next_poll[s] <= now]
                futs = {s: self.pool.submit(self.feeds[s].poll, now) for s in due}
                for s in due:                                # به ترتیب اهمیت نمادها
                    self.after_poll(s, futs[s].result(), time.time())
                self.check_stale(time.time())
            except Exception:
                log("خطای غیرمنتظره در حلقه (ادامه می‌دهم):\n" + traceback.format_exc())
            time.sleep(0.25)

    def finish(self):
        d = self.state.data
        try:
            self.tg.send_text(M.end_text(self.day, d["zones"], d["lag_data"], d["lag_send"]), silent=C.END_SILENT)
        except Exception as e:
            log("ارسال پیام پایان ناموفق:", e)
        d["end_sent"] = True
        self.state.save()
        self.state.flush()
        log("پایان بازه؛ خروج")

    # ---------------------------------------------------------------- پردازش هر نماد
    def after_poll(self, s, res, t_seen):
        if res["ok"]:
            lags = self.state.data["lag_data"]
            for t in res["new"]:        # چند ثانیه بعد از شروع دقیقه، کندل جدید در API دیده شد؟
                if self.ws <= t and 0 <= t_seen - t < 120:
                    lags.append(round(t_seen - t, 1))
            del lags[:-3000]
            self.evaluate(s, t_seen)
            self.check_entries(s, t_seen)
        else:
            log(f"{s}: خطای دریافت — {res['err']}")
        self.schedule(s, res, t_seen)

    def evaluate(self, s, now):
        f = self.feeds[s]
        ts, o, h, l, c = f.series.arrays()
        n = len(ts)
        if n < 20:
            return
        nc = n if ts[-1] + 60 + C.QUIET_CLOSE_GRACE_S <= now else n - 1      # تعداد کندل‌های بسته‌شده
        jl = nc - 1
        while jl >= 0 and ts[jl] + 60 > self.we:                              # کلوزِ بعد از ۱۱:۳۰ حساب نیست
            jl -= 1
        i0 = bisect_left(ts, self.ws)
        last = self.last_eval.get(s, self.ws - 60)
        if jl < i0 or ts[jl] <= last:                                         # کندل بسته‌ی جدیدِ داخل بازه نیامده
            return
        start = max(i0, bisect_right(ts, last) - 2)                           # دو کندل قبلی هم دوباره (اگر منبع مقدارشان را اصلاح کرده باشد)
        zones = scan(h, l, c, start, jl, 0 if C.ALLOW_HUNT_BEFORE_WINDOW else i0)
        ok, cnt = True, {}
        for z in zones:
            k = (z.mss_i, z.side)
            cnt[k] = cnt.get(k, 0) + 1
            hhmm = ny_dt(ts[z.mss_i] + 60).strftime("%m%d-%H%M")
            zid = f"{s}-{z.side[0]}-{hhmm}" + ("" if cnt[k] == 1 else chr(96 + cnt[k]))
            ok = self.handle_zone(s, z, zid, ts, o, h, l, c, nc, now) and ok
        if ok:                                                                  # اگر ارسالی ناموفق بود، بار بعد دوباره
            self.last_eval[s] = ts[jl]

    def handle_zone(self, s, z, zid, ts, o, h, l, c, nc, now):
        zs = self.state.zones
        if zid in zs:
            return True
        close_t = ts[z.mss_i] + 60
        late = now - close_t > 90
        caption = M.zone_caption(s, z, zid, ts, self.feeds[s].label(), self.day, late=late)
        try:
            mid = self.tg.send_photo(render_chart(s, z, ts, o, h, l, c, nc), caption)
        except Exception as e:
            log(f"{s}: ارسال عکس ناموفق ({e}) → ارسال متنی")
            try:
                mid = self.tg.send_text(caption)
            except Exception as e2:
                log(f"{s}: ارسال ناحیه ناموفق: {e2}")
                return False
        sent = time.time()
        zs[zid] = {"symbol": s, "side": z.side, "type": z.ztype, "hunted": z.hunted, "broken": z.broken,
                   "mss_t": ts[z.mss_i], "msg": mid, "created": sent, "entered": False}
        if not late:
            self.state.data["lag_send"].append(round(sent - close_t, 1))
        self.state.save()
        log(f"ناحیه {zid} ارسال شد | {z.ztype} | {z.hunted} / {z.broken} | تأخیر پس از کلوز {sent - close_t:.1f}s")
        return True

    def check_entries(self, s, now):
        if now >= self.we:
            return
        ts, o, h, l, c = self.feeds[s].series.arrays()
        for zid, zs in list(self.state.zones.items()):
            if zs["symbol"] != s or zs["entered"]:
                continue
            i = bisect_left(ts, zs["mss_t"])
            if i >= len(ts) or ts[i] != zs["mss_t"]:
                continue
            last = len(ts) - 1
            while last > i and ts[last] >= self.we:
                last -= 1
            k = find_entry(SimpleNamespace(side=zs["side"], broken=zs["broken"]), h, l, i + 1, last)
            if k is None:
                continue
            exact = k == len(ts) - 1
            t_touch = now if exact else ts[k]
            try:
                mid = self.tg.send_text(M.entry_text(s, zs["side"], zs["broken"], c[-1], t_touch, exact, self.day),
                                        reply_to=zs["msg"])
            except Exception as e:
                log(f"{zid}: ارسال ورود ناموفق: {e}")
                continue
            zs.update(entered=True, entry_msg=mid, entry_t=t_touch)
            self.state.save()
            log(f"ورود به ناحیه {zid} ارسال شد | کندل {k - i} بعد از MSS")

    def schedule(self, s, res, t):
        f = self.feeds[s]
        minute = int(t // 60) * 60
        if not res["ok"]:
            f.backoff = min(max(f.backoff * 2, 2.0), 20.0)
            self.next_poll[s] = t + f.backoff
            return
        f.backoff = 0.0
        active = any(z["symbol"] == s and not z["entered"] for z in self.state.zones.values())
        if (f.last_bar_t or 0) >= minute:                 # کندل این دقیقه آمده ⇒ کندل قبلی قطعاً بسته است
            f.retry_k = 0
            nxt = minute + 60 + C.FIRST_POLL_DELAY_S
            if active:
                nxt = min(nxt, t + C.ENTRY_POLL_S)
        else:                                             # هنوز نیامده؛ با فاصله‌های رو‌به‌افزایش دوباره
            if f.retry_min != minute:
                f.retry_min, f.retry_k = minute, 0
            nxt = t + C.RETRY_DELAYS[min(f.retry_k, len(C.RETRY_DELAYS) - 1)]
            f.retry_k += 1
        self.next_poll[s] = nxt

    def check_stale(self, now):
        if not (self.ws + 90 <= now <= self.we):
            return
        bad, back = [], []
        for s in C.SYMBOLS:
            f = self.feeds[s]
            age = now - (f.last_bar_t or self.ws)
            stale = age > C.STALE_WARN_S or bool(f.fail_since and now - f.fail_since > 120)
            if stale and now - self.stale.get(s, 0) > C.STALE_REPEAT_S:
                bad.append((s, int(age // 60), f.last_err[:40] if f.fail_since else ""))
                self.stale[s] = now
            elif not stale and s in self.stale:
                back.append(s)
                del self.stale[s]
        try:
            if bad:
                self.tg.send_text(M.stale_text(bad))
            if back:
                self.tg.send_text(M.recover_text(back), silent=True)
        except Exception as e:
            log("ارسال هشدار ناموفق:", e)


def run_test(tg):
    """پیام آزمایشی + دو نمونه‌ی چارت/کپشن/ریپلای ورود با داده‌ی ساختگی."""
    from .demo import demo_zone
    day = ny_dt(time.time()).date()
    tg.send_text(M.test_text())
    for sym, side in (("NAS100", "SELL"), ("EURUSD", "BUY")):
        z, ts, o, h, l, c = demo_zone(sym, side, int(time.time()) - 170 * 60)
        mid = tg.send_photo(render_chart(sym, z, ts, o, h, l, c, len(ts)),
                            M.zone_caption(sym, z, f"{sym}-{side[0]}-DEMO", ts, "داده‌ی ساختگی (نمونه)", day, demo=True))
        tg.send_text(M.entry_text(sym, side, z.broken, c[-1], time.time(), True, day), reply_to=mid)
    log("پیام‌های آزمایشی ارسال شد")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="پیام و نمونه‌ی آزمایشی به تلگرام")
    ap.add_argument("--demo", action="store_true", help="بدون تلگرام: چاپ و ذخیره‌ی نمونه")
    a = ap.parse_args(argv)
    tg = Telegram(os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID"), dry=a.demo)
    if a.test or a.demo:
        if not a.demo and tg.dry:
            log("توکن یا شناسه‌ی چت تنظیم نشده (Secrets)؛ حالت نمایشی اجرا می‌شود")
        return run_test(tg)
    if tg.dry:
        raise SystemExit("TELEGRAM_BOT_TOKEN و TELEGRAM_CHAT_ID تنظیم نشده‌اند (Secrets)")
    return Bot(tg).run()


if __name__ == "__main__":
    raise SystemExit(main())
