#!/usr/bin/env python3
"""Regenerate the screenshots in assets/.

Runs bioinfoBook inside a hidden tmux window, types into it, captures the
screen with its colours, then lays each capture out as a styled terminal
window and renders it to PNG with headless Google Chrome.

    python3 scripts/screenshots.py            all scenes
    python3 scripts/screenshots.py search     just one

Needs: tmux and Google Chrome (macOS path below, or set CHROME=/path/to/chrome).
Your private cheats are never shown: the app runs with an empty BIOINFOBOOK_HOME.
"""
import html
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "bioinfobook.py"
OUT = ROOT / "assets"
CHROME = os.environ.get("CHROME") or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
COLS, ROWS = 124, 30
BASE = (30, 30, 46)
TEXT = (205, 214, 244)
REPO = "github.com/swamyshogan/bioinfoBook"

# name -> (caption, steps, formats). Steps: text to type, ("key", name), or a pause in seconds.
SCENES = {
    "search": ("Type a few letters — every 4th line of a FASTQ, found.",
               ["fastq", 0.25, ("key", "Down"), 0.8], ["wide", "square"]),
    "fill": ("Fill in the blanks, then it's on your clipboard.",
             ["pull out reads sequence", 0.5, ("key", "Enter"), 0.3, ("key", "C-u"), "sample_R1.fastq.gz",
              ("key", "Enter"), 0.2, "AGATCGGAAG", 0.6], ["wide"]),
    "copied": ("Enter copies it. Ctrl+T types it into your prompt.",
               ["color alphafold", 0.6, ("key", "Enter"), 0.17], ["wide"]),
}
FORMATS = {"wide": (1600, 900, 14.0), "square": (1080, 1080, 11.9)}


def tmux(*args, **kw):
    return subprocess.run(["tmux", "-L", "bioinfobook-shots", "-f", "/dev/null", *args],
                          capture_output=True, text=True, **kw)


def capture(steps):
    home = tempfile.mkdtemp(prefix="bioinfobook-shot-")
    tmux("kill-server")
    tmux("new-session", "-d", "-s", "s", "-x", str(COLS), "-y", str(ROWS),
         f"env BIOINFOBOOK_HOME={home} python3 '{APP}'; sleep 30")
    time.sleep(1.6)
    for step in steps:
        if isinstance(step, (int, float)):
            time.sleep(step)
        elif isinstance(step, tuple):
            tmux("send-keys", "-t", "s", step[1])
        else:
            tmux("send-keys", "-t", "s", "-l", step)
    screen = tmux("capture-pane", "-e", "-p", "-t", "s").stdout
    tmux("kill-server")
    return screen


