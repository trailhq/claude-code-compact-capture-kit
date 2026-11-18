"""Draw the post's two charts and one diagram from the run data.

Usage: python3 make_charts.py <data folder> <image folder>

Reads ladder_kinds.csv and request_sizes.csv, which ladder_kinds.py and
request_sizes.py write from the raw run files. Nothing is typed in by hand
except labels and the figures named in DIAGRAM below, which come from the
Source pack and are checked in the claims ledger.
"""
import csv
import glob
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle  # noqa: E402

for path in glob.glob("/usr/share/fonts/opentype/inter/Inter-*.otf"):
    font_manager.fontManager.addfont(path)
plt.rcParams["font.family"] = ["Inter", "DejaVu Sans"]

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
RULE = "#e4e3de"
BLUE = "#2a78d6"
BLUE_TRACK = "#cde2fb"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
GRAY_FILL = "#f1f0ec"
GRAY_LINE = "#8a8983"
SCALE = 2          # export at twice the layout size


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


def pill(ax, x, y, width, height, color):
    if width <= 0:
        return
    width = max(width, height)          # a sliver still reads as a rounded mark
    ax.add_patch(FancyBboxPatch((x, y - height / 2), width, height, boxstyle=f"round,pad=0,rounding_size={height / 2}",
                                linewidth=0, facecolor=color))


def kinds_chart(data_folder, image_folder):
    rows = [r for r in csv.DictReader(open(os.path.join(data_folder, "ladder_kinds.csv"))) if r["rule"] == "later answer counts"]
    checkpoints = []
    for r in rows:
        if r["checkpoint"] not in checkpoints:
            checkpoints.append(r["checkpoint"])
    names = [("typed", "Typed by the user", ""),
             ("file", "In an instruction file", ""),
             ("claude", "Stated by Claude in a reply", ""),
             ("read", "Only in tool output", "an outlier in a table Claude read"),
             ("script", "Only in tool output", "a value a script printed")]
    width, height = 820, 480
    fig, ax = canvas(width, height)
    text(ax, 24, 34, "What Claude could still answer after /compact", size=19, weight="semibold")
    text(ax, 24, 60, "Right answers, by where each fact came from. One session, compacted at four sizes.", size=13.5, color=TEXT_2)
    x0, column, track = 256, 138, 62
    text(ax, x0, 100, "Tokens before /compact, by Claude Code's count", size=12, color=TEXT_2)
    for index, name in enumerate(checkpoints):
        size = int(next(r for r in rows if r["checkpoint"] == name)["pre_tokens"])
        text(ax, x0 + index * column, 124, f"{round(size / 1000)}K", size=15, weight="semibold")
    ax.add_patch(Rectangle((24, 142), width - 48, 1, color=RULE, linewidth=0))
    step = 54
    for line, (kind, label, note) in enumerate(names):
        y = 172 + line * step
        if note:
            text(ax, 24, y - 9, label, size=14)
            text(ax, 24, y + 10, note, size=11.5, color=TEXT_2)
        else:
            text(ax, 24, y, label, size=14)
        for index, name in enumerate(checkpoints):
            r = next(r for r in rows if r["checkpoint"] == name and r["kind"] == kind)
            asked, right = int(r["asked"]), int(r["right_after"])
            x = x0 + index * column
            if asked == 0:                       # nothing of this kind had been planted yet
                text(ax, x, y, "none yet", size=12, color=TEXT_2)
                continue
            pill(ax, x, y, track, 10, BLUE_TRACK)
            pill(ax, x, y, track * right / asked, 10, BLUE)
            text(ax, x + track + 9, y, f"{right} of {asked}", size=13, color=TEXT if right < asked else TEXT_2,
                 weight="semibold" if right < asked else "regular")
        ax.add_patch(Rectangle((24, y + step / 2), width - 48, 1, color=RULE, linewidth=0))
    foot = 172 + len(names) * step - step / 2 + 30
    text(ax, 24, foot, "Each bar is the share of that kind's facts Claude answered correctly after the compaction. Before it, every answer was right.",
         size=11.5, color=TEXT_2)
    text(ax, 24, foot + 20, "Claude Code 2.1.311, claude-opus-5-5 at medium effort. One run, 17 Nov 2026. Questions went to copies of the session.",
         size=11.5, color=TEXT_2)
    fig.savefig(os.path.join(image_folder, "chart-what-survives.png"), facecolor=SURFACE)
    plt.close(fig)


