# -*- coding: utf-8 -*-
"""
Claude Usage Widget — minimalist always-on-top desktop widget for Windows.

Shows, for every configured Claude account:
  * Session (5h) limit usage  + time until reset
  * Weekly  (7d) limit usage  + time until reset
  * The account e-mail and which CLI command (claude1 / claude2) maps to it
A bottom row of buttons opens a new console in one of the most-recent projects
and launches the matching Claude CLI there.

Data comes from the OAuth endpoints Claude Code itself uses:
  GET https://api.anthropic.com/api/oauth/usage    -> five_hour / seven_day utilization
  GET https://api.anthropic.com/api/oauth/profile  -> account e-mail
Tokens are read from each account's .credentials.json and transparently
refreshed (and written back) when they are about to expire.

No third-party dependencies — pure standard library (tkinter + urllib).
"""

import json
import os
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
CONFIG_EXAMPLE_PATH = os.path.join(HERE, "config.example.json")
STATE_PATH = os.path.join(HERE, "widget_state.json")
# Shared, machine-readable snapshot of the latest usage for every account.
# Other local tools (e.g. the E-Likarnya app) read this instead of hitting the
# OAuth usage endpoint themselves, so they don't burn extra rate-limited calls.
USAGE_STATE_PATH = os.path.join(HERE, "widget_usage.json")

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
PROFILE_URL = "https://api.anthropic.com/api/oauth/profile"
TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
USER_AGENT = "claude-cli/2.0.0 (external, cli)"
REFRESH_SKEW_SEC = 120  # refresh this long before expiry
CREATE_NEW_CONSOLE = 0x00000010
MAX_RECENT = 3

# Palette (dark, minimalist, cohesive)
C_KEY = "#000000"        # transparent-color key for rounded corners
C_PANEL = "#1b1b1f"
C_BORDER = "#2c2c33"
C_DIVIDER = "#26262c"
C_TEXT = "#e7e7ea"
C_EMAIL = "#cfcfd6"
C_MUTED = "#74747c"
C_LABEL = "#85858d"
C_TRACK = "#2c2c33"
C_OK = "#3fb950"
C_WARN = "#d29922"
C_CRIT = "#f85149"
C_BTN = "#6f6f78"
C_BTNBG = "#232329"
C_BTNBG_HOVER = "#30303a"
C_TIP_BG = "#0d0d0f"

# distinct per-account accent colours (identity, not utilization)
ACCOUNT_ACCENTS = ["#58a6ff", "#bc8cff", "#56d4c4", "#f0a868"]

FONT = "Segoe UI"

_ssl_ctx = ssl.create_default_context()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def expand(p):
    return os.path.expandvars(os.path.expanduser(p))


def load_config():
    """Load config.json, seeding it from config.example.json on first run.

    config.json is per-user (and git-ignored) so personal account paths never
    end up in version control; the committed example is the shared default.
    """
    if not os.path.exists(CONFIG_PATH) and os.path.exists(CONFIG_EXAMPLE_PATH):
        try:
            with open(CONFIG_EXAMPLE_PATH, "r", encoding="utf-8") as src:
                data = src.read()
            with open(CONFIG_PATH, "w", encoding="utf-8") as dst:
                dst.write(data)
        except OSError:
            pass
    path = CONFIG_PATH if os.path.exists(CONFIG_PATH) else CONFIG_EXAMPLE_PATH
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _http_json(url, method="GET", token=None, body=None, timeout=20):
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
        headers["anthropic-beta"] = "oauth-2025-04-20"
        headers["anthropic-version"] = "2023-06-01"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx) as r:
        return json.loads(r.read().decode())


def read_credentials(config_dir):
    path = os.path.join(config_dir, ".credentials.json")
    with open(path, "r", encoding="utf-8") as f:
        return path, json.load(f)


def refresh_token(cred_path, cred_data):
    """Refresh the OAuth token and write it back to .credentials.json."""
    oauth = cred_data["claudeAiOauth"]
    resp = _http_json(
        TOKEN_URL,
        method="POST",
        body={
            "grant_type": "refresh_token",
            "refresh_token": oauth["refreshToken"],
            "client_id": CLIENT_ID,
        },
    )
    oauth["accessToken"] = resp["access_token"]
    oauth["refreshToken"] = resp.get("refresh_token", oauth["refreshToken"])
    oauth["expiresAt"] = int(time.time() * 1000) + int(resp.get("expires_in", 0)) * 1000
    tmp = cred_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cred_data, f)
    os.replace(tmp, cred_path)
    return oauth["accessToken"]


def get_token(config_dir, force=False):
    """Return a valid access token, refreshing & persisting if needed."""
    cred_path, cred_data = read_credentials(config_dir)
    oauth = cred_data["claudeAiOauth"]
    expires_at = oauth.get("expiresAt", 0) / 1000.0
    if force or time.time() >= expires_at - REFRESH_SKEW_SEC:
        return refresh_token(cred_path, cred_data)
    return oauth["accessToken"]


