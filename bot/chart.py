"""چارت تمیز ۱ دقیقه‌ای: حدود ۶۰ تا ۹۰ کندل، دو خط افقی، بدون شلوغی.
خط آبی = سطح سویینگِ هانت‌شده (نه نوک شدو)، خط نارنجی = سطح سویینگِ شکسته‌شده.
متن‌های چارت عمداً انگلیسی/عددی است تا به فونت فارسی نیاز نباشد؛ توضیح فارسی در کپشن می‌آید."""
import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.ticker import FuncFormatter, MaxNLocator  # noqa: E402

from . import config as C  # noqa: E402
from .timeutil import NY, hm  # noqa: E402

BG, UP, DN, EDGE, TXT, MUTED = "#e9e9ec", "#ffffff", "#5b5b5f", "#2b2b2f", "#34343a", "#76767e"
C_HUNT, C_BRK = "#1f5fff", "#f26a1b"


def chart_range(z, n_closed):
    end = min(n_closed - 1, z.mss_i + 3)
    want = end - min(z.hunt_i, z.broken_i) + 10
    count = min(90, max(60, C.CHART_CANDLES if want < C.CHART_CANDLES else want))
    return max(0, end - count + 1), end


def render_chart(sym, z, ts, o, h, l, c, n_closed) -> bytes:
    s, e = chart_range(z, n_closed)
    idx = list(range(s, e + 1))
    xs = list(range(len(idx)))
    H = [h[i] for i in idx]
    L = [l[i] for i in idx]
    dec = C.DECIMALS.get(sym, 2)
    fmt = lambda v: f"{v:,.{dec}f}"  # noqa: E731
    ymin, ymax = min(min(L), z.hunted, z.broken), max(max(H), z.hunted, z.broken)
    pad = (ymax - ymin) * 0.08 or 1.0
    sell = z.side == "SELL"

    fig = plt.figure(figsize=(9.6, 6.0), dpi=110, facecolor=BG)
    ax = fig.add_axes([0.075, 0.085, 0.84, 0.77], facecolor=BG)
    ax.axhspan(z.bottom, z.top, color="#5d7dff", alpha=0.07, lw=0, zorder=1)
    ax.axhline(z.hunted, color=C_HUNT, lw=1.8, zorder=2)
    ax.axhline(z.broken, color=C_BRK, lw=1.8, zorder=2)
    ax.vlines(xs, L, H, colors=EDGE, linewidth=1.0, zorder=3)
    mh = max(ymax - ymin, 1e-9) * 0.0006
    bodies = [abs(c[i] - o[i]) or mh for i in idx]
    ax.bar(xs, bodies, bottom=[min(o[i], c[i]) for i in idx], width=0.66,
           color=[UP if c[i] >= o[i] else DN for i in idx], edgecolor=EDGE, linewidth=0.9, zorder=4)

    if z.hunt_i in idx:                                   # نشانه‌ی کندل هانت (نوک شدو)
        x = idx.index(z.hunt_i)
        ax.scatter([x], [z.wick], s=26, color=C_HUNT, zorder=6)
        ax.annotate("Hunt", (x, z.wick), xytext=(0, 9 if sell else -9), textcoords="offset points",
                    ha="center", va="bottom" if sell else "top", fontsize=8.5, color=C_HUNT, fontweight="bold")
    xm = idx.index(z.mss_i)                               # نشانه‌ی کندل شیفت ساختاری
    ym = (L[xm] - pad * 0.22) if sell else (H[xm] + pad * 0.22)
    ax.scatter([xm], [ym], marker="^" if sell else "v", s=46, color=C_BRK, zorder=6)
    ax.annotate("MSS", (xm, ym), xytext=(0, -8 if sell else 8), textcoords="offset points",
                ha="center", va="top" if sell else "bottom", fontsize=8.5, color=C_BRK, fontweight="bold")

    for price, col in ((z.hunted, C_HUNT), (z.broken, C_BRK)):          # برچسب قیمت سمت راست
        ax.annotate(fmt(price), xy=(1.0, price), xycoords=("axes fraction", "data"), xytext=(5, 0),
                    textcoords="offset points", va="center", ha="left", fontsize=9.5, fontweight="bold",
                    color="white", annotation_clip=False,
                    bbox=dict(boxstyle="round,pad=0.25", fc=col, ec="none"))

    ax.set_xlim(-1, len(idx) + 5)
    ax.set_ylim(ymin - pad, ymax + pad)
    step = max(1, len(idx) // 6)
    ticks = list(range(0, len(idx), step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([hm(ts[idx[p]], NY) for p in ticks])
    ax.yaxis.set_major_locator(MaxNLocator(6))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: fmt(v)))
    ax.yaxis.tick_left()
    ax.tick_params(axis="both", length=0, labelsize=8.5, colors=MUTED)
    for sp in ax.spines.values():
        sp.set_visible(False)

    fig.text(0.02, 0.945, f"{sym}  ·  1m  ·  {z.side}", fontsize=16, fontweight="bold", color=TXT, ha="left", va="center")
    fig.text(0.98, 0.945, f"MSS close {hm(ts[z.mss_i] + 60, NY)} NY", fontsize=10.5, color=MUTED, ha="right", va="center")
    fig.legend(handles=[Line2D([0], [0], color=C_HUNT, lw=2.4, label="Hunted swing level"),
                        Line2D([0], [0], color=C_BRK, lw=2.4, label="Broken swing level")],
               loc="upper left", bbox_to_anchor=(0.012, 0.915), ncol=2, frameon=False, fontsize=9.5,
               labelcolor=TXT, handlelength=1.6, columnspacing=1.6)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()