def requests_chart(data_folder, image_folder):
    rows = {r["session"]: r for r in csv.DictReader(open(os.path.join(data_folder, "request_sizes.csv")))}
    sessions = [("connectors", "Account connectors loaded", "8 servers, 418 tools"),
                ("no-mcp", "No MCP servers", "started with --strict-mcp-config")]
    width, height = 820, 360
    fig, ax = canvas(width, height)
    text(ax, 24, 34, "The first request after /compact, in two recorded sessions", size=19, weight="semibold")
    text(ax, 24, 60, "Tokens in the last request before /compact and in the first one after.", size=13.5, color=TEXT_2)
    text(ax, 24, 80, "Both sessions ran /context before and after it.", size=13.5, color=TEXT_2)
    left, right, top = 262, 776, 142
    limit = 160000

    def xpos(value):
        return left + (right - left) * value / limit

    for tick in range(0, limit + 1, 40000):
        ax.add_patch(Rectangle((xpos(tick), top), 1, 148, color=RULE, linewidth=0))
        text(ax, xpos(tick), top + 164, "0" if tick == 0 else f"{tick // 1000}K", size=12, color=TEXT_2, ha="center")
    for line, (key, label, note) in enumerate(sessions):
        y = top + 50 + line * 68
        before, after = int(rows[key]["last_request_before"]), int(rows[key]["first_request_after"])
        text(ax, 24, y - 9, label, size=14)
        text(ax, 24, y + 11, note, size=11.5, color=TEXT_2)
        gap = 11 if after > before else -11
        ax.add_patch(FancyArrowPatch((xpos(before) + gap, y), (xpos(after) - gap, y), arrowstyle="-|>", mutation_scale=14,
                                     linewidth=1.5, color=GRAY_LINE, shrinkA=0, shrinkB=0))
        ax.add_patch(Circle((xpos(before), y), 6.5, facecolor=SURFACE, edgecolor=BLUE, linewidth=2))
        ax.add_patch(Circle((xpos(after), y), 8.5, facecolor=SURFACE, linewidth=0))
        ax.add_patch(Circle((xpos(after), y), 6.5, facecolor=BLUE, linewidth=0))
        text(ax, xpos(before), y - 21, f"{before:,}", size=13, ha="center")
        text(ax, xpos(after), y - 21, f"{after:,}", size=13, ha="center", weight="semibold")
    ax.add_patch(Circle((left + 7, 116), 6, facecolor=SURFACE, edgecolor=BLUE, linewidth=2))
    text(ax, left + 20, 116, "last request before /compact", size=12, color=TEXT_2)
    ax.add_patch(Circle((left + 232, 116), 6, facecolor=BLUE, linewidth=0))
    text(ax, left + 245, 116, "first request after", size=12, color=TEXT_2)
    text(ax, 24, 338, "Claude Code 2.1.311, claude-opus-5-5 at medium effort. One recorded session each, 17 Nov 2026, on one account.",
         size=11.5, color=TEXT_2)
    fig.savefig(os.path.join(image_folder, "chart-requests-before-after.png"), facecolor=SURFACE)
    plt.close(fig)


# Figures in the diagram: run 12 of the Source pack (recorded session, no MCP servers).
DIAGRAM = {"before": "92,583", "after": "54,877", "seconds": "22.8", "summary_words": "683"}


