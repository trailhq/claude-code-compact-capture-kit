"""Draw Figure 1 and Figure 3 of the /compact post in Trail's brand style (trailhq.com/brand).

Usage: python3 analysis/make_figures.py [data folder] [image folder] [fonts folder]

The data and image folders default to the folder this script is in. Needs matplotlib.
Reads results-replay.json (freeze2.py) and results-clusters.json (freeze4.py). No number is typed in by hand.

The fonts folder is optional. It holds Switzer (Regular and Medium) and Erode (Medium) from Fontshare, and
JetBrains Mono (Medium). They are not in this repository. Without them the charts use matplotlib's default face:
the numbers and the layout are the same, the lettering is not.

Brand rules applied: paper ground, deep ocean text, steel as the chart fill, one accent (signal coral, for wrong answers),
Erode for the title, Switzer for labels, JetBrains Mono in tracked capitals for data.
"""
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.patches import FancyBboxPatch

PAPER, OCEAN, CORAL = "#FFFFFF", "#0A2333", "#F23030"
STEEL_DARK, STEEL = "#3D6280", "#7BA6C4"          # kept / right, and partly: one hue, dark to light
TRACK, TRACK_EDGE = "#F3F5F7", "#C7CFD4"          # absent / did not know: neutral grey with a hairline
INK_2, INK_3, RULE = "#353E43", "#586369", "#E1E6EA"
W, SCALE = 820, 2                                 # drawn at 820 px wide, saved at twice that

FONTS = {}


CANDIDATES = {
    "body": ("Switzer400.ttf", "Switzer-Regular.ttf", "Switzer-Regular.otf"),
    "bold": ("Switzer500.ttf", "Switzer-Medium.ttf", "Switzer-Medium.otf"),
    "title": ("Erode500.ttf", "Erode-Medium.ttf", "Erode-Medium.otf"),
    "mono": ("JBMono500.ttf", "JetBrainsMono-Medium.ttf", "JetBrainsMono-Medium.otf"),
}


def load_fonts(folder):
    for key, names in CANDIDATES.items():
        found = [os.path.join(folder, n) for n in names if folder and os.path.exists(os.path.join(folder, n))]
        FONTS[key] = FontProperties(fname=found[0]) if found else FontProperties()


def canvas(height):
    fig = plt.figure(figsize=(W / 100, height / 100), dpi=100 * SCALE)
    fig.patch.set_facecolor(PAPER)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W); ax.set_ylim(height, 0); ax.axis("off")
    return fig, ax


def text(ax, x, y, s, size, font="body", color=OCEAN, ha="left", va="baseline"):
    return ax.text(x, y, s, fontproperties=FONTS[font], fontsize=size * 0.72, color=color, ha=ha, va=va)


def mono(ax, x, y, s, size=11, color=INK_3, track=0.12, ha="left"):
    """JetBrains Mono in capitals with letter-spacing, which matplotlib cannot do by itself."""
    s = s.upper()
    steps = [size * ((0.36 if ch == " " else 0.6) + track) for ch in s]     # a word space narrower than a letter
    if ha == "right":
        x -= sum(steps) - size * track
    for ch, step in zip(s, steps):
        ax.text(x, y, ch, fontproperties=FONTS["mono"], fontsize=size * 0.72, color=color, ha="left", va="baseline")
        x += step


def box(ax, x, y, w, h, fill, edge=None, r=4):
    w = max(w, 0.01)
    r = min(r, w / 2, h / 2)
    ax.add_patch(FancyBboxPatch((x + r, y + r), w - 2 * r, h - 2 * r, boxstyle="round,pad=%f,rounding_size=%f" % (r, r),
                                linewidth=0.8 if edge else 0, facecolor=fill, edgecolor=edge or "none"))


def stacked(ax, x, y, width, height, parts, gap=2):
    """parts: (count, fill, edge). Segments share the width in proportion, with a paper gap between them."""
    total = sum(n for n, _, _ in parts)
    shown = [(n, f, e) for n, f, e in parts if n]
    usable = width - gap * (len(shown) - 1)
    for n, fill, edge in shown:
        w = usable * n / total
        box(ax, x, y, w, height, fill, edge)
        x += w + gap


