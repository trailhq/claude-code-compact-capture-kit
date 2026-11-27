"""Draw the two charts of the short post (draft v5) from the frozen results.

Usage: python3 analysis/make_chart_v5.py [data folder] [image folder]
Both folders default to the folder this script is in. Needs matplotlib.

Reads results-replay.json (freeze2.py) and results-clusters.json (freeze4.py). Nothing is typed in by hand except labels.
Same look and helpers as make_charts_v4.py.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_charts_v4 import BLUE, BLUE_MID, ORANGE, RULE, SURFACE, TEXT, TEXT_2, TRACK, Rectangle, canvas, legend, plt, stacked, text  # noqa: E402


def questions_chart(data, image_folder):
    """One panel: the seven replayed sessions together, by compactions since the rule was typed."""
    q = data["questions"]
    grades = ("right", "partly", "wrong", "unknown")
    rows = ["Before any compaction", "1 compaction since the rule was typed", "2 compactions since", "3 compactions since"]
    width, height = 820, 384
    fig, ax = canvas(width, height)
    text(ax, 24, 34, "What Claude still knew of the rules its user had typed", size=19, weight="semibold")
    text(ax, 24, 60, "Questions about typed rules, put to copies of seven real sessions replayed on Claude Code 2.1.327.", size=13.5, color=TEXT_2)
    legend(ax, 24, 92, [(BLUE, "Right"), (BLUE_MID, "Partly right"), (ORANGE, "Wrong"), (TRACK, "Said it did not know")])
    ax.add_patch(Rectangle((24, 114), width - 48, 1, color=RULE, linewidth=0))
    x0, track = 292, 336
    y = 148
    for since, label in enumerate(rows):
        v = {g: q["1M|%d" % since][g] + q["small|%d" % since][g] for g in grades}
        total = sum(v.values())
        text(ax, 24, y, label, size=13)
        stacked(ax, x0, y, track, 18, [(v["right"], BLUE, "#ffffff"), (v["partly"], BLUE_MID, TEXT), (v["wrong"], ORANGE, "#ffffff"), (v["unknown"], TRACK, TEXT)])
        text(ax, x0 + track + 14, y, "%d of %d right" % (v["right"], total), size=13, weight="semibold" if v["right"] * 2 < total else "regular")
        y += 38
    y += 14
    ax.add_patch(Rectangle((24, y - 22), width - 48, 1, color=RULE, linewidth=0))
    text(ax, 24, y, "Each bar pools the answers given that many compactions after the rule was typed; the number in a segment is a count of answers.", size=11.5, color=TEXT_2)
    text(ax, 24, y + 18, "Sessions come from the SWE-chat dataset: four were compacted near 1M tokens and three near 170K. claude-opus-5-5, automatic", size=11.5, color=TEXT_2)
    text(ax, 24, y + 36, "compaction only. A model wrote and graded the questions from the users' own messages. Three answers graded wrong are left out:", size=11.5, color=TEXT_2)
    text(ax, 24, y + 54, "the user had since replaced the rule, and Claude gave the new one.", size=11.5, color=TEXT_2)
    fig.savefig(os.path.join(image_folder, "figure-01-rules-after-compactions.png"), facecolor=SURFACE)
    plt.close(fig)


def order_chart(data, image_folder):
    """What the summary kept at a session's first, second and third compaction; later ones in the footnote."""
    by = data["by_order"]
    one = data["one_session"]
    rows = [("1", "A session's first compaction"), ("2", "Second compaction"), ("3", "Third compaction")]
    assert sum(by[k]["compactions"] for k in ("1", "2", "3", "4+")) == 383
    shown = sum(by[k]["compactions"] for k, _ in rows)
    width, height = 820, 424
    fig, ax = canvas(width, height)
    text(ax, 24, 34, "What each summary kept of the user's standing rules", size=19, weight="semibold")
    text(ax, 24, 60, "Rules and corrections that still mattered, at the first three compactions of real Claude Code sessions.", size=13.5, color=TEXT_2)
    legend(ax, 24, 92, [(BLUE, "Kept in full"), (BLUE_MID, "Partly kept"), (TRACK, "Absent")])
    left, col, track = 292, 262, 150
    text(ax, left, 128, "Typed since the last compaction", size=12.5, weight="semibold")
    text(ax, left + col, 128, "Typed before an earlier compaction", size=12.5, weight="semibold")
    ax.add_patch(Rectangle((24, 146), width - 48, 1, color=RULE, linewidth=0))
    y = 178
    for key, label in rows:
        b = by[key]
        text(ax, 24, y - 8, label, size=13)
        text(ax, 24, y + 10, "%d compactions" % b["compactions"], size=11.5, color=TEXT_2)
        for index, where in enumerate(("recent", "older")):
            t = b[where]
            x = left + index * col
            if t["n"] == 0:
                text(ax, x, y - 6, "No earlier compaction yet", size=12.5, color=TEXT_2)
                continue
            stacked(ax, x, y - 6, track, 16, [(t["kept"], BLUE, "#ffffff"), (t["partly"], BLUE_MID, TEXT), (t["absent"], TRACK, TEXT)])
            text(ax, x + track + 10, y - 6, "%d%% kept" % round(100 * t["kept"] / t["n"]), size=13, weight="semibold")
            text(ax, x, y + 14, "%d rules" % t["n"], size=11.5, color=TEXT_2)
        y += 56
    foot = y - 6
    ax.add_patch(Rectangle((24, foot - 22), width - 48, 1, color=RULE, linewidth=0))
    later, without = by["4+"], by["4+"]["older_without_the_one_session"]
    text(ax, 24, foot, "%d of the 383 judged compactions, from the SWE-chat dataset, recorded on Claude Code 2.1.76 to 2.1.259. claude-opus-5-5" % shown, size=11.5, color=TEXT_2)
    text(ax, 24, foot + 18, "judged each typed message against the summary that followed. Older messages are a sample of up to 40 a compaction.", size=11.5, color=TEXT_2)
    text(ax, 24, foot + 36, "The other %d compactions were a session's fourth or later: %d%% of recent rules kept and %d%% of older ones, or %d%% of older ones"
         % (later["compactions"], round(100 * later["recent"]["kept"] / later["recent"]["n"]), round(100 * later["older"]["kept"] / later["older"]["n"]),
            round(100 * without["kept"] / without["n"])), size=11.5, color=TEXT_2)
    text(ax, 24, foot + 54, "without one session that was compacted %d times and kept all %d of its older rules." % (one["compactions"], one["older"]["kept"]), size=11.5, color=TEXT_2)
    fig.savefig(os.path.join(image_folder, "figure-03-kept-by-compaction.png"), facecolor=SURFACE)
    plt.close(fig)


if __name__ == "__main__":
    data_folder = sys.argv[1] if len(sys.argv) > 1 else HERE
    image_folder = sys.argv[2] if len(sys.argv) > 2 else HERE
    os.makedirs(image_folder, exist_ok=True)
    questions_chart(json.load(open(os.path.join(data_folder, "results-replay.json"))), image_folder)
    order_chart(json.load(open(os.path.join(data_folder, "results-clusters.json"))), image_folder)
    print("charts written to", image_folder)