def box(ax, x, y, width, height, stripe=None, fill=GRAY_FILL):
    ax.add_patch(FancyBboxPatch((x, y), width, height, boxstyle="round,pad=0,rounding_size=6", linewidth=0, facecolor=fill))
    if stripe:
        ax.add_patch(FancyBboxPatch((x, y), 6, height, boxstyle="round,pad=0,rounding_size=3", linewidth=0, facecolor=stripe))


def diagram(image_folder):
    width, height = 820, 612
    fig, ax = canvas(width, height)
    text(ax, 24, 34, "What the next request holds after /compact", size=19, weight="semibold")
    text(ax, 24, 60, "One recorded session on Claude Code 2.1.311, with no MCP servers loaded.", size=13.5, color=TEXT_2)
    # before
    text(ax, 24, 98, "BEFORE", size=11, color=TEXT_2, weight="semibold")
    text(ax, 796, 98, f"{DIAGRAM['before']} tokens in the last request", size=12, color=TEXT_2, ha="right")
    box(ax, 24, 112, 772, 56)
    text(ax, 44, 131, "The conversation", size=14, weight="semibold")
    text(ax, 44, 151, "Your prompts, Claude's replies, tool calls and their output, the files Claude read", size=12, color=TEXT_2)
    # arrow
    ax.add_patch(FancyArrowPatch((410, 176), (410, 222), arrowstyle="-|>", mutation_scale=16, linewidth=1.5, color=GRAY_LINE))
    text(ax, 426, 192, "/compact", size=13.5, weight="semibold")
    text(ax, 426, 210, f"{DIAGRAM['seconds']} seconds", size=11.5, color=TEXT_2)
    # after
    text(ax, 24, 240, "AFTER", size=11, color=TEXT_2, weight="semibold")
    text(ax, 796, 240, f"{DIAGRAM['after']} tokens in the first request", size=12, color=TEXT_2, ha="right")
    parts = [
        (None, "Still applies", "The system prompt, the tools and the output style"),
        (BLUE, "Reloaded from disk", "Project-root CLAUDE.md, unscoped rules, auto memory, skill descriptions"),
        (ORANGE, "Written by Claude", f"The summary: nine parts, {DIAGRAM['summary_words']} words in this session"),
        (AQUA, "Kept word for word", "The most recent messages before the compaction"),
        (BLUE, "Read again from disk", "Up to five recently changed files. Here: two small rule files and three source files"),
    ]
    y = 254
    for stripe, head, words in parts:
        box(ax, 24, y, 772, 40, stripe=stripe)
        text(ax, 44, y + 20, head, size=13.5, weight="semibold")
        text(ax, 214, y + 20, words, size=12, color=TEXT_2)
        y += 46
    # not in the request
    ax.add_patch(Rectangle((24, y + 14), 772, 1, color=RULE, linewidth=0))
    text(ax, 24, y + 38, "NOT IN THE NEXT REQUEST", size=11, color=TEXT_2, weight="semibold")
    text(ax, 24, y + 62, "Everything else. It stays in the session's transcript, a JSONL file under ~/.claude/projects/.", size=13)
    text(ax, 24, y + 84, "As instructions, nested CLAUDE.md files and rules scoped with paths. They load when Claude touches a matching file.", size=13)
    text(ax, 24, y + 116, "Sources: the recorded session, and Anthropic's context window page, read 17 Nov 2026. Boxes are not to scale.",
         size=11.5, color=TEXT_2)
    fig.savefig(os.path.join(image_folder, "diagram-after-compact.png"), facecolor=SURFACE)
    plt.close(fig)


def main():
    data_folder, image_folder = sys.argv[1], sys.argv[2]
    os.makedirs(image_folder, exist_ok=True)
    kinds_chart(data_folder, image_folder)
    requests_chart(data_folder, image_folder)
    diagram(image_folder)
    for name in sorted(os.listdir(image_folder)):
        print(name, os.path.getsize(os.path.join(image_folder, name)), "bytes")


if __name__ == "__main__":
    main()
