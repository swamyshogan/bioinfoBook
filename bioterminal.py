#!/usr/bin/env python3
"""
bioterminal — animated, colourful bioinformatics cheat sheets in your terminal.

Search as you type, press Enter, and the command is on your clipboard and in
your tmux buffer.  The cheat sheets are community-written JSON files, one per
tool, in db/.  Pure Python standard library.

    bioterminal                 open the picker
    bioterminal samtools sort   open the picker, pre-filtered
    bioterminal tools           list the available cheat sheets
    bioterminal help            everything else

Ideation by Shogan · Executed by Claude
"""
from __future__ import annotations

import argparse
import codecs
import fcntl
import json
import math
import os
import random
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import termios
import time
import tty
import unicodedata
from datetime import datetime
from functools import lru_cache
from pathlib import Path

VERSION = "0.1.0"
# Where people send suggestions. Change this once the repo is on GitHub (or set BIOTERMINAL_REPO).
REPO = os.environ.get("BIOTERMINAL_REPO") or "swamyshogan/bioterminal"

# ════════════════════════════════════════════════════════════════════════
#  Colour — catppuccin mocha
# ════════════════════════════════════════════════════════════════════════

C = {
    "rosewater": (245, 224, 220), "flamingo": (242, 205, 205), "pink": (245, 194, 231),
    "mauve": (203, 166, 247), "red": (243, 139, 168), "maroon": (235, 160, 172),
    "peach": (250, 179, 135), "yellow": (249, 226, 175), "green": (166, 227, 161),
    "teal": (148, 226, 213), "sky": (137, 220, 235), "sapphire": (116, 199, 236),
    "blue": (137, 180, 250), "lavender": (180, 190, 254), "text": (205, 214, 244),
    "subtext1": (186, 194, 222), "subtext0": (166, 173, 200), "overlay2": (147, 153, 178),
    "overlay1": (127, 132, 156), "overlay0": (108, 112, 134), "surface2": (88, 91, 112),
    "surface1": (69, 71, 90), "surface0": (49, 50, 68), "base": (30, 30, 46),
    "mantle": (24, 24, 37), "crust": (17, 17, 27),
}
TAG_PALETTE = [C[k] for k in ("pink", "mauve", "red", "peach", "yellow", "green", "teal",
                              "sky", "sapphire", "blue", "lavender", "flamingo", "maroon")]
BG = C["base"]
SEL_BG = (58, 54, 82)          # surface0 nudged toward mauve
CODE_BG = C["mantle"]
LOGO_GRAD = [C["mauve"], C["pink"], C["flamingo"], C["sky"], C["blue"]]
SPARKLE_COLS = [C["pink"], C["mauve"], C["yellow"], C["teal"], C["peach"], C["sky"], C["green"]]


def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else hi if v > hi else v


def mix(a, b, t):
    t = clamp(t)
    return (round(a[0] + (b[0] - a[0]) * t),
            round(a[1] + (b[1] - a[1]) * t),
            round(a[2] + (b[2] - a[2]) * t))


def gradient(stops, t):
    t = clamp(t)
    n = len(stops) - 1
    i = min(int(t * n), n - 1)
    return mix(stops[i], stops[i + 1], t * n - i)


def ease_out(p):
    p = clamp(p)
    return 1 - (1 - p) ** 3


def tool_color(tool):
    h = 0
    for ch in tool:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return TAG_PALETTE[h % len(TAG_PALETTE)]


def _detect_truecolor():
    v = os.environ.get("BIOTERMINAL_COLOR", "").lower()
    if v in ("truecolor", "24bit", "rgb"):
        return True
    if v in ("256", "8bit"):
        return False
    if os.environ.get("TMUX"):          # tmux down-converts by itself if it has to
        return True
    if os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return True
    return os.environ.get("TERM_PROGRAM") in ("iTerm.app", "WezTerm", "ghostty", "vscode", "Hyper", "Tabby")


TRUECOLOR = _detect_truecolor()
_LEVELS = (0, 95, 135, 175, 215, 255)


@lru_cache(maxsize=4096)
def to256(rgb):
    r, g, b = rgb

    def q(v):
        return 0 if v < 48 else 1 if v < 115 else (v - 35) // 40

    qr, qg, qb = q(r), q(g), q(b)
    cr, cg, cb = _LEVELS[qr], _LEVELS[qg], _LEVELS[qb]
    gi = int(clamp(round(((r + g + b) / 3 - 8) / 10), 0, 23))
    gv = 8 + 10 * gi
    dc = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
    dg = (r - gv) ** 2 + (g - gv) ** 2 + (b - gv) ** 2
    return 232 + gi if dg < dc else 16 + 36 * qr + 6 * qg + qb


@lru_cache(maxsize=16384)
def sgr(fg, bg, bold):
    if TRUECOLOR:
        s = f"\x1b[0;38;2;{fg[0]};{fg[1]};{fg[2]}"
        if bg is not None:
            s += f";48;2;{bg[0]};{bg[1]};{bg[2]}"
    else:
        s = f"\x1b[0;38;5;{to256(fg)}"
        if bg is not None:
            s += f";48;5;{to256(bg)}"
    return s + (";1m" if bold else "m")


# plain (non-picker) output ------------------------------------------------

COLOR_OUT = sys.stdout.isatty() and "NO_COLOR" not in os.environ


def paint(text, fg=None, bold=False, bg=None):
    if not COLOR_OUT or (fg is None and bg is None and not bold):
        return text
    return sgr(fg or C["text"], bg, bold) + text + "\x1b[0m"


def pill_text(it):
    return ("◆ " if it.get("private") else "") + it["label"]


def pill(it):
    c = tool_color(it["label"])
    return paint(f" {pill_text(it)} ", c, bg=mix(c, BG, 0.8))


def grad_text(text, stops=LOGO_GRAD, bold=True):
    if not COLOR_OUT:
        return text
    n = max(1, len(text) - 1)
    return "".join(paint(ch, gradient(stops, i / n), bold) for i, ch in enumerate(text))


def err(msg):
    sys.stderr.write(paint("  ✗ ", C["red"], True) + msg + "\n")


def ok(msg):
    print(paint("  ✓ ", C["green"], True) + msg)


# ════════════════════════════════════════════════════════════════════════
#  Text helpers
# ════════════════════════════════════════════════════════════════════════

@lru_cache(maxsize=8192)
def wcw(ch):
    if ch < " " or unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in "WF" else 1


def swidth(s):
    return sum(wcw(c) for c in s)


def trunc(s, w):
    if w <= 0:
        return ""
    if swidth(s) <= w:
        return s
    out, cur = [], 0
    for c in s:
        cw = wcw(c)
        if cur + cw > w - 1:
            break
        out.append(c)
        cur += cw
    return "".join(out) + "…"


def one_line(s):
    return " ⏎ ".join(l.strip() for l in s.replace("\t", "    ").splitlines() if l.strip())


def wrap_text(s, width):
    width = max(4, width)
    out = []
    for para in s.replace("\t", "    ").split("\n"):
        line = ""
        for word in para.split(" "):
            while swidth(word) > width:
                if line:
                    out.append(line)
                    line = ""
                out.append(word[:width])
                word = word[width:]
            if not line:
                line = word
            elif swidth(line) + 1 + swidth(word) <= width:
                line += " " + word
            else:
                out.append(line)
                line = word
        out.append(line)
    return out


# shell-ish syntax colouring ---------------------------------------------------

SH_RE = re.compile(r"""
  (?P<var>\{\{[^}]*\}\})
| (?P<str>'[^']*'?|"(?:\\.|[^"\\])*"?)
| (?P<comment>(?<!\S)\#.*$)
| (?P<env>\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*|\$[0-9@#?*$!-])
| (?P<op>\|\||&&|>>|2>&1|[|;&<>]|⏎)
| (?P<flag>(?<!\S)--?[A-Za-z0-9][\w\-]*(?:=[^\s'"]*)?)
| (?P<num>(?<![\w.])\d+(?:\.\d+)?(?![\w.]))
| (?P<word>[^\s'"|;&<>$#{⏎]+|[#{$])
| (?P<space>\s+)
""", re.X)
SH_COLORS = {"var": C["peach"], "str": C["green"], "comment": C["overlay1"], "env": C["yellow"],
             "op": C["pink"], "flag": C["blue"], "num": C["peach"], "space": C["text"]}
PREFIXES = {"sudo", "time", "env", "nohup", "watch", "xargs", "exec"}


def sh_spans(line):
    spans, expect_cmd = [], True
    for m in SH_RE.finditer(line):
        kind, text = m.lastgroup, m.group()
        bold = False
        if kind == "word":
            if expect_cmd:
                col, bold = C["mauve"], True
                expect_cmd = text in PREFIXES
            elif "/" in text or text.startswith("~") or text.startswith("."):
                col = C["sky"]
            else:
                col = C["text"]
        else:
            col = SH_COLORS[kind]
            bold = kind in ("var", "op")
            if kind == "op" and text in ("|", "||", "&&", ";", "⏎"):
                expect_cmd = True
            elif kind not in ("space",):
                expect_cmd = False if kind != "comment" else expect_cmd
        spans.append((text, col, bold))
    return spans


def span_chars(spans):
    return [(ch, col, bold) for text, col, bold in spans for ch in text if wcw(ch)]


def wrap_chars(chars, width):
    lines, cur = [[]], 0
    for item in chars:
        cw = wcw(item[0])
        if cur + cw > width:
            lines.append([])
            cur = 0
        lines[-1].append(item)
        cur += cw
    return lines


# fuzzy search -----------------------------------------------------------------

def fuzzy_pos(hay, needle):
    pos, j = [], 0
    for i, c in enumerate(hay):
        if j < len(needle) and c == needle[j]:
            pos.append(i)
            j += 1
    return pos if j == len(needle) else None