def header(ax, title):
    t = text(ax, 32, 56, title, 27, "title")
    ax.figure.canvas.draw()
    width, room = t.get_window_extent().width / SCALE, W - 64      # a wider fallback face must still fit
    if width > room:
        t.set_fontsize(t.get_fontsize() * room / width)


def legend(ax, y, items):
    x = 32
    for label, fill, edge in items:
        box(ax, x, y - 10, 14, 10, fill, edge, r=3)
        t = text(ax, x + 22, y, label, 14, color=INK_2)
        ax.figure.canvas.draw()
        x += 22 + t.get_window_extent().width / SCALE + 26


def value(ax, x, y, share, kept, n, bold=True):
    mono(ax, x + 50, y, "%d%%" % round(100 * share), 19, OCEAN, track=0.02, ha="right")
    mono(ax, x + 64, y - 1, "%d of %d" % (kept, n), 10.5)


def figure_1(replay, folder):
    q = replay["questions"]

    def pooled(k):      # the 1M sessions and the small ones together
        return {g: q["1M|%d" % k][g] + q["small|%d" % k][g] for g in ("right", "partly", "wrong", "unknown")}
    rows = [("Before any compaction", pooled(0)), ("After 1 compaction", pooled(1)), ("After 2 compactions", pooled(2)), ("After 3 compactions", pooled(3))]
    fig, ax = canvas(352)
    header(ax, "What Claude still knew of rules the user had typed")
    legend(ax, 96, [("Right", STEEL_DARK, None), ("Partly right", STEEL, None), ("Wrong", CORAL, None), ("Did not know", TRACK, TRACK_EDGE)])
    ax.plot([32, W - 32], [120, 120], color=RULE, linewidth=0.8)
    y = 164
    for label, c in rows:
        n = sum(c.values())
        text(ax, 32, y, label, 16)
        stacked(ax, 236, y - 17, 380, 22, [(c["right"], STEEL_DARK, None), (c["partly"], STEEL, None),
                                           (c["wrong"], CORAL, None), (c["unknown"], TRACK, TRACK_EDGE)])
        value(ax, 634, y, c["right"] / n, c["right"], n)
        y += 50
    fig.savefig(os.path.join(folder, "figure-01-rules-after-compactions.png"), facecolor=PAPER)
    plt.close(fig)


def figure_3(clusters, folder):
    by = clusters["by_order"]
    groups = [("First compaction", by["1"]), ("Second compaction", by["2"]), ("Third compaction", by["3"])]
    fig, ax = canvas(456)
    header(ax, "Recent rules survive a compaction. Most older ones do not.")
    text(ax, 32, 82, "Recent: typed since the last compaction. Older: typed before it.", 14.5, color=INK_3)
    legend(ax, 120, [("Kept in full", STEEL_DARK, None), ("Kept in part", STEEL, None), ("Absent", TRACK, TRACK_EDGE)])
    ax.plot([32, W - 32], [144, 144], color=RULE, linewidth=0.8)
    y = 186
    for name, b in groups:
        text(ax, 32, y, name, 16, "bold")
        for label, key in (("Recent rules", "recent"), ("Older rules", "older")):
            t = b[key]
            text(ax, 212, y, label, 15, color=INK_2)
            if t["n"]:
                stacked(ax, 326, y - 17, 290, 22, [(t["kept"], STEEL_DARK, None), (t["partly"], STEEL, None), (t["absent"], TRACK, TRACK_EDGE)])
                value(ax, 634, y, t["kept"] / t["n"], t["kept"], t["n"])
            else:
                ax.plot([326, 616], [y - 6, y - 6], color=TRACK_EDGE, linewidth=0.8, linestyle=(0, (2, 4)))
                mono(ax, 634, y - 1, "None yet", 10.5)
            y += 38
        y += 22
    fig.savefig(os.path.join(folder, "figure-03-kept-by-compaction.png"), facecolor=PAPER)
    plt.close(fig)


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    data = sys.argv[1] if len(sys.argv) > 1 else here
    images = sys.argv[2] if len(sys.argv) > 2 else here
    load_fonts(sys.argv[3] if len(sys.argv) > 3 else None)
    os.makedirs(images, exist_ok=True)
    figure_1(json.load(open(os.path.join(data, "results-replay.json"))), images)
    figure_3(json.load(open(os.path.join(data, "results-clusters.json"))), images)
    print("figures written to", images)
