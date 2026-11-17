"""selftest آفلاین: الگوهای فروش/خرید/نوع ۲، همه‌ی موارد رد شدن، ورود به ناحیه، کارایی، و مقایسه با پیاده‌سازی مرجع.
اجرا:  python tests/selftest.py
"""
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bot.engine import scan, find_entry  # noqa: E402

# (hi, lo, close) — الگوی پایه‌ی فروش، نوع ۱
BASE = [
    (100.0, 98.0, 99.0), (101.0, 99.0, 100.0), (100.5, 97.0, 99.5), (102.0, 98.5, 101.5),
    (104.0, 101.0, 103.0), (106.0, 102.5, 105.0),   # 5 = SH (106)
    (105.5, 103.0, 104.0), (105.0, 102.0, 103.0), (104.0, 100.5, 101.5),
    (103.0, 99.5, 100.5),                           # 9 = L1 (99.5)
    (104.0, 100.0, 103.0),
    (106.5, 102.0, 105.5),                          # 11 = هانت (high بالای 106، close زیر آن)
    (105.0, 101.0, 102.0),
    (103.0, 99.0, 99.2),                            # 13 = j : کلوز زیر L1
]
PASS = FAIL = 0


def arrs(seq):
    return [x[0] for x in seq], [x[1] for x in seq], [x[2] for x in seq]


def mirror(seq, c=200.0):
    return [(c - lo, c - hi, c - cl) for hi, lo, cl in seq]


def zones(seq, first_j=0, min_hunt_i=0):
    hi, lo, cl = arrs(seq)
    return scan(hi, lo, cl, first_j, len(seq) - 1, min_hunt_i)


