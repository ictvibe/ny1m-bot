"""قالب پیام‌ها: فارسی، راست‌چین (RLM اول هر خط)، وقت نیویورک و تهران. قالب HTML تلگرام."""
from . import config as C
from .timeutil import NY, TEH, WEEKDAYS, both, hm

RLM = "‏"

TYPES = {
    ("SELL", "1"): "نوع ۱ ← آخرین سویینگ لو قبل از کندل هانت",
    ("SELL", "2"): "نوع ۲ ← سویینگ لوی سازنده‌ی همان سقف هانت‌شده",
    ("SELL", "1+2"): "نوع ۱ و ۲ ← هر دو یکی‌اند (بین سقف و هانت سویینگ لوی دیگری نیست)",
    ("BUY", "1"): "نوع ۱ ← آخرین سویینگ های قبل از کندل هانت",
    ("BUY", "2"): "نوع ۲ ← سویینگ های سازنده‌ی همان کف هانت‌شده",
    ("BUY", "1+2"): "نوع ۱ و ۲ ← هر دو یکی‌اند (بین کف و هانت سویینگ های دیگری نیست)",
}


def rtl(lines):
    return "\n".join(RLM + ln for ln in lines)


def px(sym, v):
    return f"<code>{v:,.{C.DECIMALS[sym]}f}</code>"


def zone_caption(sym, z, zid, ts, source, day, late=False, demo=False):
    sell = z.side == "SELL"
    top_note = "هانت‌شده با شدو" if sell else "شکسته‌شده با بدنه"
    bot_note = "شکسته‌شده با بدنه" if sell else "هانت‌شده با شدو"
    L = [f"{'📉' if sell else '📈'} <b>{'فروش (SELL)' if sell else 'خرید (BUY)'}</b> | <b>{sym}</b> | ⏱ ۱ دقیقه"]
    if demo:
        L.append("🧪 نمونه‌ی آزمایشی (داده‌ی ساختگی، سیگنال واقعی نیست)")
    if late:
        L.append("⚠️ ارسال با تأخیر (ربات دیرتر روشن شد)")
    L += ["",
          f"🔺 سقف ناحیه: {px(sym, z.top)} ← {top_note}",
          f"🔻 کف ناحیه: {px(sym, z.bottom)} ← {bot_note}",
          "",
          f"🧩 {TYPES[(z.side, z.ztype)]}",
          f"🎯 زمان هانت: {both(ts[z.hunt_i], day)}"]
    if ts[z.hunt_i] - ts[z.swing_i] > 3 * 3600:
        L.append(f"🕰 {'سقف' if sell else 'کف'} هانت‌شده ساخته شده در: {both(ts[z.swing_i], day)}")
    L += [f"✅ زمان کلوز و شیفت: {both(ts[z.mss_i] + 60, day)}",
          f"🔔 هشدار ورود: لمس لبه‌ی {'پایین' if sell else 'بالا'} ناحیه، {px(sym, z.broken)} (فقط یک‌بار)",
          "",
          f"🆔 کد ناحیه: <code>{zid}</code>",
          f"📡 منبع داده: {source}"]
    return rtl(L)


def entry_text(sym, side, edge, price_now, ts_touch, exact, day):
    sell = side == "SELL"
    return rtl([f"🔔 <b>ورود به ناحیه</b> | <b>{sym}</b> | {'فروش 📉' if sell else 'خرید 📈'}",
                f"💰 قیمت لمس: {px(sym, edge)} | قیمت الان: {px(sym, price_now)}",
                f"🕘 {'زمان لمس' if exact else 'زمان لمس (حدود، داخل همین کندل)'}: {both(ts_touch, day, secs=exact)}"])


def start_text(day, ws, we):
    return rtl(["🟢 <b>ربات روشن است</b>",
                f"📅 {WEEKDAYS[day.weekday()]} {day.isoformat()}",
                f"⏰ بازه‌ی رصد: {hm(ws, NY)} تا {hm(we, NY)} نیویورک | {hm(ws, TEH)} تا {hm(we, TEH)} تهران",
                "📊 نمادها: " + " · ".join(C.SYMBOLS),
                "⏱ تایم‌فریم: فقط ۱ دقیقه"])


def _q(xs, p):
    xs = sorted(xs)
    return xs[int(p * (len(xs) - 1))]


def end_text(day, zones, lag_data, lag_send):
    n = len(zones)
    sells = sum(1 for z in zones.values() if z["side"] == "SELL")
    ent = sum(1 for z in zones.values() if z.get("entered"))
    L = ["🏁 <b>پایان بازه‌ی امروز</b>", f"📅 {WEEKDAYS[day.weekday()]} {day.isoformat()}",
         f"🧩 تعداد ناحیه‌ها: <b>{n}</b> (فروش {sells} | خرید {n - sells})",
         f"🎯 ورود به ناحیه: {ent} مورد"]
    per = {s: sum(1 for z in zones.values() if z["symbol"] == s) for s in C.SYMBOLS}
    per = {s: k for s, k in per.items() if k}
    if per:
        L.append("📊 به تفکیک نماد: " + " | ".join(f"{s}: {k}" for s, k in per.items()))
    if lag_data:
        L.append(f"⚙️ تأخیر داده تا دیده‌شدن کندل جدید (میانه | ۹۰٪ | بیشینه): "
                 f"{_q(lag_data, .5):.0f} | {_q(lag_data, .9):.0f} | {max(lag_data):.0f} ثانیه ({len(lag_data)} نمونه)")
    if lag_send:
        L.append(f"📨 تأخیر پیام ناحیه پس از کلوز کندل (میانه | بیشینه): {_q(lag_send, .5):.0f} | {max(lag_send):.0f} ثانیه")
    return rtl(L)


def stale_text(items):
    L = ["⚠️ <b>هشدار: قطع داده</b>"]
    for sym, mins, err in items:
        L.append(f"• {sym}: حدود {mins} دقیقه است کندل جدید نیامده" + (f" ({err})" if err else ""))
    L.append("ربات خودکار دوباره تلاش می‌کند. اگر بازار تعطیل است (مثلاً تعطیلات آمریکا) طبیعی است.")
    return rtl(L)


def recover_text(syms):
    return rtl(["✅ داده دوباره وصل شد: " + " · ".join(syms)])


def test_text():
    return rtl(["✅ <b>اتصال ربات به تلگرام برقرار است</b>",
                "این پیام آزمایشی است؛ پیام بعدی یک نمونه‌ی چارت و کپشن (با داده‌ی ساختگی) است."])