def parse_reset(iso):
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def fetch_account(acc, prev=None):
    """Fetch live usage for one account -> dict consumed by the UI.

    `prev` is the previous state for this account. The e-mail (which never
    changes) is cached from it, and on a transient error the last-known
    usage values are kept so the widget shows stale data instead of blanking.
    """
    prev = prev or {}
    config_dir = expand(acc["config_dir"])
    out = {"label": acc.get("label", ""),
           "email": prev.get("email"),
           "five": prev.get("five"),
           "seven": prev.get("seven"),
           "loaded": prev.get("loaded", False),
           "error": None}
    try:
        token = get_token(config_dir)
        try:
            usage = _http_json(USAGE_URL, token=token)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                token = get_token(config_dir, force=True)
                usage = _http_json(USAGE_URL, token=token)
            else:
                raise
        five = usage.get("five_hour") or {}
        seven = usage.get("seven_day") or {}
        out["five"] = {"util": float(five.get("utilization") or 0.0),
                       "reset": parse_reset(five.get("resets_at"))}
        out["seven"] = {"util": float(seven.get("utilization") or 0.0),
                        "reset": parse_reset(seven.get("resets_at"))}
        out["loaded"] = True
        # e-mail never changes — fetch once, then cache from prev
        if not out["email"]:
            try:
                prof = _http_json(PROFILE_URL, token=token)
                out["email"] = (prof.get("account") or {}).get("email")
            except Exception:
                pass
    except FileNotFoundError:
        out["error"] = "no credentials"
    except urllib.error.HTTPError as e:
        out["error"] = "rate limited" if e.code == 429 else "HTTP %s" % e.code
    except urllib.error.URLError:
        out["error"] = "offline"
    except Exception as e:
        out["error"] = type(e).__name__
    return out


def write_usage_state(accounts_cfg, state):
    """Persist the latest per-account usage to widget_usage.json (atomic).

    Consumed by other local tools so they can show live session/weekly limits
    without spending their own API calls. Each account carries its expanded
    config_dir so a reader can match by login regardless of ordering.
    """
    accounts = []
    for i, acc in enumerate(accounts_cfg):
        s = state[i] if i < len(state) else {}
        accounts.append({
            "label": acc.get("label", ""),
            "config_dir": acc.get("config_dir", ""),
            "config_dir_expanded": expand(acc.get("config_dir", "")),
            "email": s.get("email"),
            "five": s.get("five"),
            "seven": s.get("seven"),
            "error": s.get("error"),
            "loaded": bool(s.get("loaded")),
        })
    data = {"updated_at": time.time(), "accounts": accounts}
    try:
        tmp = USAGE_STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, USAGE_STATE_PATH)
    except OSError:
        pass


