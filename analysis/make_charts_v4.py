"""Draw the two new charts of the /compact post from the frozen results.

Usage: python3 make_charts_v4.py <data folder> <image folder>

Reads results-real.json and results-replay.json, which freeze1.py and freeze2.py write from the judged
files. Nothing is typed in by hand except labels. Same look as make_charts.py, which drew the first charts.
"""
import glob
import json
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402

for path in glob.glob("/usr/share/fonts/opentype/inter/Inter-*.otf"):
    font_manager.fontManager.addfont(path)
plt.rcParams["font.family"] = ["Inter", "DejaVu Sans"]

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
RULE = "#e4e3de"
BLUE = "#2a78d6"        # kept, right
BLUE_MID = "#8cb8ee"    # partly
TRACK = "#e3e1db"       # absent, not known
ORANGE = "#eb6834"      # wrong
SCALE = 2


def canvas(width, height):
    fig = plt.figure(figsize=(width / 100, height / 100), dpi=100 * SCALE)
    fig.patch.set_facecolor(SURFACE)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, width)
    ax.set_ylim(height, 0)
    ax.axis("off")
    return fig, ax


def text(ax, x, y, words, size=14, color=TEXT, weight="regular", ha="left", va="center"):
    ax.text(x, y, words, fontsize=size * 0.72, color=color, fontweight=weight, ha=ha, va=va)


def stacked(ax, x, y, width, height, parts, gap=2):
    """parts: [(count, colour, ink for the number inside)]. Segments share the width by count, with a gap between."""
    total = sum(p[0] for p in parts)
    live = [p for p in parts if p[0] > 0]
    room = width - gap * (len(live) - 1)
    at = x
    for count, colour, ink in live:
        w = room * count / total
        ax.add_patch(FancyBboxPatch((at, y - height / 2), w, height, boxstyle="round,pad=0,rounding_size=%s" % min(4, w / 2),
                                    linewidth=0, facecolor=colour))
        if w >= 22:
            text(ax, at + w / 2, y + 0.5, str(count), size=11.5, color=ink, weight="semibold", ha="center")
        at += w + gap


def legend(ax, x, y, items):
    for colour, label in items:
        ax.add_patch(FancyBboxPatch((x, y - 5), 14, 10, boxstyle="round,pad=0,rounding_size=3", linewidth=0, facecolor=colour))
        text(ax, x + 20, y, label, size=12, color=TEXT_2)
        x += 20 + 7.1 * len(label) + 22
    return x


def questions_chart(data, image_folder):
    q = data["questions"]
    width, height = 820, 606
    fig, ax = canvas(width, height)
    text(ax, 24, 34, "What Claude still knew of the rules its user had typed", size=19, weight="semibold")
    text(ax, 24, 60, "Questions about typed rules, put to copies of seven real sessions replayed on Claude Code 2.1.327.", size=13.5, color=TEXT_2)
    legend(ax, 24, 92, [(BLUE, "Right"), (BLUE_MID, "Partly right"), (ORANGE, "Wrong"), (TRACK, "Said it did not know")])
    x0, track = 292, 336
    y = 128
    blocks = [("1M", "Four sessions compacted near 1M tokens"), ("small", "Three sessions compacted near 170K tokens")]
    rows = ["Before any compaction", "1 compaction since the rule was typed", "2 compactions since", "3 compactions since"]
    for key, title in blocks:
        ax.add_patch(Rectangle((24, y - 14), width - 48, 1, color=RULE, linewidth=0))
        text(ax, 24, y + 6, title, size=13.5, weight="semibold")
        y += 40
        for since, label in enumerate(rows):
            v = q["%s|%d" % (key, since)]
            total = sum(v.values())
            text(ax, 24, y, label, size=13)
            stacked(ax, x0, y, track, 18, [(v["right"], BLUE, "#ffffff"), (v["partly"], BLUE_MID, TEXT), (v["wrong"], ORANGE, "#ffffff"), (v["unknown"], TRACK, TEXT)])
            text(ax, x0 + track + 14, y, "%d of %d right" % (v["right"], total), size=13, weight="semibold" if v["right"] * 2 < total else "regular")
            y += 38
        y += 14
    ax.add_patch(Rectangle((24, y - 22), width - 48, 1, color=RULE, linewidth=0))
    text(ax, 24, y, "Each bar is one round of questions; the number in a segment is a count of answers. Sessions come from the public SWE-chat", size=11.5, color=TEXT_2)
    text(ax, 24, y + 18, "dataset. Claude Code 2.1.327, claude-opus-5-5, automatic compaction only. A model wrote and graded the questions from the", size=11.5, color=TEXT_2)
    text(ax, 24, y + 36, "users' own messages. Three answers graded wrong are left out: the user had since replaced the rule, and Claude gave the new one.", size=11.5, color=TEXT_2)
    fig.savefig(os.path.join(image_folder, "chart-rules-after-compactions.png"), facecolor=SURFACE)
    plt.close(fig)