def check(name, cond, info=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  OK  ", name)
    else:
        FAIL += 1
        print("  FAIL", name, info)


def expect(name, seq, want, first_j=0, min_hunt_i=0):
    """want=None → هیچ ناحیه‌ای (نه فروش نه خرید)؛ want=dict → دقیقاً یک ناحیه‌ی فروش و قرینه‌اش خرید."""
    z = zones(seq, first_j, min_hunt_i)
    mz = zones(mirror(seq), first_j, min_hunt_i)
    if want is None:
        check(name + " [SELL]", not z, z)
        check(name + " [BUY mirror]", not mz, mz)
        return
    ok = len(z) == 1 and z[0].side == "SELL" and all(getattr(z[0], k) == v for k, v in want.items())
    check(name + " [SELL]", ok, z)
    exp_b = dict(want)
    for k in ("hunted", "broken", "wick"):
        if k in exp_b:
            exp_b[k] = 200.0 - exp_b[k]
    okb = len(mz) == 1 and mz[0].side == "BUY" and all(abs(getattr(mz[0], k) - v) < 1e-9 if isinstance(v, float)
                                                        else getattr(mz[0], k) == v for k, v in exp_b.items())
    check(name + " [BUY mirror]", okb, mz)


def with_(seq, changes, extra=()):
    s = list(seq)
    for i, v in changes.items():
        s[i] = v
    return s + list(extra)


print("== الگوهای معتبر ==")
expect("فروش نوع ۱", BASE, dict(ztype="1", hunted=106.0, broken=99.5, wick=106.5, mss_i=13, hunt_i=11, swing_i=5))
T2 = with_(BASE, {13: (103.0, 99.3, 100.5)}, [(101.5, 96.0, 96.5)])   # L1 فقط با شدو لمس می‌شود؛ بعد L2 با بدنه شکسته می‌شود
expect("فروش نوع ۲", T2, dict(ztype="2", hunted=106.0, broken=97.0, mss_i=14, broken_i=2))
# نوع ۱ و ۲ یکی باشند: بین SH و هانت هیچ سویینگ لویی نباشد
SAME = [(100, 98, 99), (101, 99, 100), (100.5, 97, 99.5), (102, 98.5, 101.5), (104, 101, 103),
        (106, 102.5, 105), (105.5, 103, 104), (105, 103.5, 104.5), (105.2, 103.8, 104.8),
        (106.5, 104, 105.5), (105, 103.5, 104), (103, 96.5, 96.8)]
expect("نوع ۱ و ۲ یکی", SAME, dict(ztype="1+2", hunted=106.0, broken=97.0, mss_i=11))

print("== موارد رد شدن ==")
expect("هانت: کلوز کندل هانت بالای SH", with_(BASE, {11: (106.5, 102.0, 106.4)}), None)
expect("کلوز بالای SH بعد از هانت و قبل از j", with_(BASE, {12: (107.5, 104.0, 107.0)}), None)
expect("هانت و شکست در یک کندل", with_(BASE[:11], {}, [(106.5, 99.0, 99.2), (103, 100, 101), (102, 100.5, 101)]), None)
expect("اولین برخورد فقط شدو، کندل بعد زیرش کلوز", with_(BASE, {13: (103.0, 99.3, 100.5)}, [(101.0, 98.5, 98.8)]), None)
expect("L قبلاً با شدو لمس شده (L2)", with_(BASE, {13: (103.0, 99.3, 100.5)},
                                          [(101.5, 96.8, 98.0), (99.0, 95.5, 95.8)]), None)
expect("high کندل هانت برابر SH (بالاتر نیست)", with_(BASE, {11: (106.0, 102.0, 105.5)}), None)
expect("سویینگ غیراکید (high برابر همسایه)", with_(BASE, {6: (106.0, 103.0, 104.0)}), None)
expect("اولین عبور با بدنه بوده، بعداً شدو", with_(BASE, {8: (107.0, 104.5, 106.8)}), None)
expect("L بعد از کندل هانت ساخته شده",
       BASE[:12] + [(105.0, 101.0, 102.0), (103.0, 100.2, 100.8), (103.5, 101.0, 102.5), (102.0, 99.8, 99.9)], None)
expect("کندل j بیرون بازه (first_j)", BASE, None, first_j=14)
expect("هانت قبل از بازه ممنوع (min_hunt_i)", BASE, None, min_hunt_i=12)
expect("SH دست‌نخورده (هنوز هانت نشده)", BASE[:11] + [(105.5, 102.0, 105.0), (103, 99, 99.2)], None)

print("== چند سویینگ با یک شدو: بالاترین سطح انتخاب می‌شود + یک ناحیه برای هر L ==")
MULTI = [(100, 98, 99), (101, 99, 100), (100.5, 97, 99.5), (102, 98.5, 101.5), (104, 101, 103), (106, 102.5, 105),
         (105, 103, 104), (104, 102, 103), (105, 103, 104.5), (104, 100.5, 101.5), (103, 99.5, 100.5),
         (104, 100, 103), (106.5, 102, 104.8), (105, 101, 102), (103, 99, 99.2)]
expect("چند هانت هم‌زمان", MULTI, dict(hunted=106.0, broken=99.5, ztype="1", mss_i=14))

print("== ورود به ناحیه ==")
seq = BASE + [(99.3, 98.0, 99.0), (99.4, 98.5, 99.0), (99.6, 98.9, 99.3)]
hi, lo, cl = arrs(seq)
z = scan(hi, lo, cl, 0, 13)[0]
check("فروش: اولین لمس لبه‌ی پایین (کندل 16)", find_entry(z, hi, lo, z.mss_i + 1, len(seq) - 1) == 16)
check("فروش: بدون لمس → None", find_entry(z, hi, lo, z.mss_i + 1, 15) is None)
mhi, mlo, mcl = arrs(mirror(seq))
mz = scan(mhi, mlo, mcl, 0, 13)[0]
check("خرید: اولین لمس لبه‌ی بالا (کندل 16)", find_entry(mz, mhi, mlo, mz.mss_i + 1, len(seq) - 1) == 16)
check("خط اول = سطح سویینگ نه نوک شدو", z.hunted == 106.0 and z.wick == 106.5)

print("== سویینگ هانت‌شده‌ی قدیمی (۷۰۰۰ کندل قبل) + کارایی ==")


def noise(n, seed=0):
    out = []
    for i in range(n):
        p = 120 + 15 * math.sin(i / 37 + seed) + 6 * math.sin(i / 11) + 3 * math.sin(i / 5.3)
        out.append((p + 1 + .5 * abs(math.sin(i * 1.7)), p - 1 - .5 * abs(math.cos(i * 1.3)), p + .3 * math.sin(i * 2.1)))
    return out


LONG = noise(7000)
LONG[10] = (200.0, 119.0, 124.0)
LONG += [(125, 118, 122), (123, 108, 110), (124, 112, 120), (200.5, 115, 130), (128, 104, 105)]
t0 = time.perf_counter()
zl = scan(*arrs(LONG), len(LONG) - 1, len(LONG) - 1)
dt = time.perf_counter() - t0
check("SH از ۷۰۰۰ کندل قبل هانت و شکست داده شد", len(zl) == 1 and zl[0].hunted == 200.0 and zl[0].ztype == "1", zl)
check("زمان ارزیابی کامل ۷۰۰۰ کندل زیر ۱ ثانیه (%.0f ms)" % (dt * 1000), dt < 1.0)

print("== مقایسه با پیاده‌سازی مرجع (کند، مستقیم از متن شرط‌ها) روی داده‌ی تصادفی ==")


def reference(hi, lo, cl, first_j, min_hunt_i=0):
    n = len(hi)
    sh = [m for m in range(1, n - 1) if hi[m] > hi[m - 1] and hi[m] > hi[m + 1]]
    sl = [m for m in range(1, n - 1) if lo[m] < lo[m - 1] and lo[m] < lo[m + 1]]
    res = set()
    for s in sh:
        lvl = hi[s]
        h = next((i for i in range(s + 2, n) if hi[i] > lvl), None)
        if h is None or cl[h] > lvl or h < min_hunt_i:
            continue
        dead = next((i for i in range(h + 1, n) if cl[i] > lvl), n + 1)
        l1 = max([m for m in sl if m <= h - 1], default=None)
        l2 = max([m for m in sl if m <= s - 1], default=None)
        for L in {l1, l2} - {None}:
            lv = lo[L]
            t = next((i for i in range(L + 1, n) if lo[i] <= lv), None)
            if t is None or cl[t] >= lv or t <= h or t >= dead or t < first_j or lv >= lvl:
                continue
            res.add((t, L, s, h, lvl, lv))
    best = {}
    for t, L, s, h, lvl, lv in res:           # برای هر L فقط یکی: جدیدترین هانت، بعد بالاترین سطح
        k = (t, L)
        if k not in best or (h, lvl) > (best[k][3], best[k][4]):
            best[k] = (t, L, s, h, lvl, lv)
    return {(t, L, s, h) for t, L, s, h, _, _ in best.values()}


def rnd(n, seed):
    r = random.Random(seed)
    p, out = 100.0, []
    for _ in range(n):
        o = p
        p += r.gauss(0, 1)
        out.append((max(o, p) + abs(r.gauss(0, .8)), min(o, p) - abs(r.gauss(0, .8)), p))
    return out


bad, total = 0, 0
for seed in range(150):
    seq = rnd(260, seed)
    hi, lo, cl = arrs(seq)
    fj = 0 if seed % 3 else 120
    got = {(z.mss_i, z.broken_i, z.swing_i, z.hunt_i) for z in scan(hi, lo, cl, fj, len(seq) - 1) if z.side == "SELL"}
    want = reference(hi, lo, cl, fj)
    mseq = mirror(seq)
    mh, ml, mc = arrs(mseq)
    gotb = {(z.mss_i, z.broken_i, z.swing_i, z.hunt_i) for z in scan(mh, ml, mc, fj, len(seq) - 1) if z.side == "BUY"}
    total += len(want)
    if got != want or gotb != want:
        bad += 1
        if bad <= 3:
            print("   تفاوت seed", seed, "فقط‌موتور:", got - want, "فقط‌مرجع:", want - got)
check("۱۵۰ سری تصادفی (فروش+خرید) = مرجع؛ مجموع ناحیه‌ها: %d" % total, bad == 0 and total > 0, "bad=%d" % bad)
tmax = 0
for seed in range(5):
    seq = rnd(7500, 1000 + seed)
    t0 = time.perf_counter()
    scan(*arrs(seq), 0, len(seq) - 1)
    tmax = max(tmax, time.perf_counter() - t0)
check("بدترین زمان scan کامل ۷۵۰۰ کندل، فروش+خرید: %.0f ms (< 1000)" % (tmax * 1000), tmax < 1.0)

print("\nنتیجه: %d موفق، %d ناموفق" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