def recent_projects(accounts, limit=MAX_RECENT):
    """Most-recent project dirs across all accounts (newest first).

    Each project is tagged with the account (claude1/claude2) that last used it,
    parsed from every account's history.jsonl.
    """
    best = {}  # path -> [timestamp, label]
    for acc in accounts:
        cdir = expand(acc["config_dir"])
        label = acc.get("label", "")
        hist = os.path.join(cdir, "history.jsonl")
        try:
            with open(hist, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    p = e.get("project")
                    ts = e.get("timestamp", 0) or 0
                    if not p:
                        continue
                    if p not in best or ts > best[p][0]:
                        best[p] = [ts, label]
        except FileNotFoundError:
            continue
        except Exception:
            continue
    items = [{"path": p, "ts": v[0], "label": v[1],
              "name": os.path.basename(p.rstrip("\\/")) or p}
             for p, v in best.items()]
    items.sort(key=lambda x: x["ts"], reverse=True)
    return items[:limit]


def claude_command(label):
    """Path to the claudeN.bat launcher, or the bare name if not found."""
    cand = os.path.join(os.path.expanduser("~"), ".local", "bin", label + ".bat")
    return cand if os.path.exists(cand) else label


def open_project(path, label):
    """Open a new console in `path` and launch the matching Claude CLI.

    The working directory is set via `cwd` (not a chained `cd`) so Windows
    argument quoting can't mangle the command.
    """
    cmd = claude_command(label)
    try:
        subprocess.Popen(["cmd", "/k", cmd], cwd=path,
                         creationflags=CREATE_NEW_CONSOLE)
    except Exception:
        try:  # directory may no longer exist — still open Claude somewhere
            subprocess.Popen(["cmd", "/k", cmd], creationflags=CREATE_NEW_CONSOLE)
        except Exception:
            pass


def fmt_delta(reset_epoch):
    if not reset_epoch:
        return "--"
    secs = int(reset_epoch - time.time())
    if secs <= 0:
        return "resetting"
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    if d > 0:
        return "%dd %02dh" % (d, h)
    if h > 0:
        return "%dh %02dm" % (h, m)
    return "%dm" % m


def color_for(pct):
    if pct >= 85:
        return C_CRIT
    if pct >= 60:
        return C_WARN
    return C_OK


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------
import tkinter as tk
import tkinter.font as tkfont


class Tooltip:
    """A single reusable hover tooltip."""

    def __init__(self, root):
        self.root = root
        self.win = None

    def show(self, text):
        self.hide()
        x, y = self.root.winfo_pointerxy()
        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        lbl = tk.Label(self.win, text=text, bg=C_TIP_BG, fg=C_EMAIL,
                       font=(FONT, 8), justify="left", padx=9, pady=6,
                       bd=1, relief="solid")
        lbl.configure(highlightbackground=C_BORDER)
        lbl.pack()
        self.win.geometry("+%d+%d" % (x + 14, y + 18))

    def hide(self):
        if self.win is not None:
            self.win.destroy()
            self.win = None


class UsageWidget:
    PAD = 16
    HEADER_H = 30
    COL_GAP = 24
    # collapsed (mini) view — one session-usage ring per account
    COLLAPSE_PAD = 14
    COLLAPSE_RING = 52     # outer ring diameter
    COLLAPSE_GAP = 18
    COLLAPSE_TOP = 24      # space above the rings for the title-bar buttons
    RING_TH = 7            # ring stroke thickness

    def __init__(self, root, config):
        self.root = root
        self.config = config
        self.accounts_cfg = config.get("accounts", [])
        self.poll = max(15, int(config.get("poll_seconds", 60)))
        self.topmost = True

        self.H_FULL = 214
        self.collapsed = bool(self._read_state().get("collapsed", False))
        if self.collapsed:
            self.W, self.H = self._collapsed_dims()
        else:
            self.W, self.H = self._calc_width(), self.H_FULL

        self.label_color = {a.get("label", ""): ACCOUNT_ACCENTS[i % len(ACCOUNT_ACCENTS)]
                            for i, a in enumerate(self.accounts_cfg)}

        # shared state written by the worker thread, read by the UI loop
        self.state = [
            {"label": a.get("label", ""), "email": None,
             "five": None, "seven": None, "error": None, "loaded": False}
            for a in self.accounts_cfg
        ]
        self.recent = recent_projects(self.accounts_cfg)
        self._proj_meta = {}
        self._hover_proj = None
        self._hover_del = None
        self._menu_win = None
        self._dragging = False
        self._dx = self._dy = 0
        self.last_update = 0.0
        self._stop = threading.Event()

        self.f_email = tkfont.Font(family=FONT, size=10, weight="bold")
        self.f_label = tkfont.Font(family=FONT, size=9, weight="bold")
        self.f_proj = tkfont.Font(family=FONT, size=9)
        self.f_small = tkfont.Font(family=FONT, size=8)

        self.tip = Tooltip(root)
        self._init_window()
        self._build_canvas()

        self.worker = threading.Thread(target=self._poll_loop, daemon=True)
        self.worker.start()
        self._tick()

    # -- window setup -------------------------------------------------------
    def _init_window(self):
        r = self.root
        r.overrideredirect(True)
        r.attributes("-topmost", self.topmost)
        try:
            r.attributes("-transparentcolor", C_KEY)
        except tk.TclError:
            pass
        x, y = self._load_pos()
        r.geometry("%dx%d+%d+%d" % (self.W, self.H, x, y))
        r.configure(bg=C_KEY)
        r.protocol("WM_DELETE_WINDOW", self.close)

    def _read_state(self):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _load_pos(self):
        s = self._read_state()
        try:
            return int(s["x"]), int(s["y"])
        except Exception:
            sw = self.root.winfo_screenwidth()
            return sw - self.W - 40, 60

    def _save_pos(self):
        try:
            with open(STATE_PATH, "w", encoding="utf-8") as f:
                json.dump({"x": self.root.winfo_x(), "y": self.root.winfo_y(),
                           "collapsed": self.collapsed}, f)
        except Exception:
            pass

    # -- canvas / drawing ---------------------------------------------------
    def _build_canvas(self):
        self.c = tk.Canvas(self.root, width=self.W, height=self.H,
                           bg=C_KEY, highlightthickness=0, bd=0)
        self.c.pack(fill="both", expand=True)

        # Dragging. Initiation is bound to the background "drag" tag so that
        # clicking buttons doesn't move the window, but the motion/release
        # handlers live on the canvas widget itself. The periodic render()
        # calls c.delete("all"), which destroys the tagged items; a tag-level
        # <B1-Motion> binding would stop firing the moment its item vanished,
        # freezing the drag until the next press. Widget-level bindings survive
        # item deletion, so the drag keeps tracking the cursor across renders.
        self.c.tag_bind("drag", "<Button-1>", self._drag_start)
        self.c.bind("<B1-Motion>", self._drag_move)
        self.c.bind("<ButtonRelease-1>", self._drag_end)

        # window buttons
        self.c.tag_bind("btn_pin", "<Button-1>", lambda e: self.toggle_pin())
        self.c.tag_bind("btn_close", "<Button-1>", lambda e: self.close())
        self.c.tag_bind("btn_add", "<Button-1>", lambda e: self._add_account_dialog())
        self.c.tag_bind("btn_collapse", "<Button-1>", lambda e: self.toggle_collapse())
        for tag in ("btn_pin", "btn_close", "btn_add", "btn_collapse"):
            self.c.tag_bind(tag, "<Enter>", lambda e: self.c.config(cursor="hand2"))
            self.c.tag_bind(tag, "<Leave>", lambda e: self.c.config(cursor=""))

        # per-account auth hint + delete tooltips (re-bound when accounts change)
        self._bind_account_tags()

        # recent-project buttons
        for j in range(MAX_RECENT):
            self.c.tag_bind("proj_%d" % j, "<Button-1>",
                            lambda e, j=j: self._open_proj(j))
            self.c.tag_bind("proj_%d" % j, "<Button-3>",
                            lambda e, j=j: self._proj_menu(e, j))
            self.c.tag_bind("proj_%d" % j, "<Enter>",
                            lambda e, j=j: self._proj_enter(j))
            self.c.tag_bind("proj_%d" % j, "<Leave>", lambda e: self._proj_leave())

    def _bind_account_tags(self):
        """(Re)bind per-account hover/delete handlers after the account set changes.

        Tk canvas bindings live on the tag name (not the item), so binding once
        per account-set change is enough even though items are redrawn each tick.
        """
        for i in range(len(self.accounts_cfg)):
            self.c.tag_bind("hint_%d" % i, "<Enter>",
                            lambda e, i=i: self.tip.show(self._hint_text(i)))
            self.c.tag_bind("hint_%d" % i, "<Leave>", lambda e: self.tip.hide())
            self.c.tag_bind("hint_%d" % i, "<Button-3>",
                            lambda e, i=i: self._delete_account(i))
            self.c.tag_bind("del_%d" % i, "<Button-1>",
                            lambda e, i=i: self._delete_account(i))
            self.c.tag_bind("del_%d" % i, "<Enter>",
                            lambda e, i=i: self._del_enter(i))
            self.c.tag_bind("del_%d" % i, "<Leave>", lambda e: self._del_leave())
            # collapsed-view session rings: hover for details, double-click expands
            self.c.tag_bind("ring_%d" % i, "<Enter>",
                            lambda e, i=i: self._ring_enter(i))
            self.c.tag_bind("ring_%d" % i, "<Leave>", lambda e: self._ring_leave())
            self.c.tag_bind("ring_%d" % i, "<Double-Button-1>",
                            lambda e: self.toggle_collapse())

    def _hint_text(self, i):
        a = self.accounts_cfg[i]
        label = a.get("label", "")
        cdir = a.get("config_dir", "")
        txt = ("%s   →   %s\n"
               "To (re)authorize: run  %s  in a terminal and run  /login\n"
               "(or click a project below)") % (label, cdir, label)
        if len(self.accounts_cfg) > 1:
            txt += "\nRight-click here to remove this account"
        return txt

    def _del_enter(self, i):
        self.c.config(cursor="hand2")
        self._hover_del = i

    def _del_leave(self):
        self.c.config(cursor="")
        self._hover_del = None

    def round_rect(self, x1, y1, x2, y2, r, **kw):
        if x2 - x1 < 2 * r:
            r = max(0, (x2 - x1) / 2)
        if y2 - y1 < 2 * r:
            r = max(0, (y2 - y1) / 2)
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r,
               x2, y2, x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r,
               x1, y1 + r, x1, y1]
        return self.c.create_polygon(pts, smooth=True, **kw)

    def render(self):
        """Dispatch to the full or the collapsed (mini-ring) layout."""
        if self.collapsed:
            self._render_collapsed()
        else:
            self._render_full()

    def _render_full(self):
        c = self.c
        c.delete("all")
        W, H = self.W, self.H

        # panel
        self.round_rect(1, 1, W - 1, H - 1, 16, fill=C_PANEL,
                        outline=C_BORDER, width=1, tags="drag")

        # header
        err = self._first_error()
        has_data = any(a.get("loaded") for a in self.state)
        if not self.last_update:
            dot = C_MUTED
        elif err and has_data:
            dot = C_WARN          # stale: showing last-known values
        elif err:
            dot = C_CRIT          # error and nothing to show
        else:
            dot = C_OK
        c.create_oval(self.PAD, 14, self.PAD + 9, 23, fill=dot, outline="",
                      tags="drag")
        c.create_text(self.PAD + 16, 18, text="Claude Usage", anchor="w",
                      fill=C_TEXT, font=(FONT, 10, "bold"), tags="drag")
        if not self.last_update:
            ago, ago_col = "loading", C_MUTED
        elif err:
            ago, ago_col = "%s · updated %s ago" % (err, fmt_ago(self.last_update)), C_WARN
        else:
            ago, ago_col = "updated %s ago" % fmt_ago(self.last_update), C_MUTED
        c.create_text(self.PAD + 132, 19, text=ago, anchor="w",
                      fill=ago_col, font=(FONT, 8), tags="drag")

        # window buttons (add + collapse + pin + close)
        c.create_text(W - 88, 18, text="＋", anchor="center",
                      fill=C_BTN, font=(FONT, 12), tags="btn_add")
        c.create_text(W - 66, 18, text="－", anchor="center",
                      fill=C_BTN, font=(FONT, 12), tags="btn_collapse")
        pin_col = C_OK if self.topmost else C_BTN
        c.create_text(W - 44, 18, text="◉", anchor="center",
                      fill=pin_col, font=(FONT, 12), tags="btn_pin")
        c.create_text(W - 22, 18, text="✕", anchor="center",
                      fill=C_BTN, font=(FONT, 11), tags="btn_close")

        # account columns
        n = len(self.state)
        inner_w = W - 2 * self.PAD
        col_w = (inner_w - (n - 1) * self.COL_GAP) / n
        top = self.HEADER_H + 8
        for i, acc in enumerate(self.state):
            x0 = self.PAD + i * (col_w + self.COL_GAP)
            if i > 0:
                dx = x0 - self.COL_GAP / 2
                c.create_line(dx, top - 2, dx, H - 44, fill=C_DIVIDER, tags="drag")
            self._draw_account(i, x0, top, col_w, acc)

        self._draw_projects()

    def _fit(self, text, max_px, font):
        if font.measure(text) <= max_px:
            return text
        ell = "…"
        while text and font.measure(text + ell) > max_px:
            text = text[:-1]
        return (text + ell) if text else ell

    def _draw_account(self, i, x, y, w, acc):
        c = self.c
        email = acc.get("email") or "—"
        label = acc.get("label", "")
        col = self.label_color.get(label, C_MUTED)
        # a faint × at the very top-right removes this account (never the last one)
        del_w = 0
        if len(self.accounts_cfg) > 1:
            del_col = C_CRIT if self._hover_del == i else C_BTN
            c.create_text(x + w, y - 1, text="✕", anchor="ne",
                          fill=del_col, font=(FONT, 9), tags=("del_%d" % i,))
            del_w = 16
        # account command label (claude1 / claude2), hoverable auth hint
        c.create_text(x + w - del_w, y, text=label, anchor="ne",
                      fill=col, font=self.f_label, tags=("hint_%d" % i,))
        email_px = w - self.f_label.measure(label) - del_w - 12
        c.create_text(x, y, text=self._fit(email, email_px, self.f_email),
                      anchor="nw", fill=C_EMAIL, font=self.f_email,
                      tags=("drag", "hint_%d" % i))

        if not acc.get("loaded"):
            if acc.get("error"):
                c.create_text(x, y + 30, text="⚠ " + acc["error"], anchor="nw",
                              fill=C_CRIT, font=(FONT, 9), tags="drag")
            else:
                c.create_text(x, y + 34, text="loading…", anchor="nw",
                              fill=C_MUTED, font=(FONT, 9), tags="drag")
            return

        # data is present (possibly stale on a transient error) -> show bars
        self._metric(x, y + 28, w, "SESSION", acc.get("five"))
        self._metric(x, y + 82, w, "WEEKLY", acc.get("seven"))

    def _metric(self, x, y, w, label, data):
        c = self.c
        util = (data or {}).get("util", 0.0)
        reset = (data or {}).get("reset")
        pct = max(0.0, min(100.0, util))
        col = color_for(pct)

        c.create_text(x, y, text=label, anchor="nw",
                      fill=C_LABEL, font=(FONT, 8, "bold"), tags="drag")
        c.create_text(x + w, y - 1, text="%d%%" % round(pct), anchor="ne",
                      fill=col, font=(FONT, 10, "bold"), tags="drag")

        by = y + 22          # bar pushed down -> percentage sits higher above it
        bh = 8
        self.round_rect(x, by, x + w, by + bh, bh / 2, fill=C_TRACK,
                        outline="", tags="drag")
        if pct > 0:
            fw = max(bh, w * pct / 100.0)
            self.round_rect(x, by, x + fw, by + bh, bh / 2, fill=col,
                            outline="", tags="drag")

        # the closer the reset, the louder the time reads: yellow under an
        # hour, red in the final 15 minutes — a nudge to get something done.
        delta_col = C_MUTED
        if reset:
            left = int(reset - time.time())
            if left <= 900:
                delta_col = C_CRIT
            elif left < 3600:
                delta_col = C_WARN
        ty = by + bh + 4
        c.create_text(x, ty, text="resets in ", anchor="nw",
                      fill=C_MUTED, font=self.f_small, tags="drag")
        c.create_text(x + self.f_small.measure("resets in "), ty,
                      text=fmt_delta(reset), anchor="nw",
                      fill=delta_col, font=self.f_small, tags="drag")

    def _draw_projects(self):
        c = self.c
        W, H = self.W, self.H
        items = self.recent
        bh = 22
        by = H - 32
        sep_y = by - 9
        c.create_line(self.PAD, sep_y, W - self.PAD, sep_y, fill=C_DIVIDER, tags="drag")

        n = MAX_RECENT
        gap = 8
        inner_w = W - 2 * self.PAD
        bw = (inner_w - (n - 1) * gap) / n
        self._proj_meta = {}
        for j in range(n):
            x = self.PAD + j * (bw + gap)
            tag = "proj_%d" % j
            if j < len(items):
                it = items[j]
                self._proj_meta[j] = it
                bg = C_BTNBG_HOVER if self._hover_proj == j else C_BTNBG
                self.round_rect(x, by, x + bw, by + bh, 6, fill=bg,
                                outline="", tags=tag)
                acc_col = self.label_color.get(it["label"], C_MUTED)
                cy = by + bh / 2
                c.create_oval(x + 9, cy - 3, x + 15, cy + 3,
                              fill=acc_col, outline="", tags=tag)
                c.create_text(x + 21, cy, anchor="w",
                              text=self._fit(it["name"], bw - 28, self.f_proj),
                              fill=C_TEXT, font=self.f_proj, tags=tag)
            else:
                self.round_rect(x, by, x + bw, by + bh, 6, fill=C_PANEL,
                                outline=C_DIVIDER, tags="drag")

    # -- collapsed (mini) view ----------------------------------------------
    def _render_collapsed(self):
        """A compact panel: one session-usage ring per account.

        Each ring's arc is filled to the account's 5-hour utilization and
        coloured by the same OK/WARN/CRIT thresholds as the full bars; the
        account accent (its identity colour) labels it underneath.
        """
        c = self.c
        c.delete("all")
        W, H = self.W, self.H

        self.round_rect(1, 1, W - 1, H - 1, 14, fill=C_PANEL,
                        outline=C_BORDER, width=1, tags="drag")

        # overall status dot — same meaning as the full header's
        err = self._first_error()
        has_data = any(a.get("loaded") for a in self.state)
        if not self.last_update:
            dot = C_MUTED
        elif err and has_data:
            dot = C_WARN
        elif err:
            dot = C_CRIT
        else:
            dot = C_OK
        c.create_oval(12, 10, 19, 17, fill=dot, outline="", tags="drag")

        # restore + close (□ renders low for its box, so nudge it up to sit
        # level with the ✕)
        c.create_text(W - 34, 11, text="□", anchor="center",
                      fill=C_BTN, font=(FONT, 11), tags="btn_collapse")
        c.create_text(W - 16, 13, text="✕", anchor="center",
                      fill=C_BTN, font=(FONT, 11), tags="btn_close")

        n = len(self.state)
        ring = self.COLLAPSE_RING
        total = n * ring + (n - 1) * self.COLLAPSE_GAP
        x_left = (W - total) / 2
        cy = self.COLLAPSE_TOP + ring / 2
        for i, acc in enumerate(self.state):
            cx = x_left + i * (ring + self.COLLAPSE_GAP) + ring / 2
            self._draw_ring(i, cx, cy, acc)

    def _draw_ring(self, i, cx, cy, acc):
        c = self.c
        tag = "ring_%d" % i
        label = acc.get("label", "")
        accent = self.label_color.get(label, C_MUTED)
        th = self.RING_TH
        r = self.COLLAPSE_RING / 2 - th / 2
        x0, y0, x1, y1 = cx - r, cy - r, cx + r, cy + r

        # full track, then the utilization arc clockwise from 12 o'clock
        c.create_oval(x0, y0, x1, y1, outline=C_TRACK, width=th, tags=tag)
        data = acc.get("five") or {}
        pct = max(0.0, min(100.0, data.get("util", 0.0)))
        col = color_for(pct)
        if acc.get("loaded"):
            if pct > 0:
                extent = max(-359.999, -3.6 * pct)
                c.create_arc(x0, y0, x1, y1, start=90, extent=extent,
                             style="arc", outline=col, width=th, tags=tag)
            c.create_text(cx, cy - 1, text="%d%%" % round(pct), anchor="center",
                          fill=col, font=(FONT, 10, "bold"), tags=tag)
        elif acc.get("error"):
            c.create_text(cx, cy - 1, text="!", anchor="center",
                          fill=C_CRIT, font=(FONT, 13, "bold"), tags=tag)
        else:
            c.create_text(cx, cy - 1, text="…", anchor="center",
                          fill=C_MUTED, font=(FONT, 12, "bold"), tags=tag)

        # account identity below the ring
        c.create_text(cx, cy + r + th / 2 + 8,
                      text=self._fit(label, self.COLLAPSE_RING + self.COLLAPSE_GAP,
                                     self.f_small),
                      anchor="center", fill=accent, font=self.f_small, tags=tag)

    def _ring_tip(self, i):
        acc = self.state[i]
        head = acc.get("email") or self.accounts_cfg[i].get("label", "")
        if not acc.get("loaded"):
            return "%s\n%s" % (head, acc.get("error") or "loading…")
        five = acc.get("five") or {}
        seven = acc.get("seven") or {}
        tail = "\n⚠ %s (stale)" % acc["error"] if acc.get("error") else ""
        return ("%s\nSession  %d%%   ·   resets in %s\n"
                "Weekly  %d%%   ·   resets in %s%s"
                % (head,
                   round(five.get("util", 0.0)), fmt_delta(five.get("reset")),
                   round(seven.get("util", 0.0)), fmt_delta(seven.get("reset")),
                   tail))

    def _ring_enter(self, i):
        self.c.config(cursor="hand2")
        self.tip.show(self._ring_tip(i))

    def _ring_leave(self):
        self.c.config(cursor="")
        self.tip.hide()

    def _any_error(self):
        return any(a.get("error") for a in self.state)

    def _first_error(self):
        for a in self.state:
            if a.get("error"):
                return a["error"]
        return None

    # -- interaction --------------------------------------------------------
    def _drag_start(self, e):
        # Press landed on the background -> begin a drag. Buttons have their own
        # tag bindings and never set this flag, so they don't move the window.
        self._dragging = True
        self._dx, self._dy = e.x, e.y

    def _drag_move(self, e):
        # Widget-level binding fires for every B1 motion; only act on a real drag
        # started from the background. e.x/e.y are relative to the canvas, which
        # moves with the window, so the press offset (_dx/_dy) stays valid.
        if not self._dragging:
            return
        nx = self.root.winfo_x() + (e.x - self._dx)
        ny = self.root.winfo_y() + (e.y - self._dy)
        self.root.geometry("+%d+%d" % (nx, ny))

    def _drag_end(self, e):
        self._dragging = False

    def toggle_pin(self):
        self.topmost = not self.topmost
        self.root.attributes("-topmost", self.topmost)

    def toggle_collapse(self):
        # Anchor on the top-right edge so a right-docked widget keeps its corner
        # put while it shrinks/grows toward the screen interior.
        old_right = self.root.winfo_x() + self.W
        old_top = self.root.winfo_y()
        self.collapsed = not self.collapsed
        self.tip.hide()
        self._close_menu()
        if self.collapsed:
            self.W, self.H = self._collapsed_dims()
        else:
            self.W, self.H = self._calc_width(), self.H_FULL
        new_x = max(0, old_right - self.W)
        self.c.config(width=self.W, height=self.H)
        self.root.geometry("%dx%d+%d+%d" % (self.W, self.H, new_x, old_top))
        self.render()
        self._save_pos()

    def _open_proj(self, j):
        it = self._proj_meta.get(j)
        if it:
            open_project(it["path"], it["label"])

    def _proj_menu(self, e, j):
        """Right-click: a widget-styled popup to pick which account opens it."""
        it = self._proj_meta.get(j)
        if not it:
            return
        # with a single account left-click already does the only thing possible
        if len(self.accounts_cfg) <= 1:
            return
        self.tip.hide()
        self._close_menu()

        # 1px C_BORDER frame around a C_PANEL body — same palette as the widget
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=C_BORDER)
        self._menu_win = win
        body = tk.Frame(win, bg=C_PANEL)
        body.pack(padx=1, pady=1)

        tk.Label(body, text=it["name"], bg=C_PANEL, fg=C_MUTED,
                 font=(FONT, 8, "bold"), anchor="w", padx=12, pady=6).pack(fill="x")
        tk.Frame(body, bg=C_DIVIDER, height=1).pack(fill="x")

        for a in self.accounts_cfg:
            self._menu_row(body, a.get("label", ""), it["path"])

        win.update_idletasks()
        ww, wh = win.winfo_width(), win.winfo_height()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        px = min(e.x_root, sw - ww - 4)
        py = min(e.y_root, sh - wh - 4)
        win.geometry("+%d+%d" % (px, py))

        win.bind("<Button-1>", self._menu_click_outside)
        win.bind("<Escape>", lambda e: self._close_menu())
        try:
            win.grab_set_global()
        except tk.TclError:
            win.grab_set()
        win.focus_set()

    def _menu_row(self, parent, label, path):
        col = self.label_color.get(label, C_MUTED)
        row = tk.Frame(parent, bg=C_PANEL)
        row.pack(fill="x")
        dot = tk.Canvas(row, width=12, height=12, bg=C_PANEL,
                        highlightthickness=0, bd=0)
        dot.create_oval(3, 3, 11, 11, fill=col, outline="")
        dot.pack(side="left", padx=(12, 0))
        lbl = tk.Label(row, text=label, bg=C_PANEL, fg=C_TEXT,
                       font=(FONT, 9), anchor="w", padx=8, pady=7)
        lbl.pack(side="left", fill="x", expand=True)

        cells = (row, dot, lbl)

        def on_enter(_):
            for w in cells:
                w.configure(bg=C_BTNBG_HOVER)
            self._menu_win.configure(cursor="hand2")

        def on_leave(_):
            for w in cells:
                w.configure(bg=C_PANEL)
            self._menu_win.configure(cursor="")

        def on_click(_):
            self._close_menu()
            open_project(path, label)
            return "break"

        for w in cells:
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
            w.bind("<Button-1>", on_click)

    def _menu_click_outside(self, e):
        win = self._menu_win
        if win is None:
            return
        x, y = e.x_root, e.y_root
        wx, wy = win.winfo_rootx(), win.winfo_rooty()
        if not (wx <= x <= wx + win.winfo_width()
                and wy <= y <= wy + win.winfo_height()):
            self._close_menu()

    def _close_menu(self):
        win = self._menu_win
        if win is not None:
            try:
                win.grab_release()
            except Exception:
                pass
            try:
                win.destroy()
            except Exception:
                pass
        self._menu_win = None

    def _proj_enter(self, j):
        it = self._proj_meta.get(j)
        if not it:
            return
        self.c.config(cursor="hand2")
        self._hover_proj = j
        # with a single account there is nothing to disambiguate — skip the tip
        if len(self.accounts_cfg) <= 1:
            return
        self.tip.show("%s\n→ open a console and launch  %s\n"
                      "(right-click — choose a different account)"
                      % (it["path"], it["label"]))

    def _proj_leave(self):
        self.c.config(cursor="")
        self._hover_proj = None
        self.tip.hide()

    # -- account management -------------------------------------------------
    def _calc_width(self):
        """Widget width for the current account count.

        A floor keeps the header (title + status + buttons) from colliding
        when only one narrow account column is shown.
        """
        n = max(1, len(self.accounts_cfg))
        return max(250 * n + self.PAD, 320)

    def _collapsed_dims(self):
        """Window size for the mini view (one session ring per account)."""
        n = max(1, len(self.accounts_cfg))
        w = (2 * self.COLLAPSE_PAD + n * self.COLLAPSE_RING
             + (n - 1) * self.COLLAPSE_GAP)
        h = self.COLLAPSE_TOP + self.COLLAPSE_RING + 22
        return int(max(w, 128)), int(h)

    def _apply_geometry(self):
        """Resize the window/canvas to match the current view, keeping position."""
        if self.collapsed:
            self.W, self.H = self._collapsed_dims()
        else:
            self.W, self.H = self._calc_width(), self.H_FULL
        self.c.config(width=self.W, height=self.H)
        self.root.geometry("%dx%d+%d+%d" % (
            self.W, self.H, self.root.winfo_x(), self.root.winfo_y()))

    def _make_popup(self):
        """A 1px-bordered, panel-coloured Toplevel matching the widget palette."""
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=C_BORDER)
        body = tk.Frame(win, bg=C_PANEL)
        body.pack(padx=1, pady=1)
        return win, body

    def _place_popup(self, win, x, y):
        win.update_idletasks()
        ww, wh = win.winfo_width(), win.winfo_height()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry("+%d+%d" % (min(x, sw - ww - 4), min(y, sh - wh - 4)))

    def _styled_button(self, parent, text, fg, command):
        btn = tk.Label(parent, text=text, bg=C_BTNBG, fg=fg,
                       font=(FONT, 9, "bold"), padx=14, pady=6, cursor="hand2")
        btn.bind("<Enter>", lambda e: btn.configure(bg=C_BTNBG_HOVER))
        btn.bind("<Leave>", lambda e: btn.configure(bg=C_BTNBG))
        btn.bind("<Button-1>", lambda e: command())
        return btn

    def _add_account_dialog(self):
        self.tip.hide()
        self._close_menu()
        win, body = self._make_popup()
        self._menu_win = win

        tk.Label(body, text="Add account", bg=C_PANEL, fg=C_TEXT,
                 font=(FONT, 9, "bold"), anchor="w", padx=14
                 ).pack(fill="x", pady=(10, 2))
        tk.Label(body, text="CLI label and config directory",
                 bg=C_PANEL, fg=C_MUTED, font=(FONT, 8), anchor="w",
                 padx=14).pack(fill="x", pady=(0, 8))

        def field(caption, default):
            tk.Label(body, text=caption, bg=C_PANEL, fg=C_LABEL,
                     font=(FONT, 8, "bold"), anchor="w", padx=14).pack(fill="x")
            wrap = tk.Frame(body, bg=C_BORDER)
            wrap.pack(fill="x", padx=14, pady=(2, 8))
            ent = tk.Entry(wrap, bg=C_BTNBG, fg=C_TEXT, insertbackground=C_TEXT,
                           relief="flat", font=(FONT, 9), width=34)
            ent.pack(fill="x", padx=1, pady=1, ipady=4, ipadx=4)
            ent.insert(0, default)
            return ent

        n = len(self.accounts_cfg) + 1
        e_label = field("Label  (the claudeN command)", "claude%d" % n)
        e_dir = field("Config dir", r"%%USERPROFILE%%\.claude-account%d" % n)

        err = tk.Label(body, text="", bg=C_PANEL, fg=C_CRIT,
                       font=(FONT, 8), anchor="w", padx=14)
        err.pack(fill="x")

        def submit():
            label = e_label.get().strip()
            cdir = e_dir.get().strip()
            if not label or not cdir:
                err.configure(text="Both fields are required.")
                return
            if any(a.get("label") == label for a in self.accounts_cfg):
                err.configure(text="That label already exists.")
                return
            self.config.setdefault("accounts", []).append(
                {"label": label, "config_dir": cdir})
            self._persist_config()
            self._close_menu()
            self._rebuild_accounts()

        row = tk.Frame(body, bg=C_PANEL)
        row.pack(fill="x", padx=14, pady=(4, 12))
        self._styled_button(row, "Cancel", C_MUTED,
                            self._close_menu).pack(side="right")
        self._styled_button(row, "Add", C_OK,
                            submit).pack(side="right", padx=(0, 8))

        e_label.focus_set()
        win.bind("<Return>", lambda e: submit())
        win.bind("<Escape>", lambda e: self._close_menu())
        rx, ry = self.root.winfo_x(), self.root.winfo_y()
        self._place_popup(win, rx + self.W - 240, ry + self.HEADER_H)
        try:
            win.grab_set_global()
        except tk.TclError:
            win.grab_set()

    def _delete_account(self, i):
        if len(self.accounts_cfg) <= 1 or i >= len(self.accounts_cfg):
            return
        self.tip.hide()
        self._close_menu()
        acc = self.accounts_cfg[i]
        label = acc.get("label", "")
        win, body = self._make_popup()
        self._menu_win = win

        tk.Label(body, text="Remove account", bg=C_PANEL, fg=C_TEXT,
                 font=(FONT, 9, "bold"), anchor="w", padx=14
                 ).pack(fill="x", pady=(10, 2))
        tk.Label(body, text="%s  will be removed from the widget.\n"
                            "Your Claude login is not touched." % label,
                 bg=C_PANEL, fg=C_MUTED, font=(FONT, 8), anchor="w",
                 justify="left", padx=14).pack(fill="x", pady=(0, 10))

        def confirm():
            del self.config["accounts"][i]
            self._persist_config()
            self._close_menu()
            self._rebuild_accounts()

        row = tk.Frame(body, bg=C_PANEL)
        row.pack(fill="x", padx=14, pady=(0, 12))
        self._styled_button(row, "Cancel", C_MUTED,
                            self._close_menu).pack(side="right")
        self._styled_button(row, "Remove", C_CRIT,
                            confirm).pack(side="right", padx=(0, 8))

        win.bind("<Escape>", lambda e: self._close_menu())
        self._place_popup(win, self.root.winfo_pointerx() - 60,
                          self.root.winfo_pointery() + 10)
        try:
            win.grab_set_global()
        except tk.TclError:
            win.grab_set()

    def _persist_config(self):
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2)
        os.replace(tmp, CONFIG_PATH)

    def _rebuild_accounts(self):
        """Apply a changed account set: resize, recolour, rebind, redraw.

        Existing usage state is preserved per label so surviving accounts don't
        flash back to 'loading' after an add/remove.
        """
        prev_by_label = {s.get("label"): s for s in self.state}
        self.accounts_cfg = self.config.get("accounts", [])
        self.label_color = {
            a.get("label", ""): ACCOUNT_ACCENTS[i % len(ACCOUNT_ACCENTS)]
            for i, a in enumerate(self.accounts_cfg)}
        self.state = [
            prev_by_label.get(a.get("label"),
                              {"label": a.get("label", ""), "email": None,
                               "five": None, "seven": None,
                               "error": None, "loaded": False})
            for a in self.accounts_cfg]
        self._hover_del = None
        self._apply_geometry()
        try:
            self.recent = recent_projects(self.accounts_cfg)
        except Exception:
            pass
        self._bind_account_tags()
        self.render()

    def close(self):
        self._stop.set()
        self._save_pos()
        self.root.destroy()

    # -- background polling -------------------------------------------------
    def _poll_loop(self):
        # per-account backoff: a rate-limited account cools down on its own
        # without stalling the healthy one.
        fails = []
        next_at = []
        while not self._stop.is_set():
            # snapshot — the account set can change while we poll (add/remove)
            accounts = self.accounts_cfg
            n = len(accounts)
            if len(fails) != n:
                fails = [0] * n
                next_at = [0.0] * n
            now = time.time()
            polled = False
            for i, acc in enumerate(accounts):
                if self._stop.is_set():
                    return
                if now < next_at[i]:
                    continue
                polled = True
                st = self.state
                res = fetch_account(acc, st[i] if i < len(st) else None)
                st = self.state
                if i < len(st):
                    st[i] = res
                if res.get("error"):
                    fails[i] = min(fails[i] + 1, 5)
                    next_at[i] = now + min(60 * (2 ** fails[i]), 600)
                else:
                    fails[i] = 0
                    next_at[i] = now + self.poll
            if polled:
                try:
                    self.recent = recent_projects(self.accounts_cfg)
                except Exception:
                    pass
                self.last_update = time.time()
                # Expose the fresh numbers to other local tools (E-Likarnya, …).
                try:
                    write_usage_state(self.accounts_cfg, self.state)
                except Exception:
                    pass
            # tick often enough to honour per-account timers
            self._stop.wait(min(15, self.poll))

    def _tick(self):
        if self._stop.is_set():
            return
        self.render()
        self.root.after(1000, self._tick)


def fmt_ago(ts):
    s = int(time.time() - ts)
    if s < 60:
        return "%ds" % s
    if s < 3600:
        return "%dm" % (s // 60)
    return "%dh" % (s // 3600)


def main():
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    config = load_config()
    root = tk.Tk()
    root.title("Claude Usage")
    UsageWidget(root, config)
    root.mainloop()


if __name__ == "__main__":
    main()