def kept_chart(data, image_folder):
    bands = data["swechat_meaning"]["bands"]
    rows = [("manual", "Manual /compact"), ("auto_under_200k", "Automatic, under 200K tokens"),
            ("auto_200k_900k", "Automatic, 200K to 900K"), ("auto_900k_plus", "Automatic at the limit, 900K or more"),
            ("all", "All 383 compactions")]
    width, height = 820, 518
    fig, ax = canvas(width, height)
    text(ax, 24, 34, "What the summary kept of the user's standing rules", size=19, weight="semibold")
    text(ax, 24, 60, "Rules and corrections that still mattered, in 383 compactions of real Claude Code sessions.", size=13.5, color=TEXT_2)
    legend(ax, 24, 92, [(BLUE, "Kept in full"), (BLUE_MID, "Partly kept"), (TRACK, "Absent")])
    left, col, track = 292, 262, 150
    text(ax, left, 128, "Typed since the last compaction", size=12.5, weight="semibold")
    text(ax, left + col, 128, "Typed before an earlier compaction", size=12.5, weight="semibold")
    ax.add_patch(Rectangle((24, 146), width - 48, 1, color=RULE, linewidth=0))
    y = 178
    for key, label in rows:
        b = bands[key]
        if key == "all":
            ax.add_patch(Rectangle((24, y - 28), width - 48, 1, color=RULE, linewidth=0))
            y += 6
        text(ax, 24, y - 8, label, size=13, weight="semibold" if key == "all" else "regular")
        text(ax, 24, y + 10, "%d compactions" % b["compactions"] if key != "all" else "includes 8 idle compactions", size=11.5, color=TEXT_2)
        for index, where in enumerate(("recent", "older")):
            t = b[where]["rules_that_matter"]
            x = left + index * col
            stacked(ax, x, y - 6, track, 16, [(t["kept"], BLUE, "#ffffff"), (t["partly"], BLUE_MID, TEXT), (t["absent"], TRACK, TEXT)])
            text(ax, x + track + 10, y - 6, "%d%% kept" % round(100 * t["kept"] / t["n"]), size=13, weight="semibold")
            text(ax, x, y + 14, "%d rules" % t["n"], size=11.5, color=TEXT_2)
        y += 56
    foot = y - 6
    ax.add_patch(Rectangle((24, foot - 22), width - 48, 1, color=RULE, linewidth=0))
    text(ax, 24, foot, "Sessions from the public SWE-chat dataset, recorded on Claude Code 2.1.76 to 2.1.259. claude-opus-5-5 judged each", size=11.5, color=TEXT_2)
    text(ax, 24, foot + 18, "typed message against the summary that followed. Messages from before an earlier compaction are a sample of up to 40 a compaction.", size=11.5, color=TEXT_2)
    text(ax, 24, foot + 36, "An older rule is counted once at each later compaction that sampled it.", size=11.5, color=TEXT_2)
    fig.savefig(os.path.join(image_folder, "chart-kept-by-recency.png"), facecolor=SURFACE)
    plt.close(fig)


if __name__ == "__main__":
    data_folder, image_folder = sys.argv[1:3]
    os.makedirs(image_folder, exist_ok=True)
    questions_chart(json.load(open(os.path.join(data_folder, "results-replay.json"))), image_folder)
    kept_chart(json.load(open(os.path.join(data_folder, "results-real.json"))), image_folder)
    print("charts written to", image_folder)