def xterm256(n):
    if n < 16:
        return [(0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0), (0, 0, 238), (205, 0, 205), (0, 205, 205),
                (229, 229, 229), (127, 127, 127), (255, 0, 0), (0, 255, 0), (255, 255, 0), (92, 92, 255),
                (255, 0, 255), (0, 255, 255), (255, 255, 255)][n]
    if n < 232:
        n -= 16
        lv = (0, 95, 135, 175, 215, 255)
        return lv[n // 36], lv[(n // 6) % 6], lv[n % 6]
    v = 8 + 10 * (n - 232)
    return v, v, v


def ansi_to_html(text):
    rows = []
    for line in text.rstrip("\n").split("\n"):
        fg, bg, bold, cells = TEXT, BASE, False, []
        for part in re.split(r"(\x1b\[[0-9;]*m)", line):
            if not part.startswith("\x1b["):
                cells += [(ch, fg, bg, bold) for ch in part]
                continue
            codes = [int(c) if c else 0 for c in part[2:-1].split(";")]
            i = 0
            while i < len(codes):
                c = codes[i]
                if c == 0:
                    fg, bg, bold = TEXT, BASE, False
                elif c == 1:
                    bold = True
                elif c == 22:
                    bold = False
                elif c == 39:
                    fg = TEXT
                elif c == 49:
                    bg = BASE
                elif c in (38, 48) and i + 1 < len(codes):
                    col = None
                    if codes[i + 1] == 2 and i + 4 < len(codes):
                        col, i = tuple(codes[i + 2:i + 5]), i + 4
                    elif codes[i + 1] == 5 and i + 2 < len(codes):
                        col, i = xterm256(codes[i + 2]), i + 2
                    if col and c == 38:
                        fg = col
                    elif col:
                        bg = col
                i += 1
        cells += [(" ", TEXT, BASE, False)] * (COLS - len(cells))
        out, run, style = [], [], None
        for ch, f, b, bo in cells[:COLS]:
            if (f, b, bo) != style and run:
                out.append(span(run, style))
                run = []
            style = (f, b, bo)
            run.append(ch)
        if run:
            out.append(span(run, style))
        rows.append("".join(out))
    return "\n".join(rows)


def span(chars, style):
    f, b, bo = style
    css = f"color:rgb{f};" + (f"background:rgb{b};" if b != BASE else "") + ("font-weight:700;" if bo else "")
    return f'<span style="{css}">{html.escape("".join(chars))}</span>'


PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{ width: {w}px; height: {h}px; overflow: hidden; }}
  body {{
    font-family: -apple-system, "SF Pro Display", "Helvetica Neue", sans-serif;
    background:
      radial-gradient(900px 600px at 12% 8%, rgba(203,166,247,.30), transparent 60%),
      radial-gradient(800px 600px at 92% 95%, rgba(137,180,250,.28), transparent 60%),
      radial-gradient(600px 400px at 85% 10%, rgba(245,194,231,.18), transparent 60%),
      linear-gradient(160deg, #181825 0%, #11111b 100%);
    display: flex; flex-direction: column; align-items: center; justify-content: center; gap: {gap}px;
    color: #cdd6f4;
  }}
  .head {{ text-align: center; }}
  .title {{ font-size: {title}px; font-weight: 800; letter-spacing: -0.02em; line-height: 1.05; }}
  .title span {{ -webkit-background-clip: text; background-clip: text; color: transparent; }}
  .bio  {{ background-image: linear-gradient(90deg, #cba6f7, #b4befe, #89b4fa); }}
  .book {{ background-image: linear-gradient(90deg, #f5c2e7, #fab387); font-weight: 900; }}
  .sub {{ font-size: {sub}px; color: #bac2de; margin-top: 8px; }}
  .win {{
    background: #1e1e2e; border-radius: 14px; overflow: hidden;
    box-shadow: 0 40px 90px rgba(0,0,0,.55), 0 0 0 1px rgba(203,166,247,.22), 0 0 70px rgba(203,166,247,.10);
  }}
  .bar {{ height: 34px; display: flex; align-items: center; padding: 0 16px; gap: 8px;
          background: #181825; border-bottom: 1px solid #313244; position: relative; }}
  .dot {{ width: 12px; height: 12px; border-radius: 50%; }}
  .bar .name {{ position: absolute; left: 0; right: 0; text-align: center; font-size: 13px; color: #7f849c; }}
  pre {{ font-family: "SF Mono", Menlo, monospace; font-size: {font}px; line-height: 1.17;
         padding: 14px 18px 16px; color: #cdd6f4; white-space: pre; font-variant-ligatures: none; }}
  .foot {{ display: flex; gap: 14px; align-items: center; font-size: {small}px; color: #a6adc8; }}
  .pill {{ padding: 6px 14px; border-radius: 999px; background: rgba(49,50,68,.8); border: 1px solid #45475a; }}
  .pill b {{ color: #cba6f7; font-weight: 600; }}
</style></head><body>
  <div class="head">
    <div class="title"><span class="bio">bioinfo</span><span class="book">Book</span></div>
    <div class="sub">{caption}</div>
  </div>
  <div class="win">
    <div class="bar">
      <span class="dot" style="background:#f38ba8"></span>
      <span class="dot" style="background:#f9e2af"></span>
      <span class="dot" style="background:#a6e3a1"></span>
      <span class="name">bioinfoBook — zsh</span>
    </div>
    <pre>{screen}</pre>
  </div>
  <div class="foot">
    <span class="pill"><b>{repo}</b></span>
    <span>open source · bioinformatics cheat sheets in your terminal</span>
  </div>
</body></html>"""


def render(name, caption, screen, fmt, workdir):
    w, h, font = FORMATS[fmt]
    sq = fmt == "square"
    page = PAGE.format(w=w, h=h, font=font, caption=html.escape(caption), screen=ansi_to_html(screen),
                       repo=REPO, title=56 if sq else 52, sub=21 if sq else 20, small=15 if sq else 16,
                       gap=34 if sq else 30)
    page_path = Path(workdir) / f"{name}-{fmt}.html"
    page_path.write_text(page, "utf-8")
    png = OUT / f"bioinfobook-{name}-{fmt}.png"
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
                    f"--window-size={w},{h}", f"--screenshot={png}", page_path.as_uri()],
                   check=True, capture_output=True)
    print(png.relative_to(ROOT))


def main():
    OUT.mkdir(exist_ok=True)
    only = sys.argv[1:]
    with tempfile.TemporaryDirectory() as workdir:
        for name, (caption, steps, fmts) in SCENES.items():
            if only and name not in only:
                continue
            screen = capture(steps)
            for fmt in fmts:
                render(name, caption, screen, fmt, workdir)


if __name__ == "__main__":
    main()