def field_score(text, tok):
    low = text.lower()
    i = low.find(tok)
    if i >= 0:
        return 10 + (4 if i == 0 or not low[i - 1].isalnum() else 0) + (2 if len(tok) == len(low) else 0)
    if len(tok) >= 2:
        p = fuzzy_pos(low, tok)
        if p:
            spread = p[-1] - p[0] + 1
            if spread <= len(tok) * 4:
                return max(1.0, 6 - (spread - len(tok)) * 0.4)
    return 0


def score(item, tokens):
    total = 0.0
    for tok in tokens:
        if tok.startswith("#") and len(tok) > 1:
            want = tok[1:]
            if not (item["label"].startswith(want) or (item["private"] and want in ("my", "mine", "private"))):
                return None
            total += 5
            continue
        best = max(field_score(item["title"], tok) * 3,
                   field_score(item["label"], tok) * 2.5,
                   field_score(item["cmd"], tok) * 2,
                   field_score(item.get("notes", ""), tok))
        if best <= 0:
            return None
        total += best
    return total + min(item.get("uses", 0), 25) * 0.4


def highlight_positions(text, tokens):
    low, out = text.lower(), set()
    for tok in tokens:
        if tok.startswith("#"):
            continue
        i = low.find(tok)
        if i >= 0:
            out.update(range(i, i + len(tok)))
        else:
            p = fuzzy_pos(low, tok)
            if p and p[-1] - p[0] + 1 <= len(tok) * 4:
                out.update(p)
    return out


def search(cheats, query):
    tokens = query.lower().split()
    if not tokens:
        return list(cheats)
    scored = [(s, it) for it in cheats if (s := score(it, tokens)) is not None]
    scored.sort(key=lambda p: (-p[0], p[1]["_order"]))
    return [it for _, it in scored]


# placeholders ------------------------------------------------------------------

PH_RE = re.compile(r"\{\{\s*([^}:]+?)\s*(?::\s*([^}]*?))?\s*\}\}")


def placeholders(cmd):
    seen, out = set(), []
    for m in PH_RE.finditer(cmd):
        name = m.group(1)
        if name not in seen:
            seen.add(name)
            out.append((name, m.group(2) or ""))
    return out


def fill_placeholders(cmd, values):
    return PH_RE.sub(lambda m: values.get(m.group(1), m.group(0)), cmd)


# ════════════════════════════════════════════════════════════════════════
#  Storage
# ════════════════════════════════════════════════════════════════════════

HERE = Path(__file__).resolve().parent
TOOL_KEYS = ("tool", "description", "homepage", "contributors")
CHEAT_KEYS = ("title", "cmd", "notes")
TOOLS = {}      # tool name -> {"path": Path, "meta": {...}} for every loaded file


def db_dir():
    """The community database: one JSON file per bioinformatics tool."""
    return Path(os.environ.get("BIOTERMINAL_DB") or HERE / "db").expanduser()


def config_dir():
    return Path(os.environ.get("BIOTERMINAL_HOME") or "~/.config/bioterminal").expanduser()


def private_dir():
    """Your own private cheats, one file per category. Outside the repo, never published."""
    return config_dir() / "private"


PRIVATE_PREFIX = "my-"   # private tool keys look like my-hpc so they never clash with db/ tools


def private_key(category):
    name = re.sub(r"[^a-z0-9._+-]+", "-", (category or "mine").strip().lower()).strip("-") or "mine"
    return PRIVATE_PREFIX + name


def state_path():
    """Per-machine usage counts, kept out of the database files."""
    return config_dir() / "state.json"


def _write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def format_tool_file(tool, meta, rows):
    """One cheat per line keeps the files easy to read, review and diff."""
    head = [f'  "tool": {json.dumps(tool)}']
    for k in TOOL_KEYS[1:]:
        if meta.get(k):
            head.append(f"  {json.dumps(k)}: {json.dumps(meta[k], ensure_ascii=False)}")
    body = ",\n    ".join(json.dumps({k: r[k] for k in CHEAT_KEYS if r.get(k)}, ensure_ascii=False) for r in rows)
    cheats = '  "cheats": [' + (f"\n    {body}\n  " if rows else "") + "]"
    return "{\n" + ",\n".join(head + [cheats]) + "\n}\n"


def load():
    try:
        state = json.loads(state_path().read_text("utf-8"))
    except (OSError, ValueError):
        state = {}
    uses, last = state.get("uses", {}), state.get("last_used", {})
    files = [(f, False) for f in sorted(db_dir().glob("*.json"))]
    files += [(f, True) for f in sorted(private_dir().glob("*.json"))]
    items = []
    TOOLS.clear()
    for f, private in files:
        try:
            data = json.loads(f.read_text("utf-8"))
        except ValueError as e:
            err(f"{f} isn't valid JSON: {e}")
            sys.exit(1)
        label = data.get("tool") or f.stem
        tool = private_key(f.stem) if private else label
        TOOLS[tool] = {"path": f, "label": label, "private": private,
                       "meta": {k: data[k] for k in TOOL_KEYS[1:] if data.get(k)}}
        for n, row in enumerate(data.get("cheats", []), 1):
            it = {"id": f"{tool}-{n}", "tool": tool, "label": label, "private": private, "title": row.get("title", ""),
                  "cmd": row.get("cmd", ""), "notes": row.get("notes", ""), "_order": len(items)}
            it["uses"] = uses.get(it["id"], 0)
            if it["id"] in last:
                it["last_used"] = last[it["id"]]
            items.append(it)
    return items


def _renumber(items):
    counts = {}
    for it in items:
        counts[it["tool"]] = counts.get(it["tool"], 0) + 1
        it["id"] = f"{it['tool']}-{counts[it['tool']]}"


def save_state(items):
    data = {"uses": {it["id"]: it["uses"] for it in items if it.get("uses")},
            "last_used": {it["id"]: it["last_used"] for it in items if it.get("last_used")}}
    _write_text(state_path(), json.dumps(data, indent=2) + "\n")


def save(items):
    """Write the tool files back (after add / edit / delete)."""
    _renumber(items)
    by_tool = {t: [] for t in TOOLS}
    for it in items:
        by_tool.setdefault(it["tool"], []).append(it)
    for tool, rows in by_tool.items():
        info = TOOLS[tool]
        _write_text(info["path"], format_tool_file(info["label"], info["meta"], rows))
    save_state(items)


def new_entry(items, cmd, title="", notes="", category="mine"):
    """Your own cheats always go into a private category file."""
    tool = private_key(category)
    if tool not in TOOLS:
        label = tool[len(PRIVATE_PREFIX):]
        TOOLS[tool] = {"path": private_dir() / f"{label}.json", "label": label, "private": True,
                       "meta": {"description": "My own commands" if label == "mine" else f"My {label} commands"}}
    info = TOOLS[tool]
    it = {
        "id": f"{tool}-{sum(1 for i in items if i['tool'] == tool) + 1}",
        "tool": tool,
        "label": info["label"],
        "private": True,
        "title": title.strip() or trunc(one_line(cmd), 60),
        "cmd": cmd.rstrip("\n"),
        "notes": notes.strip(),
        "uses": 0,
        "_order": len(items),
    }
    items.append(it)
    return it


def find_entry(items, ident):
    ident = str(ident).lstrip("#").lower()
    for it in items:
        if it["id"] == ident:
            return it
    err(f"no cheat called {ident} — ids look like samtools-3; see them with `bioterminal ls`")
    sys.exit(1)


# ════════════════════════════════════════════════════════════════════════
#  Clipboard / tmux
# ════════════════════════════════════════════════════════════════════════

def in_tmux():
    return bool(os.environ.get("TMUX")) and shutil.which("tmux") is not None


