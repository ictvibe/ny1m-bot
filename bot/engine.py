"""موتور ستاپ: هانت نقدینگی با شدو + شیفت ساختاری با بدنه (فقط کندل‌های بسته‌شده‌ی ۱ دقیقه‌ای).

SELL : سویینگ‌های SH با شدو هانت می‌شوند، بعد کندل j با بدنه (close) زیر یک سویینگ لوی دست‌نخورده (L) بسته می‌شود.
BUY  : دقیقاً قرینه (قیمت‌ها منفی می‌شوند و همان کد SELL اجرا می‌شود).

یک‌بار عبور از کندل‌ها (O(n)) با چند پشته؛ برای ~۷۰۰۰ کندل چند میلی‌ثانیه.
"""
from dataclasses import dataclass
from typing import List, Optional, Sequence


@dataclass
class Zone:
    side: str        # "SELL" | "BUY"
    ztype: str       # "1" | "2" | "1+2"
    hunted: float    # خط ۱: سطح سویینگِ هانت‌شده (نه نوک شدو)
    broken: float    # خط ۲: سطح سویینگِ شکسته‌شده (لبه‌ی ورود)
    wick: float      # نوک شدوی کندل هانت (فقط اطلاعات)
    swing_i: int     # اندیس کندل وسط سویینگ هانت‌شده
    hunt_i: int      # اندیس کندل هانت
    broken_i: int    # اندیس کندل وسط سویینگ شکسته‌شده
    mss_i: int       # اندیس کندل j (کلوز با بدنه آن‌طرفِ سویینگ شکسته‌شده)

    @property
    def top(self) -> float:
        return max(self.hunted, self.broken)

    @property
    def bottom(self) -> float:
        return min(self.hunted, self.broken)


def _scan_sell(hi, lo, cl, first_j: int, last_j: int, min_hunt_i: int):
    """خروجی: لیست (hunted, broken, wick, s, h, m_l, j, ztype) با قیمت‌ها در همین فضا."""
    n = last_j + 1
    fresh = []            # [(s, level)] سویینگ‌های بالای هانت‌نشده؛ سطح‌ها غیرصعودی → بالای پشته کمترین
    hunted = []           # [s, level, h, L1, L2]
    lows = []             # [(m, level)] سویینگ لوهای دست‌نخورده؛ صعودی → بالای پشته بیشترین
    last_sl = [-1] * (n + 1)   # last_sl[x] = آخرین اندیس سویینگ لو با m <= x-1
    out = []
    for k in range(n):
        hk, lk, ck = hi[k], lo[k], cl[k]
        m = k - 1
        new_sh = new_sl = False
        if m >= 1:                                   # سویینگ ۳کندلی m با کندل k تأیید می‌شود
            new_sh = hi[m] > hi[m - 1] and hi[m] > hk
            new_sl = lo[m] < lo[m - 1] and lo[m] < lk
        last_sl[k] = m if new_sl else (last_sl[k - 1] if k else -1)

        if hunted:                                   # بعد از هانت، کلوز بالای SH ستاپ را می‌کشد
            hunted = [x for x in hunted if ck <= x[1]]
        while fresh and fresh[-1][1] < hk:           # اولین کندل با high بالای SH
            s, lvl = fresh.pop()
            if ck <= lvl:                            # فقط شدو → هانت
                hunted.append([s, lvl, k, last_sl[k], last_sl[s]])
            # اگر close بالای SH باشد = شکست با بدنه، نه هانت → حذف
        broken = []
        while lows and lows[-1][1] >= lk:            # اولین برخورد با L
            ml, lvl = lows.pop()
            if ck < lvl:                             # با بدنه زیر L بسته شد
                broken.append((ml, lvl))
            # برخورد فقط با شدو → L برای همیشه نامعتبر

        if broken and hunted and k >= first_j:
            best = {}
            for s, lvl, h, l1, l2 in hunted:
                if h >= k or h < min_hunt_i:         # هانت و شکست در یک کندل معتبر نیست
                    continue
                for ml, lv in broken:
                    t1, t2 = (l1 == ml), (l2 == ml)
                    if not (t1 or t2) or lv >= lvl:
                        continue
                    zt = "1+2" if (t1 and t2) else ("1" if t1 else "2")
                    cur = best.get(ml)
                    if cur is None or (h, lvl) > (cur[0], cur[1]):   # جدیدترین هانت، بعد بالاترین سطح
                        best[ml] = (h, lvl, s, zt, lv)
            for ml, (h, lvl, s, zt, lv) in best.items():             # برای هر L حداکثر یک ناحیه
                out.append((lvl, lv, hi[h], s, h, ml, k, zt))

        if new_sh:
            fresh.append((m, hi[m]))
        if new_sl:
            lows.append((m, lo[m]))
    return out


def scan(hi: Sequence[float], lo: Sequence[float], cl: Sequence[float],
         first_j: int, last_j: int, min_hunt_i: int = 0) -> List[Zone]:
    """همه‌ی ناحیه‌هایی که کندل MSS آن‌ها در بازه‌ی اندیس [first_j, last_j] است (کندل‌های بسته‌شده)."""
    if last_j < 3 or last_j >= len(hi):
        return []
    res: List[Zone] = []
    for lvl, lv, wick, s, h, ml, j, zt in _scan_sell(hi, lo, cl, first_j, last_j, min_hunt_i):
        res.append(Zone("SELL", zt, lvl, lv, wick, s, h, ml, j))
    nh = [-x for x in lo[:last_j + 1]]               # قرینه برای BUY
    nl = [-x for x in hi[:last_j + 1]]
    nc = [-x for x in cl[:last_j + 1]]
    for lvl, lv, wick, s, h, ml, j, zt in _scan_sell(nh, nl, nc, first_j, last_j, min_hunt_i):
        res.append(Zone("BUY", zt, -lvl, -lv, -wick, s, h, ml, j))
    res.sort(key=lambda z: (z.mss_i, z.side, -z.broken if z.side == "SELL" else z.broken))
    return res


def find_entry(z: Zone, hi: Sequence[float], lo: Sequence[float],
               start: int, end: int) -> Optional[int]:
    """اولین کندل در [start, end] (کندل در حال تشکیل هم شامل است) که به لبه‌ی ورود برسد.
    SELL: high >= لبه‌ی پایین (سطح شکسته‌شده)  |  BUY: low <= لبه‌ی بالا (سطح شکسته‌شده)."""
    end = min(end, len(hi) - 1)
    if z.side == "SELL":
        for k in range(max(start, 0), end + 1):
            if hi[k] >= z.broken:
                return k
    else:
        for k in range(max(start, 0), end + 1):
            if lo[k] <= z.broken:
                return k
    return None
