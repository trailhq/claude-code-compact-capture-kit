#!/usr/bin/env python3
"""render_cast.py

Replays a terminal recording (asciicast v2, as written by tui-capture.py)
through xterm.js in headless Chrome and saves pictures of the terminal.

    render_cast.py frames <session.cast> <out dir>
        one picture of the terminal window at every marker, plus its text

    render_cast.py full <session.cast> <out dir> <marker label>
        one tall picture of everything on the terminal up to that marker,
        scrollback included, plus its text with line numbers

    render_cast.py crop <picture.png> <first line> <last line> <out.png>
        cut lines first..last (1-based, as numbered in the text file) out of
        a picture made by "frames" or "full"

The pictures show exactly the characters and colours the session wrote. The
font, the window colours and the padding are this script's.

Needs, next to this file: "npm install @xterm/xterm@5
@fontsource/noto-sans-symbols-2". Needs on the machine: Python with
playwright and Pillow, Google Chrome at /usr/bin/google-chrome, and the
fonts DejaVu Sans Mono and FreeMono. It was run on Linux; on another
system, change the Chrome path in open_page().
"""

import json
import os
import sys

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
XTERM = os.path.join(HERE, "node_modules", "@xterm", "xterm")
SYMBOLS = os.path.join(HERE, "node_modules", "@fontsource", "noto-sans-symbols-2", "files",
                       "noto-sans-symbols-2-symbols-400-normal.woff2")
SCALE = 2
PADDING_X = 22
PADDING_Y = 18

THEME = {
    "background": "#161618", "foreground": "#e4e4e4", "cursor": "#e4e4e4",
    "cursorAccent": "#161618", "selectionBackground": "#44475a",
    "black": "#1e1e1e", "red": "#f14c4c", "green": "#23d18b", "yellow": "#e5e510",
    "blue": "#3b8eea", "magenta": "#d670d6", "cyan": "#29b8db", "white": "#e5e5e5",
    "brightBlack": "#808080", "brightRed": "#ff6b6b", "brightGreen": "#3fe29b",
    "brightYellow": "#f5f543", "brightBlue": "#6cb0ff", "brightMagenta": "#e693e6",
    "brightCyan": "#56d4f0", "brightWhite": "#ffffff",
}

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="file://%(xterm)s/css/xterm.css">
<style>
  @font-face { font-family: 'ShotSymbols'; unicode-range: U+23F8-23FA;
               src: url("file://%(symbols)s") format("woff2"); }
  /* The context grid's pieces come from FreeMono, where they are drawn
     small. Scale them up to fill the cell, as a terminal font would. */
  @font-face { font-family: 'ShotGrid'; unicode-range: U+26C0-26C3, U+26DD, U+26F6;
               src: local("FreeMono"); size-adjust: 132%%; }
  html, body { margin: 0; background: %(bg)s; }
  #wrap { display: inline-block; padding: %(py)dpx %(px)dpx; background: %(bg)s; }
  .xterm-viewport { overflow: hidden !important; }
</style></head>
<body><div id="wrap"><div id="host"></div></div>
<script src="file://%(xterm)s/lib/xterm.js"></script>
<script>
  window.makeTerm = (cols, rows, theme, fontSize) => {
    if (window.xt) { window.xt.dispose(); document.getElementById('host').innerHTML = ''; }
    window.xt = new Terminal({
      cols, rows, theme, fontSize, scrollback: 50000, allowProposedApi: true,
      cursorBlink: false, cursorStyle: 'block', cursorInactiveStyle: 'none',
      fontFamily: "'DejaVu Sans Mono', 'ShotSymbols', 'ShotGrid', 'FreeMono', 'DejaVu Sans', monospace",
      lineHeight: 1.18, letterSpacing: 0, customGlyphs: true,
      drawBoldTextInBrightColors: false, minimumContrastRatio: 1,
    });
    window.xt.open(document.getElementById('host'));
  };
  window.feed = (data) => new Promise((resolve) => window.xt.write(data, resolve));
  window.settle = () => new Promise((resolve) =>
    requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 60))));
  window.viewport = () => {
    const b = window.xt.buffer.active, out = [];
    for (let i = 0; i < window.xt.rows; i++) {
      const line = b.getLine(b.viewportY + i);
      out.push(line ? line.translateToString(true) : '');
    }
    return out;
  };
  window.everything = () => {
    const b = window.xt.buffer.active, out = [];
    for (let i = 0; i < b.length; i++) {
      const line = b.getLine(i);
      out.push(line ? line.translateToString(true) : '');
    }
    return out;
  };
  window.used = () => {
    const b = window.xt.buffer.active;
    let last = b.length - 1;
    while (last > 0) {
      const line = b.getLine(last);
      if (line && line.translateToString(true).length) break;
      last--;
    }
    return last + 1;
  };