def copy_text(text):
    done = False
    for cmd in (["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "-ib"]):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=text.encode(), check=True, timeout=3)
                done = True
                break
            except (subprocess.SubprocessError, OSError):
                pass
    if in_tmux():
        subprocess.run(["tmux", "load-buffer", "-"], input=text.encode(), check=False)
        done = True
    if not done:  # OSC 52: ask the terminal itself to set the clipboard
        import base64
        try:
            with open("/dev/tty", "w") as t:
                t.write("\x1b]52;c;" + base64.b64encode(text.encode()).decode() + "\x07")
            done = True
        except OSError:
            pass
    return done


def tmux_type(text, pane=None, delay=0.0):
    """Type text into a tmux pane's prompt without running it.

    With a delay the keys are sent from a detached helper, so they land after
    the shell is back at its prompt instead of being echoed by the terminal."""
    target = ["-t", pane] if pane else []
    if "\n" in text:  # bracketed paste so the shell doesn't execute each line
        subprocess.run(["tmux", "load-buffer", "-b", "bioterminal", "-"], input=text.encode(), check=False)
        send = ["tmux", "paste-buffer", "-p", "-d", "-b", "bioterminal"] + target
    else:
        send = ["tmux", "send-keys"] + target + ["-l", text]
    if delay:
        subprocess.Popen(["sh", "-c", f"sleep {delay}; exec {shlex.join(send)}"], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.run(send, check=False)


def tty_stuff(text):
    """Push text into this terminal's input queue (outside tmux)."""
    if "\n" in text:
        text = "\x1b[200~" + text + "\x1b[201~"
    fd = os.open("/dev/tty", os.O_RDWR)
    try:
        # no echo while stuffing, or the text shows up twice; the shell sets
        # its own terminal modes again when it draws the prompt
        attrs = termios.tcgetattr(fd)
        attrs[3] &= ~termios.ECHO
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        for b in text.encode():
            fcntl.ioctl(fd, termios.TIOCSTI, bytes([b]))
    finally:
        os.close(fd)


# ════════════════════════════════════════════════════════════════════════
#  Terminal + canvas
# ════════════════════════════════════════════════════════════════════════

class Canvas:
    def __init__(self, w, h, bg=BG):
        self.w, self.h = w, h
        self.ch = [[" "] * w for _ in range(h)]
        self.fg = [[C["text"]] * w for _ in range(h)]
        self.bg = [[bg] * w for _ in range(h)]
        self.bo = [[False] * w for _ in range(h)]

    def _unwide(self, y, x):
        row = self.ch[y]
        if row[x] == "" and x > 0:
            row[x - 1] = " "
        elif x + 1 < self.w and row[x + 1] == "" and wcw(row[x]) == 2:
            row[x + 1] = " "

    def put(self, x, y, text, fg=C["text"], bg=None, bold=False, clip=None):
        if not 0 <= y < self.h:
            return x + swidth(text)
        right = self.w if clip is None else min(clip, self.w)
        rch, rfg, rbg, rbo = self.ch[y], self.fg[y], self.bg[y], self.bo[y]
        for c in text:
            cw = wcw(c)
            if cw == 0:
                continue
            if x + cw > right:
                break
            if x >= 0:
                self._unwide(y, x)
                if cw == 2:
                    self._unwide(y, x + 1)
                rch[x], rfg[x], rbo[x] = c, fg, bold
                if bg is not None:
                    rbg[x] = bg
                if cw == 2:
                    rch[x + 1], rfg[x + 1] = "", fg
                    if bg is not None:
                        rbg[x + 1] = bg
            x += cw
        return x

    def fill(self, x, y, w, h, bg):
        for yy in range(max(0, y), min(self.h, y + h)):
            for xx in range(max(0, x), min(self.w, x + w)):
                self._unwide(yy, xx)
                self.ch[yy][xx] = " "
                self.bg[yy][xx] = bg

    def dim(self, amount):
        """Fade everything drawn so far toward the background (behind a modal)."""
        for y in range(self.h):
            rfg, rbg = self.fg[y], self.bg[y]
            for x in range(self.w):
                rfg[x] = mix(rfg[x], BG, amount)
                rbg[x] = mix(rbg[x], BG, amount)

    def render(self):
        out = []
        for y in range(self.h):
            out.append(f"\x1b[{y + 1};1H")
            last = None
            rch, rfg, rbg, rbo = self.ch[y], self.fg[y], self.bg[y], self.bo[y]
            for x in range(self.w):
                c = rch[x]
                if c == "":
                    continue
                st = (rfg[x], rbg[x], rbo[x])
                if st != last:
                    out.append(sgr(*st))
                    last = st
                out.append(c)
        out.append("\x1b[0m")
        return "".join(out)


def draw_box(cv, x, y, w, h, color=None, title=None, title_fg=None, grad=None, bg=None):
    if w < 2 or h < 2:
        return
    if bg is not None:
        cv.fill(x, y, w, h, bg)

    def col(i):
        return gradient(grad, i / max(1, w - 1)) if grad else color

    cv.put(x, y, "╭", col(0))
    cv.put(x + w - 1, y, "╮", col(w - 1))
    cv.put(x, y + h - 1, "╰", col(0))
    cv.put(x + w - 1, y + h - 1, "╯", col(w - 1))
    for i in range(1, w - 1):
        cv.put(x + i, y, "─", col(i))
        cv.put(x + i, y + h - 1, "─", col(i))
    for j in range(1, h - 1):
        cv.put(x, y + j, "│", col(0))
        cv.put(x + w - 1, y + j, "│", col(w - 1))
    if title and w > len(title) + 6:
        cv.put(x + 2, y, f" {title} ", title_fg or col(2), bold=True)


KEY_RE = re.compile(r"\x1b[\[O](<?[\d;]*)([A-Za-z~])")
CSI_KEYS = {"A": "up", "B": "down", "C": "right", "D": "left", "H": "home", "F": "end", "Z": "shift-tab"}
TILDE_KEYS = {"1": "home", "7": "home", "4": "end", "8": "end", "5": "pgup", "6": "pgdn", "3": "delete"}


def parse_keys(s):
    keys, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\x1b":
            m = KEY_RE.match(s, i)
            if m:
                params, fin = m.groups()
                i = m.end()
                if params.startswith("<") and fin in "Mm":
                    try:
                        b, x, y = (int(v) for v in params[1:].split(";"))
                        keys.append(("mouse", b, x, y, fin == "M"))
                    except ValueError:
                        pass
                elif fin == "~" and params == "200":
                    end = s.find("\x1b[201~", i)
                    end = len(s) if end < 0 else end
                    keys.append(("paste", s[i:end]))
                    i = end + 6
                elif fin == "~":
                    keys.append(TILDE_KEYS.get(params.split(";")[0], "unknown"))
                else:
                    keys.append(CSI_KEYS.get(fin, "unknown"))
                continue
            keys.append("esc")
            i += 1
            continue
        if c == "\r":
            keys.append("enter")
        elif c in "\x7f\x08":
            keys.append("backspace")
        elif c == "\t":
            keys.append("tab")
        elif ord(c) < 32:
            keys.append("ctrl-" + chr(ord(c) + 96))
        else:
            keys.append(c)
        i += 1
    return keys


class Term:
    def __init__(self):
        self.fd = os.open("/dev/tty", os.O_RDWR)
        self.dec = codecs.getincrementaldecoder("utf-8")("replace")
        self.saved = None

    def start(self):
        self.saved = termios.tcgetattr(self.fd)
        tty.setraw(self.fd)
        # alt screen, hide cursor, no autowrap, SGR mouse, bracketed paste
        self.write("\x1b[?1049h\x1b[?25l\x1b[?7l\x1b[?1000h\x1b[?1006h\x1b[?2004h\x1b[2J")

    def stop(self):
        if self.saved is None:
            return
        try:
            self.write("\x1b[?2004l\x1b[?1006l\x1b[?1000l\x1b[?7h\x1b[0m\x1b[?25h\x1b[?1049l")
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)
        except (OSError, termios.error):
            pass  # the terminal is already gone (window or popup closed)
        self.saved = None

    def write(self, s):
        data = s.encode()
        while data:
            try:
                n = os.write(self.fd, data)
            except InterruptedError:
                continue
            data = data[n:]

    def size(self):
        try:
            sz = os.get_terminal_size(self.fd)
            return sz.columns, sz.lines
        except OSError:
            return 80, 24

    def read_keys(self, timeout):
        try:
            r, _, _ = select.select([self.fd], [], [], timeout)
        except InterruptedError:
            return []
        if not r:
            return []
        s = self.dec.decode(os.read(self.fd, 65536))
        # wait a moment for the rest of an escape sequence / paste
        for _ in range(20):
            unfinished = re.search(r"\x1b(\[[\d;<]*)?$", s) or ("\x1b[200~" in s and "\x1b[201~" not in s)
            if not unfinished or not select.select([self.fd], [], [], 0.03)[0]:
                break
            s += self.dec.decode(os.read(self.fd, 65536))
        return parse_keys(s)


# ════════════════════════════════════════════════════════════════════════
#  The picker
# ════════════════════════════════════════════════════════════════════════

FONT = {"b": ("█▄▄", "█▄█"), "i": ("█", "█"), "o": ("█▀█", "█▄█"), "t": ("▀█▀", " █ "),
        "e": ("█▀▀", "██▄"), "r": ("█▀█", "█▀▄"), "m": ("█▀▄▀█", "█ ▀ █"), "n": ("█▄ █", "█ ▀█"),
        "a": ("▄▀█", "█▀█"), "l": ("█  ", "█▄▄")}
LOGO = [" ".join(FONT[ch][row] for ch in "bioterminal") for row in (0, 1)]
TAGLINE = "bioinformatics cheat sheets in your terminal"
SPARK_CHARS = "✦✧⋆*+·•"


class Picker:
    def __init__(self, term, cheats, query="", pane=None, anim=True, print_mode=False):
        self.term, self.cheats = term, cheats
        self.query = query
        self.pane, self.anim, self.print_mode = pane, anim, print_mode
        now = time.monotonic()
        self.t0 = now if anim else now - 100
        self.sel, self.sel_anim, self.offset = 0, 0.0, 0
        self.mode = "list"            # list | confirm | fill | exiting
        self.fill = None
        self.toast = None             # (title, sub, color, t0, dur)
        self.particles = []
        self.exit_at = None
        self.quit = False
        self.result = None
        self.dying = None             # (id, t0)
        self.suspend_fn = None
        self.list_geom = None
        self.preview_id, self.preview_t = None, self.t0
        self.shimmer_t = self.t0 + 2.5
        self.results = []
        self.filter_t = self.t0
        self.count_anim = float(len(cheats))
        self.refilter(keep=False)

    # ── state ────────────────────────────────────────────────────────
    def refilter(self, keep=True):
        cur = self.current() if keep else None
        self.results = search(self.cheats, self.query)
        self.sel = 0
        if cur is not None and self.query == "":
            for i, it in enumerate(self.results):
                if it["id"] == cur["id"]:
                    self.sel = i
        self.sel_anim = min(self.sel_anim, max(0, len(self.results) - 1))
        self.filter_t = time.monotonic() if self.anim else 0

    def current(self):
        return self.results[self.sel] if 0 <= self.sel < len(self.results) else None

    def move(self, d):
        if self.results:
            self.sel = max(0, min(len(self.results) - 1, self.sel + d))

    def show_toast(self, title, sub, color, dur):
        now = time.monotonic()
        self.toast = (title, sub, color, now, dur)
        if self.anim:
            W, H = self.term.size()
            cx, cy = W / 2, H / 2
            for _ in range(34):
                a = random.uniform(0, 2 * math.pi)
                sp = random.uniform(10, 34)
                self.particles.append({
                    "x": cx + math.cos(a) * 6, "y": cy + math.sin(a) * 1.5,
                    "vx": math.cos(a) * sp, "vy": math.sin(a) * sp * 0.45 - 3,
                    "t0": now, "life": random.uniform(0.45, 0.95),
                    "ch": random.choice(SPARK_CHARS), "col": random.choice(SPARKLE_COLS)})

    # ── actions ──────────────────────────────────────────────────────
    def act(self, kind):
        it = self.current()
        if it is None:
            return
        ph = placeholders(it["cmd"])
        if ph:
            self.fill = {"kind": kind, "item": it, "vars": ph, "i": 0, "values": {}, "text": ph[0][1]}
            self.mode = "fill"
        else:
            self.finish(kind, it, it["cmd"])

    def finish(self, kind, it, text):
        it["uses"] = it.get("uses", 0) + 1
        it["last_used"] = datetime.now().isoformat(timespec="seconds")
        save_state(self.cheats)
        self.mode = "exiting"
        dur = 0.85
        if self.print_mode:
            self.result = ("print", text)
            self.show_toast("✓ Selected", trunc(one_line(text), 40), C["green"], 0.5)
            dur = 0.5
        elif kind == "copy":
            copy_text(text)
            self.result = ("copy", text)
            hint = "paste with ⌘V" + (" or prefix ]" if in_tmux() else "")
            self.show_toast("✓ Copied to clipboard", hint, C["green"], dur)
        else:
            if in_tmux() and self.pane:
                tmux_type(text, self.pane)
                self.result = ("typed", text)
            else:
                self.result = ("type-later", text)
            self.show_toast("↳ Typed into your prompt", "edit it, then press ⏎ to run", C["blue"], 0.6)
            dur = 0.6
        self.exit_at = time.monotonic() + (dur if self.anim else 0)

    def delete_now(self, it):
        self.cheats[:] = [c for c in self.cheats if c["id"] != it["id"]]
        save(self.cheats)
        q = self.sel
        self.refilter(keep=False)
        self.sel = min(q, max(0, len(self.results) - 1))

    def edit_current(self):
        it = self.current()
        if it is None:
            return

        def run():
            edit_entry_in_editor(it)
            save(self.cheats)
        self.suspend_fn = run

    def add_new(self):
        def run():
            print()
            it = interactive_add(self.cheats, argparse.Namespace(command=[], title=None, category=None,
                                                                 notes=None, last=False, editor=False,
                                                                 quick=False))
            if it:
                self.query = ""
                self.refilter(keep=False)
                self.sel = len(self.results) - 1
        self.suspend_fn = run

    # ── input ────────────────────────────────────────────────────────
    def handle(self, k):
        if self.mode == "exiting":
            if k in ("esc", "ctrl-c", "enter", "q"):
                self.exit_at = 0
            return
        if self.mode == "confirm":
            it = self.current()
            if k in ("y", "Y") and it:
                if self.anim:
                    self.dying = (it["id"], time.monotonic())
                else:
                    self.delete_now(it)
            self.mode = "list"
            return
        if self.mode == "fill":
            self.handle_fill(k)
            return

        if isinstance(k, tuple):
            if k[0] == "paste":
                self.query += " ".join(k[1].split())
                self.refilter()
            elif k[0] == "mouse":
                self.handle_mouse(*k[1:])
            return
        if k in ("ctrl-c", "ctrl-q"):
            self.quit = True
        elif k == "esc":
            if self.query:
                self.query = ""
                self.refilter()
            else:
                self.quit = True
        elif k == "enter":
            self.act("copy")
        elif k == "ctrl-t":
            self.act("type")
        elif k in ("up", "ctrl-p", "ctrl-k", "shift-tab"):
            self.move(-1)
        elif k in ("down", "ctrl-n", "ctrl-j", "tab"):
            self.move(1)
        elif k == "pgup":
            self.move(-(self.list_geom[3] if self.list_geom else 10))
        elif k == "pgdn":
            self.move(self.list_geom[3] if self.list_geom else 10)
        elif k == "home":
            self.move(-10 ** 9)
        elif k == "end":
            self.move(10 ** 9)
        elif k == "ctrl-d":
            if self.current():
                self.mode = "confirm"
        elif k == "ctrl-e":
            self.edit_current()
        elif k == "ctrl-a":
            self.add_new()
        elif k == "backspace":
            if self.query:
                self.query = self.query[:-1]
                self.refilter()
        elif k == "ctrl-u":
            self.query = ""
            self.refilter()
        elif k == "ctrl-w":
            self.query = re.sub(r"\S*\s*$", "", self.query.rstrip())
            self.refilter()
        elif isinstance(k, str) and len(k) == 1:
            self.query += k
            self.refilter()

    def handle_mouse(self, b, x, y, press):
        if b == 64:
            self.move(-1)
        elif b == 65:
            self.move(1)
        elif b == 0 and press and self.list_geom:
            x0, y0, w, rows = self.list_geom
            r = (y - 1) - y0
            if x0 <= x - 1 < x0 + w and 0 <= r < rows:
                i = self.offset + r
                if i < len(self.results):
                    if i == self.sel:
                        self.act("copy")
                    else:
                        self.sel = i

    def handle_fill(self, k):
        f = self.fill
        if k in ("esc", "ctrl-c"):
            self.fill, self.mode = None, "list"
        elif k == "enter":
            name, default = f["vars"][f["i"]]
            f["values"][name] = f["text"] or default
            f["i"] += 1
            if f["i"] >= len(f["vars"]):
                text = fill_placeholders(f["item"]["cmd"], f["values"])
                self.fill = None
                self.finish(f["kind"], f["item"], text)
            else:
                f["text"] = f["vars"][f["i"]][1]
        elif k == "backspace":
            f["text"] = f["text"][:-1]
        elif k == "ctrl-u":
            f["text"] = ""
        elif isinstance(k, tuple) and k[0] == "paste":
            f["text"] += k[1].replace("\n", " ")
        elif isinstance(k, str) and len(k) == 1:
            f["text"] += k

    # ── animation state ──────────────────────────────────────────────
    def update(self, dt, now):
        k = 1 - math.exp(-dt * 22) if self.anim else 1
        self.sel_anim += (self.sel - self.sel_anim) * k
        if abs(self.sel - self.sel_anim) < 0.02:
            self.sel_anim = float(self.sel)
        kc = 1 - math.exp(-dt * 14) if self.anim else 1
        self.count_anim += (len(self.results) - self.count_anim) * kc
        if abs(len(self.results) - self.count_anim) < 0.3:
            self.count_anim = float(len(self.results))
        cur = self.current()
        cid = cur["id"] if cur else None
        if cid != self.preview_id:
            self.preview_id, self.preview_t = cid, now if self.anim else 0
        for p in self.particles:
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["vx"] *= 1 - 2.2 * dt
            p["vy"] += 9 * dt
        self.particles = [p for p in self.particles if now - p["t0"] < p["life"]]
        if self.dying and now - self.dying[1] > 0.28:
            it = next((c for c in self.cheats if c["id"] == self.dying[0]), None)
            self.dying = None
            if it:
                self.delete_now(it)
        if self.anim and now > self.shimmer_t + 6:
            self.shimmer_t = now + random.uniform(0, 2)

    def animating(self, now):
        if not self.anim:
            return False
        return (now - self.t0 < 1.2 or self.particles or self.toast or self.dying
                or abs(self.sel - self.sel_anim) > 0 or abs(len(self.results) - self.count_anim) > 0
                or now - self.filter_t < 0.2 or now - self.preview_t < 0.2
                or 0 < now - self.shimmer_t < 1.0)

    # ── drawing ──────────────────────────────────────────────────────
    def draw(self, now):
        W, H = self.term.size()
        cv = Canvas(W, H)
        if W < 44 or H < 12:
            cv.put(1, 1, "✦ make the window a bit bigger", C["mauve"], bold=True)
            return cv
        m = 2 if W >= 70 else 1
        y = 1
        if H >= 24:
            self.draw_logo(cv, m + 1, y, now)
            y += 3
        self.draw_search(cv, m, y, W - 2 * m, now)
        y += 3
        top, ph = y, H - 1 - y
        if W >= 100:
            lw = int((W - 2 * m) * 0.56)
            list_box = (m, top, lw, ph)
            prev_box = (m + lw + 1, top, W - 2 * m - lw - 1, ph)
        else:
            prev_h = min(11, ph // 2) if ph >= 14 else 0
            list_box = (m, top, W - 2 * m, ph - prev_h)
            prev_box = (m, top + ph - prev_h, W - 2 * m, prev_h) if prev_h else None

        x, yy, w, h = list_box
        n = len(self.results)
        tagline = "commands" if not self.query else f"{n} match{'' if n == 1 else 'es'}"
        draw_box(cv, x, yy, w, h, C["surface1"], tagline, C["mauve"])
        self.draw_list(cv, x + 1, yy + 1, w - 2, h - 2, now)
        if prev_box:
            x, yy, w, h = prev_box
            draw_box(cv, x, yy, w, h, C["surface1"], "preview", C["lavender"])
            self.draw_preview(cv, x + 2, yy + 1, w - 4, h - 2, now)
        self.draw_footer(cv, m + 1, H - 1, W - 2 * m - 2)

        if self.mode == "fill":
            cv.dim(0.65)
            self.draw_fill(cv, W, H, now)
        self.draw_particles(cv, now)
        if self.toast:
            self.draw_toast(cv, W, H, now)
        return cv

    def draw_logo(self, cv, x, y, now):
        el = now - self.t0
        reveal = el * 95
        sweep = (now - self.shimmer_t) * 45 - 6
        n = len(LOGO[0])
        for row, line in enumerate(LOGO):
            for i, ch in enumerate(line):
                if ch == " " or i > reveal:
                    continue
                col = gradient(LOGO_GRAD, (i + row * 0.5) / n)
                edge = clamp(1 - (reveal - i) / 5)
                col = mix(col, C["rosewater"], edge * 0.9)
                col = mix(col, (255, 255, 255), math.exp(-((i - sweep) / 2.0) ** 2) * 0.6)
                cv.put(x + i, y + row, ch, col, bold=True)
        sub = TAGLINE
        tools = len({c["tool"] for c in self.cheats if not c["private"]})
        shown = int(clamp((el - 0.12) * 70, 0, 99))
        sx = x + n + 3
        cv.put(sx, y, sub[:shown], C["subtext0"])
        if shown >= len(sub):
            p = clamp((el - 0.5) / 0.3)
            cx = cv.put(sx, y + 1, "✦ ", mix(BG, C["yellow"], p))
            cx = cv.put(cx, y + 1, str(len(self.cheats)), mix(BG, C["mauve"], p), bold=True)
            cx = cv.put(cx, y + 1, " cheats · ", mix(BG, C["overlay1"], p))
            cx = cv.put(cx, y + 1, str(tools), mix(BG, C["pink"], p), bold=True)
            cv.put(cx, y + 1, " tools", mix(BG, C["overlay1"], p))

    def draw_search(self, cv, x, y, w, now):
        el = clamp((now - self.t0) / 0.3)
        grad = [mix(BG, c, ease_out(el)) for c in (C["mauve"], C["pink"], C["blue"])]
        draw_box(cv, x, y, w, 3, grad=grad)
        cx = cv.put(x + 2, y + 1, "❯ ", C["pink"], bold=True)
        total = f"/{len(self.cheats)}"
        num = str(int(round(self.count_anim)))
        rx = x + w - 2 - len(num) - len(total)
        cv.put(rx, y + 1, num, C["mauve"], bold=True)
        cv.put(rx + len(num), y + 1, total, C["overlay0"])
        avail = rx - cx - 3
        q = self.query
        while swidth(q) > avail and q:
            q = q[1:]
        cx = cv.put(cx, y + 1, q, C["text"], bold=True)
        pulse = 0.5 + 0.5 * math.sin(now * 6)
        if self.mode in ("list", "confirm"):
            cv.put(cx, y + 1, "▌", mix(C["mauve"], C["pink"], pulse))
        if not self.query:
            cv.put(cx + 2, y + 1, "type to search  ·  #tool to filter", C["overlay0"], clip=rx - 1)

    def draw_list(self, cv, x0, y0, w, rows, now):
        self.list_geom = (x0, y0, w, rows)
        res = self.results
        if not self.cheats:
            return self.draw_empty(cv, x0, y0, w, rows, now)
        if not res:
            msg = f"no matches for “{trunc(self.query, w - 20)}”"
            cy = y0 + rows // 2 - 1
            cv.put(x0 + (w - swidth(msg)) // 2, cy, msg, C["overlay1"])
            shrug = "¯\\_(ツ)_/¯"
            cv.put(x0 + (w - swidth(shrug)) // 2, cy + 2, shrug, C["peach"])
            return
        # keep the selection on screen with a 1-row margin
        if self.sel < self.offset + 1:
            self.offset = max(0, self.sel - 1)
        if self.sel > self.offset + rows - 2:
            self.offset = self.sel - rows + 2
        self.offset = max(0, min(self.offset, max(0, len(res) - rows)))

        tokens = self.query.lower().split()
        fade_q = ease_out((now - self.filter_t) / 0.16) if self.anim else 1
        visible = res[self.offset:self.offset + rows]
        tagw = min(16, max((len(pill_text(it)) for it in visible), default=0) + 2)
        for r, it in enumerate(visible):
            i = self.offset + r
            yy = y0 + r
            p = (now - (self.t0 + 0.14 + r * 0.02)) / 0.22
            if p <= 0:
                continue
            e = ease_out(p)
            dx = int(round((1 - e) * 10))
            alpha = e * (0.35 + 0.65 * fade_q)
            if self.dying and self.dying[0] == it["id"]:
                dp = clamp((now - self.dying[1]) / 0.28)
                alpha *= 1 - dp
                dx -= int(dp * 10)
            glow = max(0.0, 1 - abs(i - self.sel_anim))
            rowbg = mix(BG, SEL_BG, glow)
            cv.fill(x0, yy, w, 1, rowbg)

            def fa(c, a=alpha, bgc=rowbg):
                return mix(bgc, c, a)

            if i == self.sel:
                cv.put(x0, yy, "▌", fa(C["mauve"]), rowbg)
            xx = x0 + 2 + dx
            tc = tool_color(it["label"])
            label = trunc(pill_text(it), tagw - 2)
            cv.put(xx, yy, f" {label} ", fa(tc), fa(mix(tc, rowbg, 0.78)), bold=True)
            xx += tagw + 1
            right = x0 + w - 1
            span = right - xx
            tw = max(8, min(int(span * 0.45), 46))
            title = trunc(one_line(it["title"]), tw)
            hl = highlight_positions(title, tokens)
            base = mix(C["subtext0"], C["text"], glow)
            for j, ch in enumerate(title):
                if j in hl:
                    xx2 = cv.put(xx, yy, ch, fa(C["yellow"]), fa(mix(C["yellow"], rowbg, 0.82)), True)
                else:
                    xx2 = cv.put(xx, yy, ch, fa(base), None, glow > 0.5)
                xx = xx2
            xx = max(xx, x0 + 2 + dx + tagw + 1 + tw) + 2
            cw = right - xx
            if cw > 6:
                disp = one_line(it["cmd"])
                chars = span_chars(sh_spans(disp))
                hl = highlight_positions(disp, tokens)
                if len(chars) > cw:
                    chars = chars[:cw - 1] + [("…", C["overlay0"], False)]
                dim = 0.45 + 0.55 * glow
                for j, (ch, col, bold) in enumerate(chars):
                    if j in hl:
                        cv.put(xx, yy, ch, fa(C["teal"]), fa(mix(C["teal"], rowbg, 0.8)), True)
                    else:
                        cv.put(xx, yy, ch, fa(mix(rowbg, col, dim)), None, bold and glow > 0.5)
                    xx += 1
        # scrollbar on the right border
        if len(res) > rows:
            bx = x0 + w
            th = max(1, rows * rows // len(res))
            ty = int((rows - th) * self.offset / max(1, len(res) - rows))
            for r in range(rows):
                on = ty <= r < ty + th
                cv.put(bx, y0 + r, "┃" if on else "│", C["mauve"] if on else C["surface1"])

    def draw_empty(self, cv, x0, y0, w, rows, now):
        lines = [
            [("✦  ", "star"), ("nothing saved yet", C["text"]), ("  ✦", "star")],
            [],
            [("save your own commands   ", C["overlay1"]), ("bioterminal add", C["mauve"])],
            [],
            [("press ", C["overlay1"]), ("ctrl-a", C["pink"]), (" to add one right now", C["overlay1"])],
        ]
        cy = y0 + max(0, (rows - len(lines)) // 2)
        for n, parts in enumerate(lines):
            width = sum(swidth(t) for t, _ in parts)
            xx = x0 + (w - width) // 2
            for t, col in parts:
                if col == "star":
                    col = gradient(SPARKLE_COLS, 0.5 + 0.5 * math.sin(now * 3 + xx))
                xx = cv.put(xx, cy + n, t, col, bold=(n == 0))

    def draw_preview(self, cv, x0, y0, w, h, now):
        it = self.current()
        if it is None or w < 8 or h < 2:
            return
        a = ease_out((now - self.preview_t) / 0.18) if self.anim else 1

        def fa(c):
            return mix(BG, c, 0.25 + 0.75 * a)

        y, bottom = y0, y0 + h
        for line in wrap_text(it["title"], w)[:2]:
            cv.put(x0, y, line, fa(C["text"]), bold=True)
            y += 1
        tc = tool_color(it["label"])
        meta = TOOLS.get(it["tool"], {}).get("meta", {})
        if y < bottom:
            xx = cv.put(x0, y, f" {pill_text(it)} ", fa(tc), mix(BG, mix(tc, BG, 0.8), a), True) + 1
            if meta.get("description"):
                cv.put(xx + 1, y, trunc(meta["description"], x0 + w - xx - 1), fa(C["overlay1"]))
            y += 1
        y += 1
        # command block
        cmd_lines = []
        for line in it["cmd"].replace("\t", "    ").split("\n"):
            cmd_lines.extend(wrap_chars(span_chars(sh_spans(line)), w - 3) or [[]])
        room = bottom - y - 1
        notes = wrap_text(it["notes"], w) if it["notes"] else []
        max_cmd = room - (min(len(notes), 4) + 2 if notes else 0)
        max_cmd = max(1, max_cmd)
        if len(cmd_lines) > max_cmd:
            cmd_lines = cmd_lines[:max_cmd - 1] + [[("…", C["overlay0"], False)]]
        for chars in cmd_lines:
            if y >= bottom - 1:
                break
            cv.fill(x0, y, w, 1, CODE_BG)
            cv.put(x0, y, "▎", fa(tc), CODE_BG)
            xx = x0 + 2
            for ch, col, bold in chars:
                bgc = mix(CODE_BG, C["peach"], 0.18) if col == C["peach"] and bold else CODE_BG
                xx = cv.put(xx, y, ch, mix(CODE_BG, col, 0.25 + 0.75 * a), bgc, bold)
            y += 1
        if notes and y + 2 < bottom:
            y += 1
            cv.put(x0, y, "notes", fa(C["overlay1"]), bold=True)
            y += 1
            for line in notes:
                if y >= bottom - 1:
                    break
                cv.put(x0, y, line, fa(C["subtext0"]))
                y += 1
        foot = it["id"]
        if it.get("uses"):
            foot += f"  ·  used {it['uses']}×"
        if placeholders(it["cmd"]):
            foot += "  ·  has {{blanks}}"
        if it["private"]:
            foot += "  ·  private, only on this computer"
        elif meta.get("homepage"):
            foot += "  ·  " + re.sub(r"^https?://(www\.)?", "", meta["homepage"])
        cv.put(x0, bottom - 1, trunc(foot, w), fa(C["overlay0"]))

    def draw_footer(self, cv, x, y, w):
        if self.mode == "confirm" and self.current():
            t = trunc(one_line(self.current()["title"]), max(10, w - 40))
            xx = cv.put(x, y, " delete ", C["crust"], C["red"], True)
            xx = cv.put(xx + 1, y, f"“{t}”?  ", C["red"], bold=True)
            xx = cv.put(xx, y, "y", C["red"], bold=True)
            cv.put(xx, y, " yes · any other key keeps it", C["overlay1"])
            return
        hints = [("⏎", "copy"), ("^T", "type"), ("^A", "add"), ("^E", "edit"), ("^D", "delete"), ("esc", "quit")]
        if self.print_mode:
            hints[0] = ("⏎", "select")
        xx = x
        for key, label in hints:
            if xx + len(key) + len(label) + 4 > x + w:
                break
            xx = cv.put(xx, y, f" {key} ", C["mauve"], C["surface0"], True)
            xx = cv.put(xx + 1, y, label, C["overlay1"]) + 2

    def draw_fill(self, cv, W, H, now):
        f = self.fill
        bw = min(W - 6, 76)
        cmd_lines = []
        vals = dict(f["values"])
        name_now = f["vars"][f["i"]][0]
        vals_view = {**vals, name_now: f["text"] or "▁"}
        preview = fill_placeholders(f["item"]["cmd"], {k: "\x00" + v + "\x01" for k, v in vals_view.items()})
        for line in preview.split("\n")[:5]:
            cmd_lines.append(trunc(line.replace("\t", "    "), bw * 3))
        bh = 7 + min(len(cmd_lines), 5)
        bx, by = (W - bw) // 2, (H - bh) // 2
        draw_box(cv, bx, by, bw, bh, grad=[C["peach"], C["pink"], C["mauve"]], bg=C["mantle"])
        cv.put(bx + 2, by, " fill in the blanks ", C["peach"], C["mantle"], True)
        y = by + 2
        for line in cmd_lines:
            xx, inval = bx + 3, False
            for ch in line:
                if ch == "\x00":
                    inval = True
                    continue
                if ch == "\x01":
                    inval = False
                    continue
                if xx >= bx + bw - 3:
                    break
                col = C["green"] if inval else C["subtext0"]
                xx = cv.put(xx, y, ch, col, C["mantle"], inval)
            y += 1
        y += 1
        pulse = 0.5 + 0.5 * math.sin(now * 6)
        xx = cv.put(bx + 3, y, name_now, C["peach"], C["mantle"], True)
        xx = cv.put(xx, y, " ❯ ", C["pink"], C["mantle"], True)
        xx = cv.put(xx, y, f["text"], C["text"], C["mantle"], True, clip=bx + bw - 3)
        cv.put(xx, y, "▌", mix(C["peach"], C["pink"], pulse), C["mantle"])
        default = f["vars"][f["i"]][1]
        hint = f"{f['i'] + 1} of {len(f['vars'])}  ·  ⏎ next  ·  esc cancel"
        if default:
            hint = f"default: {default}  ·  " + hint
        cv.put(bx + 3, y + 2, trunc(hint, bw - 6), C["overlay0"], C["mantle"])

    def draw_toast(self, cv, W, H, now):
        title, sub, col, t0, dur = self.toast
        el = now - t0
        if el > dur + 0.2:
            return
        grow = ease_out(el / 0.16) if self.anim else 1
        fade = clamp((dur - el) / 0.22) if self.anim else 1
        full = max(swidth(title), swidth(sub)) + 8
        bw = max(4, int(full * grow))
        bh = 4
        bx, by = (W - bw) // 2, (H - bh) // 2
        bgc = mix(BG, mix(C["mantle"], col, 0.12), fade)
        draw_box(cv, bx, by, bw, bh, mix(BG, col, fade), bg=bgc)
        if grow > 0.9:
            cv.put((W - swidth(title)) // 2, by + 1, title, mix(bgc, col, fade), bgc, True)
            cv.put((W - swidth(sub)) // 2, by + 2, sub, mix(bgc, C["overlay1"], fade), bgc)

    def draw_particles(self, cv, now):
        for p in self.particles:
            x, y = int(round(p["x"])), int(round(p["y"]))
            if 0 <= x < cv.w and 0 <= y < cv.h:
                a = 1 - (now - p["t0"]) / p["life"]
                cv.put(x, y, p["ch"], mix(cv.bg[y][x], p["col"], a), bold=a > 0.5)

    # ── main loop ────────────────────────────────────────────────────
    def loop(self):
        last, prev, prev_size = time.monotonic(), None, None
        while True:
            now = time.monotonic()
            dt = min(0.1, now - last)
            last = now
            self.update(dt, now)
            if self.toast and now - self.toast[3] > self.toast[4] + 0.2:
                self.toast = None
            cv = self.draw(now)
            frame = cv.render()
            if (cv.w, cv.h) != prev_size:
                frame = "\x1b[2J" + frame
                prev_size = (cv.w, cv.h)
            if frame != prev:
                self.term.write(frame)
                prev = frame
            if self.quit or (self.exit_at is not None and now >= self.exit_at):
                return
            for k in self.term.read_keys(1 / 60 if self.animating(now) else 1 / 20):
                self.handle(k)
                if self.quit:
                    return
            if self.suspend_fn:
                fn, self.suspend_fn = self.suspend_fn, None
                self.term.stop()
                try:
                    fn()
                except (KeyboardInterrupt, EOFError):
                    print()
                self.term.start()
                prev, prev_size, last = None, None, time.monotonic()
                self.refilter()

    def after(self):
        """Runs once the screen is restored."""
        if not self.result:
            return
        kind, text = self.result
        out = sys.stderr if not sys.stdout.isatty() else sys.stdout
        if kind == "print":
            sys.stdout.write(text + "\n")
        elif kind == "copy":
            out.write(paint("  ✓ copied  ", C["green"], True) + paint(trunc(one_line(text), 70), C["subtext0"]) + "\n")
        elif kind == "type-later":
            if in_tmux():
                tmux_type(text, os.environ.get("TMUX_PANE"), delay=0.15)
            else:
                try:
                    tty_stuff(text)
                except OSError:
                    copy_text(text)
                    out.write(paint("  couldn't type it here — copied it instead ✓", C["yellow"]) + "\n")


def run_picker(args):
    cheats = load()
    try:
        term = Term()
    except OSError:
        err("bioterminal needs an interactive terminal")
        sys.exit(1)
    pane = args.pane
    if pane and "#{" in pane and in_tmux():  # format wasn't expanded — ask tmux
        pane = subprocess.run(["tmux", "display-message", "-p", "#{pane_id}"],
                              capture_output=True, text=True).stdout.strip() or None
    anim = not (args.no_anim or os.environ.get("BIOTERMINAL_NO_ANIM"))
    pk = Picker(term, cheats, " ".join(args.query), pane, anim, args.print)
    for s in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(s, lambda *_: sys.exit(1))
    try:
        term.start()
        pk.loop()
    finally:
        term.stop()
    pk.after()


# ════════════════════════════════════════════════════════════════════════
#  Prompts, editor, history
# ════════════════════════════════════════════════════════════════════════

def _tty_out():
    if sys.stdout.isatty():
        return sys.stdout
    try:
        return open("/dev/tty", "w")
    except OSError:
        return sys.stderr


def ask(label, default="", hint="", required=False):
    out = _tty_out()
    while True:
        line = paint("  ◆ ", C["mauve"], True) + paint(label, C["text"], True)
        if hint:
            line += paint(f"  {hint}", C["overlay0"])
        out.write(line + "\n")
        out.flush()
        try:
            import readline
            readline.set_startup_hook(lambda: readline.insert_text(default) if default else None)
        except Exception:
            readline = None
        try:
            if sys.stdout.isatty():
                val = input(paint("    › ", C["pink"], True) if not readline else "    › ")
            else:
                out.write("    › ")
                out.flush()
                val = sys.stdin.readline().rstrip("\n")
        finally:
            if readline:
                readline.set_startup_hook(None)
        if val.strip() or not required:
            return val.strip()
        out.write(paint("    this one's needed\n", C["red"]))


def flourish(text, anim=True):
    out = _tty_out()
    if not (COLOR_OUT and anim and out.isatty()):
        out.write(grad_text(text) + "\n")
        return
    n = len(text)
    for f in range(18):
        pos = f / 17 * (n + 8) - 4
        s = []
        for i, ch in enumerate(text):
            col = gradient(LOGO_GRAD, i / max(1, n - 1))
            col = mix(col, (255, 255, 255), math.exp(-((i - pos) / 2.5) ** 2) * 0.7)
            s.append(paint(ch, col, True) if i <= pos + 3 else " ")
        out.write("\r" + "".join(s))
        out.flush()
        time.sleep(0.022)
    out.write("\r" + grad_text(text) + "\n")


FORM_CMD = "─── command (everything below this line) ───"
FORM_NOTES = "─── notes (optional, below this line) ───"


def entry_form(it):
    return (f"# bioterminal {it.get('id', 'new')} — edit, save and close. Lines starting with # are ignored.\n"
            f"title: {it.get('title', '')}\n"
            f"{FORM_CMD}\n{it.get('cmd', '')}\n"
            f"{FORM_NOTES}\n{it.get('notes', '')}\n")


def parse_form(text):
    title, cmd, notes, section = "", [], [], "head"
    for line in text.split("\n"):
        if line.startswith("─── command"):
            section = "cmd"
        elif line.startswith("─── notes"):
            section = "notes"
        elif section == "head":
            if line.startswith("#"):
                continue
            if line.lower().startswith("title:"):
                title = line[6:].strip()
        elif section == "cmd":
            cmd.append(line)
        else:
            notes.append(line)
    return title, "\n".join(cmd).strip("\n"), "\n".join(notes).strip()


def run_editor(text):
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or ("nano" if shutil.which("nano") else "vi")
    fd, path = tempfile.mkstemp(suffix=".bioterminal.txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        subprocess.call(shlex.split(editor) + [path])
        return Path(path).read_text("utf-8")
    finally:
        os.unlink(path)


def edit_entry_in_editor(it):
    title, cmd, notes = parse_form(run_editor(entry_form(it)))
    if not cmd:
        err("the command was empty — nothing changed")
        return False
    it.update(title=title or trunc(one_line(cmd), 60), cmd=cmd, notes=notes)
    return True


def _unmetafy(raw):
    out, i = bytearray(), 0
    while i < len(raw):
        b = raw[i]
        if b == 0x83 and i + 1 < len(raw):
            out.append(raw[i + 1] ^ 0x20)
            i += 2
        else:
            out.append(b)
            i += 1
    return bytes(out)


def last_history_command():
    candidates = [os.environ.get("HISTFILE"), "~/.zsh_history", "~/.bash_history"]
    for c in candidates:
        if not c:
            continue
        p = Path(c).expanduser()
        if p.exists():
            break
    else:
        return None
    text = _unmetafy(p.read_bytes()[-300_000:]).decode("utf-8", "replace")
    entries, cur = [], None
    for line in text.split("\n"):
        m = re.match(r"^: \d+:\d+;(.*)$", line)
        body = m.group(1) if (m and cur is None) else line
        cur = body if cur is None else cur + "\n" + body
        if cur.endswith("\\"):
            cur = cur[:-1]
            continue
        entries.append(cur)
        cur = None
    for e in reversed(entries):
        e = e.strip()
        if e and not re.match(r"^(bioterminal|.*/bioterminal(\.py)?)(\s|$)", e):
            return e
    return None


# ════════════════════════════════════════════════════════════════════════
#  Sub-commands
# ════════════════════════════════════════════════════════════════════════

def interactive_add(cheats, a):
    cmd = " ".join(a.command).strip()
    if a.last:
        cmd = last_history_command() or ""
        if not cmd:
            err("couldn't find your last command in shell history")
            err('tip: bioterminal add "$(fc -ln -1)"')
            return None
    if a.editor:
        draft = {"cmd": cmd, "title": a.title or "", "notes": a.notes or ""}
        title, cmd, notes = parse_form(run_editor(entry_form(draft)))
        category = a.category or "mine"
        if not cmd:
            err("empty command — nothing saved")
            return None
    else:
        interactive = sys.stdin.isatty() and not a.quick
        if interactive:
            print(paint("  ✦ new private cheat", C["mauve"], True) +
                  paint(f"  saved in {private_dir()}, never shared", C["overlay0"]))
        if not cmd:
            if not interactive:
                err("give me a command:  bioterminal add 'samtools flagstat in.bam'")
                return None
            cmd = ask("command", required=True)
        elif interactive:
            print(paint("  ◆ ", C["mauve"], True) + paint("command", C["text"], True))
            print("    " + "".join(paint(t, c, b) for t, c, b in sh_spans(cmd)))
        title = a.title if a.title is not None else (ask("description", hint="what does it do? — this is what you'll search for") if interactive else "")
        cats = sorted(TOOLS[t]["label"] for t in TOOLS if TOOLS[t]["private"])
        hint = ("yours: " + ", ".join(cats) + "  ·  ") if cats else ""
        category = a.category if a.category is not None else (
            ask("category", default="", hint=hint + "e.g. hpc, lab, rnaseq (enter = mine)") if interactive else "")
        notes = a.notes if a.notes is not None else (ask("notes", hint="optional") if interactive else "")
    dup = next((c for c in cheats if c["cmd"].strip() == cmd.strip()), None)
    if dup:
        err(f"that one's already saved as {dup['id']} “{dup['title']}”")
        return None
    it = new_entry(cheats, cmd, title, notes, category or "mine")
    save(cheats)
    flourish(f"  ✦ saved {it['id']} · {trunc(it['title'], 50)}")
    print(paint("    find it again by searching its description, or ", C["overlay1"]) +
          paint(f"#{it['label']}", C["pink"], True))
    if placeholders(cmd):
        print(paint("    blanks found: ", C["overlay1"]) +
              paint(", ".join(n for n, _ in placeholders(cmd)), C["peach"], True) +
              paint(" — you'll be asked for them when you copy", C["overlay1"]))
    return it


def cmd_add(a):
    cheats = load()
    return 0 if interactive_add(cheats, a) else 1


def print_entry(it, tokens=()):
    head = paint(f"  {it['id']:<13}", C["overlay0"])
    print(head + pill(it) + " " + paint(it["title"], C["text"], True))
    for line in it["cmd"].split("\n"):
        print("        " + "".join(paint(t, c, b) for t, c, b in sh_spans(line)))
    if it.get("notes"):
        for line in it["notes"].split("\n"):
            print("        " + paint(line, C["overlay1"]))


def cmd_ls(a):
    cheats = load()
    q = " ".join(a.query)
    if a.tool:
        q += " " + " ".join("#" + t.lstrip("#").lower() for t in a.tool)
    items = search(cheats, q)
    if a.plain:
        for it in items:
            print(f"{it['id']}\t{it['label']}{' (private)' if it['private'] else ''}\t{it['title']}\t{one_line(it['cmd'])}")
        return 0
    if not items:
        print(paint("  nothing found", C["overlay1"]) + ("" if cheats else paint("  — try `bioterminal add`", C["overlay0"])))
        return 0
    for n, it in enumerate(items):
        if n:
            print(paint("  " + "┄" * 40, C["surface1"]))
        print_entry(it)
    print(paint(f"\n  {len(items)} of {len(cheats)}", C["overlay0"]))
    return 0


def resolve_and_fill(it):
    text = it["cmd"]
    ph = placeholders(text)
    if ph:
        vals = {}
        for name, default in ph:
            vals[name] = ask(name, default=default, hint=f"default: {default}" if default else "") or default
        text = fill_placeholders(text, vals)
    return text


def cmd_cp(a):
    cheats = load()
    it = find_entry(cheats, a.id)
    text = resolve_and_fill(it)
    copy_text(text)
    it["uses"] = it.get("uses", 0) + 1
    save_state(cheats)
    ok("copied  " + paint(trunc(one_line(text), 70), C["subtext0"]))
    return 0


def cmd_rm(a):
    cheats = load()
    it = find_entry(cheats, a.id)
    print_entry(it)
    if not a.yes:
        ans = ask("delete this one?", hint="y / n")
        if ans.lower() not in ("y", "yes"):
            print(paint("  kept it", C["overlay1"]))
            return 0
    cheats.remove(it)
    save(cheats)
    ok(f"deleted {it['id']}")
    return 0


def cmd_edit(a):
    cheats = load()
    it = find_entry(cheats, a.id)
    if edit_entry_in_editor(it):
        save(cheats)
        ok(f"updated {it['id']} · {it['title']}")
    return 0


def cmd_tools(a):
    cheats = load()
    counts = {}
    for c in cheats:
        counts[c["tool"]] = counts.get(c["tool"], 0) + 1
    tools = sorted((t for t in TOOLS if not TOOLS[t]["private"]), key=str.lower)
    mine = sorted((t for t in TOOLS if TOOLS[t]["private"]), key=str.lower)
    if a.markdown:
        print("| Tool | Cheats | What's covered | Homepage |\n|---|---:|---|---|")
        for t in tools:
            meta = TOOLS[t]["meta"]
            home = f"[link]({meta['homepage']})" if meta.get("homepage") else "—"
            print(f"| [{t}](db/{t}.json) | {counts.get(t, 0)} | {meta.get('description', '')} | {home} |")
        print(f"\n**{sum(counts.get(t, 0) for t in tools)} cheats across {len(tools)} tools.**")
        return 0
    if not tools:
        print(paint(f"  no cheat sheets in {db_dir()}", C["overlay1"]))
        return 0
    width = max(len(t) for t in tools) + 2
    for t in tools:
        meta = TOOLS[t]["meta"]
        print("  " + pill({"label": t}) + " " * (width - len(t) - 1) + paint(f"{counts.get(t, 0):>4} ", C["mauve"], True) +
              paint(meta.get("description", ""), C["subtext0"]))
    shared = sum(counts.get(t, 0) for t in tools)
    print(paint(f"\n  {shared} cheats in {len(tools)} tools", C["overlay1"]) +
          paint("  ·  missing something? ", C["overlay0"]) + paint("bioterminal suggest <tool>", C["mauve"]))
    if mine:
        print(paint("\n  your private categories", C["text"], True) + paint(f"  {private_dir()}", C["overlay0"]))
        for t in mine:
            info = TOOLS[t]
            print("  " + pill({"label": info["label"], "private": True}) + " " * max(1, width - len(info["label"]) - 3) +
                  paint(f"{counts.get(t, 0):>4} ", C["mauve"], True) + paint(info["meta"].get("description", ""), C["subtext0"]))
    return 0


def issue_url(template, **fields):
    from urllib.parse import urlencode
    return f"https://github.com/{REPO}/issues/new?" + urlencode({"template": template, **fields})


def open_url(url, just_print=False):
    print(paint("  ↗ ", C["blue"], True) + paint(url, C["sky"]))
    opener = shutil.which("open") or shutil.which("xdg-open")
    if opener and not just_print:
        subprocess.run([opener, url], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cmd_suggest(a):
    """Open a GitHub issue asking for a missing command or a whole new tool."""
    load()
    tool = (a.tool or "").lower()
    if tool and tool in TOOLS and not TOOLS[tool]["private"]:
        url = issue_url("add-command.yml", title=f"[{tool}] add: ", tool=tool)
        print(paint(f"  suggest a missing {tool} command", C["text"], True))
    elif tool:
        url = issue_url("new-tool.yml", title=f"New tool: {tool}", tool=tool)
        print(paint(f"  request cheat sheets for a new tool: {tool}", C["text"], True))
    else:
        url = f"https://github.com/{REPO}/issues/new/choose"
    open_url(url, a.print)
    return 0


def cmd_share(a):
    """Turn one of your private cheats into a suggestion for everyone."""
    cheats = load()
    it = find_entry(cheats, a.id)
    row = {k: it[k] for k in CHEAT_KEYS if it.get(k)}
    tool = (a.tool or it["label"]).lower()
    print_entry(it)
    print(paint("\n  check it has nothing private in it (usernames, hostnames, paths) before you submit", C["yellow"]))
    url = issue_url("add-command.yml", title=f"[{tool}] add: {it['title']}", tool=tool,
                    command=it["cmd"], description=it["title"], notes=it.get("notes", ""),
                    json=json.dumps(row, ensure_ascii=False))
    open_url(url, a.print)
    return 0


NAME_RE = re.compile(r"[a-z0-9][a-z0-9._+-]*")


def validate_file(path):
    """Problems with one community tool file — empty list if it's good."""
    try:
        data = json.loads(Path(path).read_text("utf-8"))
    except (OSError, ValueError) as e:
        return [f"not valid JSON: {e}"]
    if not isinstance(data, dict):
        return ["the file must be one JSON object: {\"tool\": …, \"description\": …, \"cheats\": […]}"]
    problems = []
    for k in set(data) - set(TOOL_KEYS) - {"cheats"}:
        problems.append(f"unknown field “{k}” (allowed: {', '.join(TOOL_KEYS)}, cheats)")
    tool = data.get("tool")
    if not isinstance(tool, str) or not NAME_RE.fullmatch(tool):
        problems.append("“tool” must be the tool's name in lowercase, e.g. \"samtools\"")
    elif tool != Path(path).stem:
        problems.append(f"the file must be named {tool}.json")
    if not isinstance(data.get("description"), str) or not data["description"].strip():
        problems.append("add a one-line “description” of what the cheats cover")
    hp = data.get("homepage")
    if hp is not None and not (isinstance(hp, str) and re.match(r"https?://", hp)):
        problems.append("“homepage” must be a URL starting with http:// or https://")
    co = data.get("contributors")
    if co is not None and not (isinstance(co, list) and all(isinstance(x, str) and x.strip() for x in co)):
        problems.append("“contributors” must be a list of GitHub usernames")
    cheats = data.get("cheats")
    if not isinstance(cheats, list) or not cheats:
        problems.append("“cheats” must be a list with at least one cheat")
        return problems
    seen = {}
    for i, c in enumerate(cheats, 1):
        where = f"cheat {i}"
        if not isinstance(c, dict):
            problems.append(f"{where}: must be an object with title and cmd")
            continue
        where += f" “{trunc(str(c.get('title', '')), 40)}”"
        for k in set(c) - set(CHEAT_KEYS):
            problems.append(f"{where}: unknown field “{k}” (allowed: {', '.join(CHEAT_KEYS)})")
        title, cmd = c.get("title"), c.get("cmd")
        if not isinstance(title, str) or not title.strip():
            problems.append(f"{where}: needs a “title”")
        elif len(title) > 80:
            problems.append(f"{where}: title is {len(title)} characters — keep it under 80, put detail in notes")
        if not isinstance(cmd, str) or not cmd.strip():
            problems.append(f"{where}: needs a “cmd”")
            continue
        if cmd.count("{{") != len(PH_RE.findall(cmd)) or cmd.count("{{") != cmd.count("}}"):
            problems.append(f"{where}: a {{{{blank}}}} isn't closed properly")
        if "notes" in c and not isinstance(c["notes"], str):
            problems.append(f"{where}: “notes” must be text")
        key = cmd.strip()
        if key in seen:
            problems.append(f"{where}: same command as cheat {seen[key]}")
        seen[key] = i
    return problems


def cmd_validate(a):
    files = [Path(f) for f in a.files] or sorted(db_dir().glob("*.json"))
    bad = 0
    for f in files:
        problems = validate_file(f)
        if problems:
            bad += 1
            print(paint("  ✗ ", C["red"], True) + paint(f.name, C["text"], True))
            for p in problems:
                print(paint("      · ", C["red"]) + p)
        else:
            n = len(json.loads(f.read_text("utf-8"))["cheats"])
            print(paint("  ✓ ", C["green"], True) + paint(f.name, C["text"], True) + paint(f"  {n} cheats", C["overlay1"]))
    if bad:
        print(paint(f"\n  {bad} file{'s need' if bad > 1 else ' needs'} fixing — see CONTRIBUTING.md", C["red"]))
        return 1
    print(paint(f"\n  all {len(files)} files look good ✦", C["green"]))
    return 0


# ════════════════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════════════════

HELP = [
    ("bioterminal [search…]", "open the picker (optionally pre-filtered)"),
    ("bioterminal tools", "list the cheat sheets      --markdown for a README table"),
    ("bioterminal ls [search]", "print matches              --tool NAME  --plain"),
    ("bioterminal cp <id>", "copy one by id, e.g. samtools-3"),
    ("bioterminal add [cmd]", "save a private cheat       -d description  -c category  -n notes  -l last  -e editor"),
    ("bioterminal edit <id>", "edit in $EDITOR"),
    ("bioterminal rm <id>", "delete one"),
    ("bioterminal suggest [tool]", "missing a command? opens a GitHub issue for it"),
    ("bioterminal share <id>", "suggest one of your private cheats for everyone"),
    ("bioterminal validate", "check db/ files before opening a pull request"),
]
KEYS = [("⏎", "copy to clipboard + tmux buffer"), ("^T", "type it into your prompt"), ("↑↓ ^P ^N", "move"),
        ("^A", "add"), ("^E", "edit"), ("^D", "delete"), ("^U", "clear search"), ("esc", "clear / quit")]


def print_help():
    print()
    for row, line in enumerate(LOGO):
        print("   " + "".join(paint(ch, gradient(LOGO_GRAD, (i + row * 0.5) / len(line)), True)
                              for i, ch in enumerate(line)))
    print(paint(f"   {TAGLINE} · v{VERSION}", C["overlay1"]))
    print(paint("   ideation by Shogan · executed by Claude\n", C["overlay0"]))
    for cmd, desc in HELP:
        print("   " + paint(f"{cmd:<27}", C["mauve"], True) + paint(desc, C["subtext0"]))
    print(paint("\n   in the picker", C["text"], True))
    for k, d in KEYS:
        print("   " + paint(f" {k} ", C["mauve"], True, C["surface0"]) + " " * (10 - len(k)) + paint(d, C["subtext0"]))
    print(paint("\n   tips", C["text"], True))
    print(paint("   • write ", C["subtext0"]) + paint("{{name}}", C["peach"], True) + paint(" or ", C["subtext0"]) +
          paint("{{name:default}}", C["peach"], True) + paint(" in a command and you'll be asked to fill it in", C["subtext0"]))
    print(paint("   • search ", C["subtext0"]) + paint("#samtools", C["pink"], True) + paint(" to show just one tool", C["subtext0"]))
    print(paint(f"   • cheat sheets: {db_dir()}  (one JSON file per tool)", C["subtext0"]))
    print(paint(f"   • your private cheats: {private_dir()}  (search ", C["subtext0"]) + paint("#my", C["pink"], True) +
          paint(" to list them)", C["subtext0"]))
    print()


def build_sub_parsers():
    p = argparse.ArgumentParser(prog="bioterminal", add_help=False)
    sub = p.add_subparsers(dest="sub")

    s = sub.add_parser("add", aliases=["new"])
    s.add_argument("command", nargs="*")
    s.add_argument("-d", "--title", "--desc", "--description")
    s.add_argument("-c", "--category")
    s.add_argument("-n", "--notes")
    s.add_argument("-l", "--last", action="store_true")
    s.add_argument("-e", "--editor", action="store_true")
    s.add_argument("-q", "--quick", action="store_true")
    s.set_defaults(fn=cmd_add)

    s = sub.add_parser("ls", aliases=["list"])
    s.add_argument("query", nargs="*")
    s.add_argument("-t", "--tool", action="append")
    s.add_argument("--plain", action="store_true")
    s.set_defaults(fn=cmd_ls)

    for name, aliases, fn in (("cp", ["copy"], cmd_cp), ("edit", [], cmd_edit), ("rm", ["del", "delete"], cmd_rm)):
        s = sub.add_parser(name, aliases=aliases)
        s.add_argument("id")
        if name == "rm":
            s.add_argument("-y", "--yes", action="store_true")
        s.set_defaults(fn=fn)

    s = sub.add_parser("tools")
    s.add_argument("--markdown", action="store_true")
    s.set_defaults(fn=cmd_tools)

    s = sub.add_parser("suggest")
    s.add_argument("tool", nargs="?")
    s.add_argument("--print", action="store_true")
    s.set_defaults(fn=cmd_suggest)

    s = sub.add_parser("share")
    s.add_argument("id")
    s.add_argument("-t", "--tool")
    s.add_argument("--print", action="store_true")
    s.set_defaults(fn=cmd_share)

    s = sub.add_parser("validate")
    s.add_argument("files", nargs="*")
    s.set_defaults(fn=cmd_validate)

    return p


SUBS = {"add", "new", "ls", "list", "cp", "copy", "edit", "rm", "del", "delete", "tools", "validate", "suggest", "share"}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("-h", "--help", "help"):
        print_help()
        return 0
    if argv and argv[0] in ("-V", "--version"):
        print(f"bioterminal {VERSION}")
        return 0
    try:
        if argv and argv[0] in SUBS:
            a = build_sub_parsers().parse_args(argv)
            return a.fn(a) or 0
        p = argparse.ArgumentParser(prog="bioterminal", add_help=False)
        p.add_argument("query", nargs="*")
        p.add_argument("--pane")
        p.add_argument("--no-anim", action="store_true")
        p.add_argument("--print", action="store_true")
        run_picker(p.parse_args(argv))
        return 0
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(main())
