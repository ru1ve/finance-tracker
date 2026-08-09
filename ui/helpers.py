"""
ui/helpers.py — Shared widget factory functions and formatting helpers.
"""
from __future__ import annotations

import datetime
import tkinter as tk
from tkinter import ttk

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import db
from ui.constants import BG, BG2, BG3, FG, ACCENT, SUBTEXT, STYLE

_DATE_FORMATS = {
    "YYYY-MM-DD":  "%Y-%m-%d",
    "DD/MM/YYYY":  "%d/%m/%Y",
    "DD Mon YYYY": "%d %b %Y",
    "MM/DD/YYYY":  "%m/%d/%Y",
}


def fmt_gbp(v):
    if v is None:
        return "—"
    neg = v < 0
    s = f"£{abs(v):,.2f}"
    return f"-{s}" if neg else s


def fmt_pct(v):
    if v is None:
        return "—"
    return f"{v*100:.2f}%"


def format_date(date_str):
    """Display a stored date string using the user-configured date format."""
    if not date_str or date_str == "—":
        return date_str
    fmt_key = db.get_setting("date_format", "YYYY-MM-DD")
    out_fmt  = _DATE_FORMATS.get(fmt_key, "%Y-%m-%d")
    for parse_fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(str(date_str), parse_fmt).strftime(out_fmt)
        except ValueError:
            pass
    return date_str


def styled_frame(parent, **kw):
    return tk.Frame(parent, bg=BG, **kw)


def styled_label(parent, text, font=None, fg=None, **kw):
    return tk.Label(parent, text=text, bg=BG, fg=fg or FG,
                    font=font or STYLE["font"], **kw)


def styled_entry(parent, width=20, **kw):
    return tk.Entry(parent, bg=BG3, fg=FG, insertbackground=FG,
                    relief="flat", font=STYLE["font_mono"], width=width, **kw)


def styled_button(parent, text, command, color=ACCENT, **kw):
    return tk.Button(parent, text=text, command=command,
                     bg=BG3, fg=color, activebackground=BG2, activeforeground=color,
                     relief="flat", font=STYLE["font_bold"],
                     cursor="hand2", padx=10, pady=4, **kw)


def section_label(parent, text):
    return tk.Label(parent, text=text, bg=BG, fg=ACCENT,
                    font=STYLE["font_h2"], anchor="w")


def add_tooltip(widget, text: str):
    """Attach a simple hover tooltip to a widget."""
    tip = None

    def _show(event):
        nonlocal tip
        tip = tk.Toplevel(widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{event.x_root + 12}+{event.y_root + 4}")
        tk.Label(tip, text=text, bg=BG3, fg=FG, font=STYLE["font"],
                 relief="solid", bd=1, padx=6, pady=3).pack()

    def _hide(_event):
        nonlocal tip
        if tip:
            tip.destroy()
            tip = None

    widget.bind("<Enter>", _show)
    widget.bind("<Leave>", _hide)


def make_tree(parent, columns, show="headings", height=14):
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("TCombobox",
                    fieldbackground=BG3, background=BG3, foreground=FG,
                    selectbackground=BG3, selectforeground=ACCENT,
                    arrowcolor=ACCENT)
    style.map("TCombobox", fieldbackground=[("readonly", BG3)])
    style.configure("Finance.Treeview",
                    background=BG2, foreground=FG, fieldbackground=BG2,
                    rowheight=24, font=STYLE["font"])
    style.configure("Finance.Treeview.Heading",
                    background=BG3, foreground=ACCENT,
                    font=STYLE["font_bold"], relief="flat")
    style.map("Finance.Treeview", background=[("selected", BG3)],
              foreground=[("selected", ACCENT)])

    tree = ttk.Treeview(parent, columns=columns, show=show,
                        style="Finance.Treeview", height=height)
    sb = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    return tree, sb


def embed_figure(parent, fig):
    canvas = FigureCanvasTkAgg(fig, master=parent)
    canvas.draw()
    return canvas.get_tk_widget()
