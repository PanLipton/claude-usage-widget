# -*- coding: utf-8 -*-
"""Render a self-contained, anonymized preview.png for the README.

Uses fake e-mails / project names and the exact widget palette + layout so the
image stays faithful without exposing any real account data. Re-run after a
visual change:  python tools/generate_preview.py
"""
import os
from PIL import Image, ImageDraw, ImageFont

S = 2  # supersample for crisp text
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "preview.png")

# palette (mirrors claude_usage_widget.pyw)
C_PANEL = "#1b1b1f"; C_BORDER = "#2c2c33"; C_DIVIDER = "#26262c"
C_TEXT = "#e7e7ea"; C_EMAIL = "#cfcfd6"; C_MUTED = "#74747c"; C_LABEL = "#85858d"
C_TRACK = "#2c2c33"; C_OK = "#3fb950"; C_WARN = "#d29922"
C_BTN = "#6f6f78"; C_BTNBG = "#232329"
ACCENT = ["#58a6ff", "#bc8cff"]

PAD = 16; HEADER_H = 30; COL_GAP = 24
W = 516; H = 214

REG = "C:/Windows/Fonts/segoeui.ttf"
BLD = "C:/Windows/Fonts/segoeuib.ttf"
SYM = "C:/Windows/Fonts/seguisym.ttf"  # ◉ ✕ live here, not in segoeui


def f(bold, size):
    return ImageFont.truetype(BLD if bold else REG, size * S)


def sym(size):
    return ImageFont.truetype(SYM, size * S)


def color_for(p):
    return C_OK if p < 60 else (C_WARN if p < 85 else "#f85149")


img = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)


def rr(x1, y1, x2, y2, r, **kw):
    d.rounded_rectangle([x1 * S, y1 * S, x2 * S, y2 * S], radius=r * S, **kw)


def oval(x1, y1, x2, y2, fill):
    d.ellipse([x1 * S, y1 * S, x2 * S, y2 * S], fill=fill)


def text(x, y, s, font, fill, anchor="la"):
    d.text((x * S, y * S), s, font=font, fill=fill, anchor=anchor)


def tw(s, font):
    return d.textlength(s, font=font) / S


# panel
rr(1, 1, W - 1, H - 1, 16, fill=C_PANEL, outline=C_BORDER, width=S)

# header
oval(PAD, 14, PAD + 9, 23, C_OK)
text(PAD + 16, 18, "Claude Usage", f(True, 10), C_TEXT, "lm")
text(PAD + 132, 19, "updated 12s ago", f(False, 8), C_MUTED, "lm")
text(W - 66, 18, "+", f(True, 13), C_BTN, "mm")
text(W - 44, 18, "◉", sym(11), C_OK, "mm")
text(W - 22, 18, "✕", sym(10), C_BTN, "mm")

# accounts (fake data)
accounts = [
    {"email": "you@example.com", "label": "claude1", "acc": ACCENT[0],
     "session": 23, "s_reset": "4h 56m", "weekly": 41, "w_reset": "4h 26m"},
    {"email": "work@example.com", "label": "claude2", "acc": ACCENT[1],
     "session": 8, "s_reset": "3h 46m", "weekly": 62, "w_reset": "1d 00h"},
]
n = len(accounts)
inner_w = W - 2 * PAD
col_w = (inner_w - (n - 1) * COL_GAP) / n
top = HEADER_H + 8


def metric(x, y, w, label, pct, reset):
    col = color_for(pct)
    text(x, y, label, f(True, 8), C_LABEL, "la")
    text(x + w, y - 1, "%d%%" % pct, f(True, 10), col, "ra")
    by = y + 22; bh = 8
    rr(x, by, x + w, by + bh, bh / 2, fill=C_TRACK)
    fw = max(bh, w * pct / 100.0)
    rr(x, by, x + fw, by + bh, bh / 2, fill=col)
    ty = by + bh + 4
    text(x, ty, "resets in ", f(False, 8), C_MUTED, "la")
    text(x + tw("resets in ", f(False, 8)), ty, reset, f(False, 8), C_MUTED, "la")


for i, a in enumerate(accounts):
    x0 = PAD + i * (col_w + COL_GAP)
    if i > 0:
        dx = (x0 - COL_GAP / 2) * S
        d.line([dx, (top - 2) * S, dx, (H - 44) * S], fill=C_DIVIDER, width=S)
    # delete x (faint), label, email
    text(x0 + col_w, top - 1, "✕", sym(8), C_BTN, "ra")
    text(x0 + col_w - 16, top, a["label"], f(True, 9), a["acc"], "ra")
    text(x0, top, a["email"], f(True, 10), C_EMAIL, "la")
    metric(x0, top + 28, col_w, "SESSION", a["session"], a["s_reset"])
    metric(x0, top + 82, col_w, "WEEKLY", a["weekly"], a["w_reset"])

# projects
projects = [("my-web-app", ACCENT[0]), ("data-pipeline", ACCENT[1]),
            ("notes-cli", ACCENT[0])]
bh = 22; by = H - 32; sep_y = by - 9
d.line([PAD * S, sep_y * S, (W - PAD) * S, sep_y * S], fill=C_DIVIDER, width=S)
gap = 8
bw = (inner_w - (len(projects) - 1) * gap) / len(projects)
for j, (name, col) in enumerate(projects):
    x = PAD + j * (bw + gap)
    rr(x, by, x + bw, by + bh, 6, fill=C_BTNBG)
    cy = by + bh / 2
    oval(x + 9, cy - 3, x + 15, cy + 3, col)
    text(x + 21, cy, name, f(False, 9), C_TEXT, "lm")

img.save(OUT)
print("wrote", OUT, img.size)