</script></body></html>
"""


def read_cast(path):
    with open(path, encoding="utf-8") as handle:
        header = json.loads(handle.readline())
        events = [json.loads(line) for line in handle if line.strip()]
    return header, events


def open_page(playwright, width, height):
    browser = playwright.chromium.launch(
        executable_path="/usr/bin/google-chrome",
        args=["--no-sandbox", "--force-color-profile=srgb", "--font-render-hinting=none"])
    context = browser.new_context(device_scale_factor=SCALE,
                                  viewport={"width": width, "height": height})
    page = context.new_page()
    html = os.path.join(HERE, "_page.html")
    with open(html, "w", encoding="utf-8") as handle:
        handle.write(PAGE % {"xterm": XTERM, "bg": THEME["background"],
                             "px": PADDING_X, "py": PADDING_Y, "symbols": SYMBOLS})
    page.goto("file://" + html)
    page.evaluate("document.fonts.load(\"14px ShotSymbols\", \"\u23fa\")")
    page.evaluate("document.fonts.load(\"14px ShotGrid\", \"\u26c1\")")
    page.evaluate("document.fonts.ready")
    return browser, page


def write_text(path, lines):
    width = len(str(len(lines)))
    with open(path, "w", encoding="utf-8") as handle:
        for number, line in enumerate(lines, 1):
            handle.write("%*d| %s\n" % (width, number, line))


def frames(cast_path, out_dir, font_size=14):
    header, events = read_cast(cast_path)
    os.makedirs(out_dir, exist_ok=True)
    with sync_playwright() as playwright:
        browser, page = open_page(playwright, 1700, 1400)
        page.evaluate("([c, r, t, f]) => makeTerm(c, r, t, f)",
                      [header["width"], header["height"], THEME, font_size])
        count = 0
        pending = []
        for when, kind, data in events:
            if kind == "o":
                pending.append(data)
            elif kind == "m":
                if pending:
                    page.evaluate("(d) => feed(d)", "".join(pending))
                    pending = []
                page.evaluate("settle()")
                count += 1
                stem = os.path.join(out_dir, "%02d-%s" % (count, data))
                page.locator("#wrap").screenshot(path=stem + ".png")
                write_text(stem + ".txt", page.evaluate("viewport()"))
                print("%s  %.1fs" % (os.path.basename(stem), when))
        browser.close()


def full(cast_path, out_dir, label, font_size=14):
    """Everything on the terminal up to a marker, scrollback included: the
    window is scrolled a page at a time and the pages are joined."""
    from PIL import Image
    import io
    header, events = read_cast(cast_path)
    os.makedirs(out_dir, exist_ok=True)
    chunks = []
    found = False
    for when, kind, data in events:
        if kind == "o":
            chunks.append(data)
        elif kind == "m" and data == label:
            found = True
            break
    if not found:
        sys.exit("no marker named %r in %s" % (label, cast_path))
    rows = header["height"]
    with sync_playwright() as playwright:
        browser, page = open_page(playwright, 1700, 1400)
        page.evaluate("([c, r, t, f]) => makeTerm(c, r, t, f)",
                      [header["width"], rows, THEME, font_size])
        page.evaluate("(d) => feed(d)", "".join(chunks))
        page.evaluate("settle()")
        used = max(page.evaluate("used()"), rows)
        lines = page.evaluate("everything()")[:used]
        starts = list(range(0, max(used - rows, 0) + 1, rows))
        if starts[-1] != used - rows:
            starts.append(used - rows)
        pages = []
        for start in starts:
            page.evaluate("(n) => window.xt.scrollToLine(n)", start)
            page.evaluate("settle()")
            shot = Image.open(io.BytesIO(page.locator("#wrap").screenshot()))
            pages.append((start, shot.convert("RGB")))
        browser.close()
    pad_x, pad_y = PADDING_X * SCALE, PADDING_Y * SCALE
    first = pages[0][1]
    row_height = (first.height - 2 * pad_y) / float(rows)
    height = int(round(used * row_height)) + 2 * pad_y
    canvas = Image.new("RGB", (first.width, height), THEME["background"])
    for start, shot in pages:
        inner = shot.crop((0, pad_y, shot.width, shot.height - pad_y))
        canvas.paste(inner, (0, pad_y + int(round(start * row_height))))
    stem = os.path.join(out_dir, "full-%s" % label)
    canvas.save(stem + ".png")
    write_text(stem + ".txt", lines)
    print("%s: %d lines, %dx%d" % (os.path.basename(stem), used, canvas.width, canvas.height))


def crop(picture, first, last, out_path, text_path=None):
    from PIL import Image
    text_path = text_path or os.path.splitext(picture)[0] + ".txt"
    total = sum(1 for _ in open(text_path, encoding="utf-8"))
    image = Image.open(picture)
    inner = image.height - 2 * PADDING_Y * SCALE
    row = inner / float(total)
    top = PADDING_Y * SCALE + int(round((first - 1) * row))
    bottom = PADDING_Y * SCALE + int(round(last * row))
    box = (0, max(0, top - PADDING_Y * SCALE), image.width,
           min(image.height, bottom + PADDING_Y * SCALE))
    piece = image.crop(box)
    # Paint the padding strips with the window colour, so neighbouring
    # lines do not show at the edges.
    from PIL import ImageDraw
    draw = ImageDraw.Draw(piece)
    pad = PADDING_Y * SCALE
    draw.rectangle([0, 0, piece.width, pad - 1], fill=THEME["background"])
    draw.rectangle([0, piece.height - pad, piece.width, piece.height], fill=THEME["background"])
    piece.save(out_path)
    print("%s: lines %d-%d, %dx%d" % (os.path.basename(out_path), first, last,
                                      piece.width, piece.height))


def main():
    arguments = sys.argv[1:]
    if len(arguments) >= 3 and arguments[0] == "frames":
        frames(arguments[1], arguments[2])
    elif len(arguments) >= 4 and arguments[0] == "full":
        full(arguments[1], arguments[2], arguments[3])
    elif len(arguments) >= 5 and arguments[0] == "crop":
        crop(arguments[1], int(arguments[2]), int(arguments[3]), arguments[4])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
