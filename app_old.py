"""
app_old.py — Personal Finance Tracker
Tkinter + Matplotlib UI over SQLite backend.

Tabs:
  1. Dashboard      — balances, totals, account management (add/edit/deactivate)
  2. Snapshot       — log a new balance snapshot for all accounts
  3. History        — charts of account / category history over time
  4. Categories     — spending allocation breakdown over time
  5. Interest       — current interest summary + forward projection
  6. Mortgage       — affordability estimator
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import datetime
import sys
from pathlib import Path

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.dates as mdates

import db

# ---------------------------------------------------------------------------
# Colour palette — dark enough to be bearable
# ---------------------------------------------------------------------------
BG       = "#1e1e2e"
BG2      = "#2a2a3e"
BG3      = "#313149"
FG       = "#cdd6f4"
ACCENT   = "#89b4fa"
GREEN    = "#a6e3a1"
RED      = "#f38ba8"
YELLOW   = "#f9e2af"
MAUVE    = "#cba6f7"
TEAL     = "#94e2d5"
PINK     = "#f5c2e7"
SUBTEXT  = "#6c7086"

CAT_COLOURS = {
    "Spending":          RED,
    "Deposit":           ACCENT,
    "Emergency Fund":    YELLOW,
    "Long Term Savings": GREEN,
    "Pension":           MAUVE,
}

STYLE = {
    "bg": BG, "fg": FG,
    "font": ("Segoe UI", 10),
    "font_bold": ("Segoe UI", 10, "bold"),
    "font_h1": ("Segoe UI", 16, "bold"),
    "font_h2": ("Segoe UI", 12, "bold"),
    "font_mono": ("Consolas", 10),
}

def fmt_gbp(v):
    if v is None: return "—"
    neg = v < 0
    s = f"£{abs(v):,.2f}"
    return f"-{s}" if neg else s

def fmt_pct(v):
    if v is None: return "—"
    return f"{v*100:.2f}%"

_DATE_FORMATS = {
    "YYYY-MM-DD":  "%Y-%m-%d",
    "DD/MM/YYYY":  "%d/%m/%Y",
    "DD Mon YYYY": "%d %b %Y",
    "MM/DD/YYYY":  "%m/%d/%Y",
}

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


# ---------------------------------------------------------------------------
# Base helpers
# ---------------------------------------------------------------------------

def styled_frame(parent, **kw):
    f = tk.Frame(parent, bg=BG, **kw)
    return f

def styled_label(parent, text, font=None, fg=None, **kw):
    return tk.Label(parent, text=text, bg=BG, fg=fg or FG,
                    font=font or STYLE["font"], **kw)

def styled_entry(parent, width=20, **kw):
    e = tk.Entry(parent, bg=BG3, fg=FG, insertbackground=FG,
                 relief="flat", font=STYLE["font_mono"], width=width, **kw)
    return e

def styled_button(parent, text, command, color=ACCENT, **kw):
    return tk.Button(parent, text=text, command=command,
                     bg=BG3, fg=color, activebackground=BG2, activeforeground=color,
                     relief="flat", font=STYLE["font_bold"],
                     cursor="hand2", padx=10, pady=4, **kw)

def section_label(parent, text):
    return tk.Label(parent, text=text, bg=BG, fg=ACCENT,
                    font=STYLE["font_h2"], anchor="w")


def add_tooltip(widget, text):
    """Show a small popup label when the mouse hovers over widget."""
    tip = None

    def _show(event):
        nonlocal tip
        if tip:
            return
        tip = tk.Toplevel(widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{event.x_root + 12}+{event.y_root + 6}")
        tk.Label(tip, text=text, bg="#2a2a1a", fg="#e8e3c0",
                 font=("Segoe UI", 9), relief="solid", bd=1,
                 padx=6, pady=3, wraplength=260).pack()

    def _hide(_event=None):
        nonlocal tip
        if tip:
            tip.destroy()
            tip = None

    widget.bind("<Enter>", _show)
    widget.bind("<Leave>", _hide)
    widget.bind("<ButtonPress>", _hide)

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


# ---------------------------------------------------------------------------
# Tab 1 — Dashboard
# ---------------------------------------------------------------------------

class DashboardTab(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._selected_id     = None
        self._selected_active = True
        self._build()

    def _build(self):
        # Header — Refresh only; add/deactivate live in the edit bar
        hdr = styled_frame(self)
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        styled_label(hdr, "Dashboard", font=STYLE["font_h1"]).pack(side="left")
        styled_button(hdr, "⟳ Refresh", self.refresh, color=GREEN).pack(side="right", padx=8)

        # Summary cards (main row)
        self.cards_frame = styled_frame(self)
        self.cards_frame.pack(fill="x", padx=20, pady=(4, 2))

        # Category allocation cards (second row)
        self.cat_cards_frame = styled_frame(self)
        self.cat_cards_frame.pack(fill="x", padx=20, pady=(0, 4))

        # ---- Edit / Create bar (two rows so nothing can be hidden) ----
        section_label(self, "  Account Editor  —  select a row to edit, or fill in fields to create").pack(
            fill="x", padx=20, pady=(2, 0))

        edit_bar = tk.Frame(self, bg=BG2)
        edit_bar.pack(fill="x", padx=20, pady=(0, 6))

        # Row 1 — input fields
        fields_row = tk.Frame(edit_bar, bg=BG2)
        fields_row.pack(fill="x", padx=8, pady=(4, 2))

        def _lbl(parent, text):
            return tk.Label(parent, text=text, bg=BG2, fg=SUBTEXT, font=STYLE["font"])

        def _ent(parent, var, w):
            return tk.Entry(parent, textvariable=var, bg=BG3, fg=FG,
                            insertbackground=FG, relief="flat",
                            font=STYLE["font"], width=w)

        _lbl(fields_row, "Bank:").pack(side="left", padx=(0, 3))
        self._bank_var = tk.StringVar()
        _ent(fields_row, self._bank_var, 12).pack(side="left", padx=(0, 10))

        _lbl(fields_row, "Label:").pack(side="left", padx=(0, 3))
        self._actype_var = tk.StringVar()
        _ent(fields_row, self._actype_var, 12).pack(side="left", padx=(0, 10))

        _lbl(fields_row, "Type:").pack(side="left", padx=(0, 3))
        self._pt_var = tk.StringVar()
        self._pt_combo = ttk.Combobox(fields_row, textvariable=self._pt_var, width=14,
                                      font=STYLE["font"], state="normal")
        self._pt_combo["values"] = db.get_product_types()
        self._pt_combo.pack(side="left", padx=(0, 10))

        _lbl(fields_row, "Category:").pack(side="left", padx=(0, 3))
        self._cat_var = tk.StringVar()
        self._cat_combo = ttk.Combobox(fields_row, textvariable=self._cat_var, width=12,
                                       font=STYLE["font"], state="normal")
        self._cat_combo["values"] = db.get_account_categories()
        self._cat_combo.pack(side="left", padx=(0, 10))

        _max_lbl = _lbl(fields_row, "Int. Cap £:")
        _max_lbl.pack(side="left", padx=(0, 3))
        add_tooltip(_max_lbl, "Maximum balance on which interest is paid.\n"
                              "Leave blank if interest applies to the full balance.")
        self._maxbal_var = tk.StringVar()
        _ent(fields_row, self._maxbal_var, 10).pack(side="left", padx=(0, 4))

        # Row 2 — action buttons (always fully visible on their own row)
        action_row = tk.Frame(edit_bar, bg=BG2)
        action_row.pack(fill="x", padx=8, pady=(0, 4))

        # Status / name-preview label
        self._sel_label = tk.Label(action_row, text="New account",
                                   bg=BG2, fg=SUBTEXT, font=STYLE["font"],
                                   anchor="w")
        self._sel_label.pack(side="left", padx=(0, 10))

        tk.Frame(action_row, bg=BG3, width=1).pack(side="left", fill="y", pady=2)

        # Save / Create button (text changes with mode)
        self._save_btn = styled_button(action_row, "Create Account", self._save_edits, color=GREEN)
        self._save_btn.pack(side="left", padx=(8, 0))

        # Deactivate/Reactivate — hidden until an account is selected
        self._toggle_btn = styled_button(action_row, "⊗ Deactivate", self._deactivate, color=RED)
        # not packed yet — shown in _on_select

        # Unselect button — hidden until an account is selected
        self._unselect_btn = tk.Button(
            action_row, text="← Unselect", bg=BG3, fg=SUBTEXT,
            relief="flat", font=STYLE["font"], padx=8, pady=3,
            cursor="hand2", activebackground=BG2, activeforeground=FG,
            command=self._clear_selection)
        # not packed yet — shown in _on_select

        tk.Label(action_row, text="Rates & allocations → Log Snapshot",
                 bg=BG2, fg=SUBTEXT, font=STYLE["font"]).pack(side="right", padx=(0, 4))

        # Live name preview while typing in create mode
        for var in (self._bank_var, self._actype_var):
            var.trace_add("write", lambda *_: self._update_create_preview())

        # Tree
        section_label(self, "  Current Balances").pack(fill="x", padx=20, pady=(4, 2))
        self._tree_frame = styled_frame(self)
        self._tree_frame.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        self._build_tree()

    def _build_tree(self):
        for w in self._tree_frame.winfo_children():
            w.destroy()

        tree_frame = self._tree_frame
        self._spend_cats = db.get_spending_category_names()
        _cat_short = {"Spending": "Spending", "Deposit": "Deposit",
                      "Emergency Fund": "Emerg. Fund", "Long Term Savings": "LT Savings",
                      "Pension": "Pension"}
        cat_cols = [c.lower().replace(" ", "_") for c in self._spend_cats]
        cols = ("name", "bank", "product_type", "rate", "max_for_rate",
                "balance", "yearly_int", "last_recorded") + tuple(cat_cols)
        self.tree, sb = make_tree(tree_frame, cols, height=22)
        fixed_defs = [
            ("name",          "Account Name",  175, "w"),
            ("bank",          "Bank",           90, "w"),
            ("product_type",  "Type",           110, "w"),
            ("rate",          "Rate %",          68, "e"),
            ("max_for_rate",  "Rate Max £",      95, "e"),
            ("balance",       "Balance",         100, "e"),
            ("yearly_int",    "Yr. Interest",    95, "e"),
            ("last_recorded", "Last Recorded",   100, "e"),
        ]
        for col, hdr_text, w, anch in fixed_defs + [
            (c, _cat_short.get(n, n), 78, "e")
            for c, n in zip(cat_cols, self._spend_cats)
        ]:
            self.tree.heading(col, text=hdr_text)
            self.tree.column(col, width=w, anchor=anch)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.tag_configure("inactive", foreground=SUBTEXT)

        self.refresh()

    def rebuild(self):
        """Rebuild tree columns (called when spending categories change)."""
        self._clear_selection()
        self._build_tree()

    def _make_card(self, parent, label, value, colour, subtitle=None, subtitle_colour=None):
        f = tk.Frame(parent, bg=BG3, padx=16, pady=10)
        # Invisible spacer enforces a minimum card width
        tk.Frame(f, bg=BG3, width=170, height=1).pack()
        tk.Label(f, text=label, bg=BG3, fg=SUBTEXT, font=STYLE["font"],
                 anchor="w").pack(fill="x")
        tk.Label(f, text=value, bg=BG3, fg=colour,
                 font=("Segoe UI", 16, "bold"), anchor="w").pack(fill="x")
        # Always render the subtitle row so all cards share the same height
        sub_text   = subtitle or ""
        sub_colour = subtitle_colour if subtitle else BG3  # invisible when empty
        tk.Label(f, text=sub_text, bg=BG3, fg=sub_colour,
                 font=STYLE["font"], anchor="w").pack(fill="x", pady=(2, 0))
        return f


    def _mom_sub(self, history, current_val):
        """Return (subtitle_text, subtitle_colour) for a card, or (None, None)."""
        pct, gbp = self._mom_change_from(history, current_val)
        if pct is None:
            return None, None
        arrow  = "↑" if gbp >= 0 else "↓"
        sign   = "+" if gbp >= 0 else ""
        colour = GREEN if gbp >= 0 else RED
        return f"{arrow} {abs(pct):.2f}%  {sign}{fmt_gbp(gbp)}  vs 1 mo", colour

    def _mom_change_from(self, history, current_val: float):
        """_mom_change() generalised to accept any pre-fetched history list."""
        if not history:
            return None, None
        today     = datetime.date.today()
        target    = today - datetime.timedelta(days=30)
        today_str = today.isoformat()

        def _d(s): return datetime.date.fromisoformat(s[:10])

        series = list(history)
        if not series or series[-1][0][:10] < today_str:
            series.append((today_str, current_val))

        if _d(series[0][0]) > target:
            if len(series) < 2:
                return None, None
            d0, v0 = series[0]
            d1, v1 = series[1]
            span = (_d(d1) - _d(d0)).days
            if span == 0:
                return None, None
            slope = (v1 - v0) / span
            target_val = v0 - slope * (_d(d0) - target).days
        else:
            before = [(d, v) for d, v in series if _d(d) <= target]
            after  = [(d, v) for d, v in series if _d(d) >= target]
            if not before or not after:
                return None, None
            d0, v0 = before[-1]
            d1, v1 = after[0]
            if d0[:10] == d1[:10]:
                target_val = v0
            else:
                span = (_d(d1) - _d(d0)).days
                frac = (target - _d(d0)).days / span
                target_val = v0 + frac * (v1 - v0)

        if target_val == 0:
            return None, None
        delta_gbp = current_val - target_val
        return delta_gbp / abs(target_val) * 100, delta_gbp

    def refresh(self):
        sel = self._selected_id
        for w in self.cards_frame.winfo_children():
            w.destroy()
        for w in self.cat_cards_frame.winfo_children():
            w.destroy()

        summary     = db.get_current_interest_summary()
        date_str, _ = db.get_latest_snapshot()

        total_balance  = sum(r["balance"] for r in summary)
        total_interest = sum(r["yearly_interest"] for r in summary)
        total_debt     = sum(r["balance"] for r in summary if r["balance"] < 0)
        net            = total_balance - abs(total_debt) if total_debt else total_balance

        # Fetch histories for MoM calculations (one DB call each)
        assets_hist = db.get_assets_history()     # positive balances
        debt_hist   = db.get_debt_history()       # negative balances (values are negative)
        nw_hist     = db.get_net_worth_history()  # total (used for Net Worth card)

        # Main summary cards
        card_defs = [
            ("Total Assets",    fmt_gbp(total_balance),    GREEN,  assets_hist,  total_balance),
            ("Total Debt",      fmt_gbp(abs(total_debt)),  RED,    [(d, abs(v)) for d, v in debt_hist], abs(total_debt)),
            ("Net Worth",       fmt_gbp(net),              ACCENT, nw_hist,      net),
            ("Yearly Interest", fmt_gbp(total_interest),   YELLOW, None,         None),
            ("Last Snapshot",   format_date(date_str) if date_str else "None", SUBTEXT, None, None),
        ]
        for label, val, colour, hist, cur in card_defs:
            sub, sub_col = self._mom_sub(hist, cur) if hist is not None else (None, None)
            self._make_card(self.cards_frame, label, val, colour,
                            subtitle=sub, subtitle_colour=sub_col).pack(
                side="left", padx=(0, 10), pady=4)

        # Category allocation cards — use same logic as CategoriesTab via get_category_history()
        cat_history = db.get_category_history()
        if cat_history:
            cur_totals = cat_history[-1]["totals"]
            cat_series: dict = {cat: [] for cat in self._spend_cats}
            for entry in cat_history:
                for cat in self._spend_cats:
                    cat_series[cat].append((entry["date"], entry["totals"].get(cat, 0.0)))
        else:
            cur_totals = {cat: 0.0 for cat in self._spend_cats}
            cat_series = {cat: [] for cat in self._spend_cats}

        _cat_colours = {
            "Spending":          MAUVE,
            "Deposit":           ACCENT,
            "Emergency Fund":    TEAL,
            "Long Term Savings": GREEN,
            "Pension":           YELLOW,
        }
        for cat in self._spend_cats:
            cur_val      = cur_totals.get(cat, 0.0)
            sub, sub_col = self._mom_sub(cat_series[cat], cur_val)
            colour       = _cat_colours.get(cat, FG)
            self._make_card(self.cat_cards_frame, cat, fmt_gbp(cur_val), colour,
                            subtitle=sub, subtitle_colour=sub_col).pack(
                side="left", padx=(0, 10), pady=4)

        # Tree rows
        for row in self.tree.get_children():
            self.tree.delete(row)

        today      = datetime.date.today().isoformat()
        all_accs   = db.get_all_accounts(include_inactive=True)
        snapshot   = db.get_latest_balance_per_account()
        last_dates = db.get_last_recorded_dates()
        rates      = db._get_rates_on_date(today)
        allocs     = db.get_all_allocations_on_date(today)

        yearly_int = {
            acc["id"]: max(0.0, snapshot.get(acc["id"], 0.0)) * rates.get(acc["id"], 0.0)
            for acc in all_accs
        }

        active   = [a for a in all_accs if a["is_active"]]
        inactive = [a for a in all_accs if not a["is_active"]]

        # Bank colour palette — subtle background tints, one per unique bank name
        _BANK_BG = [
            "#1a2030",  # slate blue
            "#1a2a1e",  # forest green
            "#2a221a",  # amber
            "#251a2a",  # purple
            "#1a2828",  # teal
            "#2a1a1e",  # rose
            "#1e1a2a",  # indigo
            "#22261a",  # olive
        ]
        banks = sorted({
            (a.get("bank") or "").strip()
            for a in all_accs
            if (a.get("bank") or "").strip()
        })
        bank_tag_map: dict = {}
        for i, bank in enumerate(banks):
            t = f"_bank_{i}"
            bank_tag_map[bank] = t
            self.tree.tag_configure(t, background=_BANK_BG[i % len(_BANK_BG)])

        def _btag(acc):
            return bank_tag_map.get((acc.get("bank") or "").strip(), "")

        for acc in active:
            self._insert_row(acc, snapshot, rates, last_dates, allocs, yearly_int,
                             tag="active", bank_tag=_btag(acc))

        if inactive:
            n_cols = 8 + len(self._spend_cats)
            self.tree.insert("", "end", iid="__sep__",
                             values=("── Deactivated ──",) + ("",) * (n_cols - 1),
                             tags=("sep",))
            self.tree.tag_configure("sep", foreground=SUBTEXT)
            for acc in inactive:
                self._insert_row(acc, snapshot, rates, last_dates, allocs, yearly_int,
                                 tag="inactive", bank_tag=_btag(acc))

        if sel and self.tree.exists(str(sel)):
            self.tree.selection_set(str(sel))

    def _insert_row(self, acc, snapshot, rates, last_dates, allocs, yearly_int, tag, bank_tag=""):
        acc_id     = acc["id"]
        rate       = rates.get(acc_id, 0.0)
        balance    = snapshot.get(acc_id)
        last_dt    = last_dates.get(acc_id)
        acc_allocs = allocs.get(acc_id, {})
        max_bal    = acc.get("max_balance_for_rate")
        try:
            max_bal = float(max_bal) if max_bal not in (None, "", "None") else None
        except (TypeError, ValueError):
            max_bal = None
        yr_int     = yearly_int.get(acc_id, 0.0)

        def _fmt_alloc(cat):
            v = acc_allocs.get(cat, {"fixed": 0.0, "pct": 0.0})
            if v["fixed"]:
                return f"£{v['fixed']:,.2f}"
            if v["pct"]:
                return f"{v['pct']*100:.2f}%"
            return "—"

        cat_vals = tuple(_fmt_alloc(c) for c in self._spend_cats)
        self.tree.insert("", "end", iid=str(acc_id), values=(
            acc["account_name"],
            acc.get("bank") or "—",
            acc.get("product_type") or "—",
            f"{rate * 100:.2f}%" if rate else "—",
            fmt_gbp(max_bal) if max_bal else "—",
            fmt_gbp(balance) if balance is not None else "—",
            fmt_gbp(yr_int) if yr_int else "—",
            format_date(last_dt) if last_dt else "—",
        ) + cat_vals, tags=(bank_tag, tag) if bank_tag else (tag,))

    def _update_create_preview(self):
        """Show a live name preview in the status label when in create (no selection) mode."""
        if self._selected_id:
            return
        bank  = self._bank_var.get().strip()
        label = self._actype_var.get().strip()
        name  = f"{bank} - {label}" if bank and label else (bank or label)
        if name:
            self._sel_label.config(text=f"→ {name}", fg=ACCENT)
        else:
            self._sel_label.config(text="New account", fg=SUBTEXT)

    def _on_select(self, event):
        sel = self.tree.selection()
        if not sel or sel[0] == "__sep__":
            return
        self._selected_id = int(sel[0])
        acc = db.get_account_by_id(self._selected_id)
        self._selected_active = bool(acc["is_active"])
        acc_name = acc.get("account_name") or ""
        self._sel_label.config(text=f"Editing: {acc_name}", fg=ACCENT)
        self._bank_var.set(acc.get("bank") or "")
        self._actype_var.set(acc.get("account_type") or "")
        self._pt_var.set(acc.get("product_type") or "")
        self._cat_var.set(acc.get("category") or "")
        mb = acc.get("max_balance_for_rate")
        try:
            mb = float(mb) if mb not in (None, "", "None") else None
        except (TypeError, ValueError):
            mb = None
        self._maxbal_var.set(f"{mb:.2f}" if mb is not None else "")
        # Switch to edit mode
        self._save_btn.config(text="Save Changes")
        if self._selected_active:
            self._toggle_btn.config(text="⊗ Deactivate", fg=RED, command=self._deactivate)
        else:
            self._toggle_btn.config(text="↺ Reactivate", fg=GREEN, command=self._reactivate)
        self._toggle_btn.pack(side="left", padx=(8, 0))
        self._unselect_btn.pack(side="left", padx=(6, 0))

    def _save_edits(self):
        bank   = self._bank_var.get().strip()
        label  = self._actype_var.get().strip()
        ptype  = self._pt_var.get().strip()
        cat    = self._cat_var.get().strip()
        mb_raw = self._maxbal_var.get().strip().replace("£", "").replace(",", "")

        if not bank and not label:
            messagebox.showwarning("Validation", "Bank and Label cannot both be blank.")
            return
        name = f"{bank} - {label}" if bank and label else (bank or label)
        try:
            max_bal = float(mb_raw) if mb_raw else None
        except ValueError:
            messagebox.showwarning("Validation", "Int. Cap £ must be a number.")
            return
        if ptype and ptype not in db.get_product_types():
            db.add_product_type(ptype)
            self._pt_combo["values"] = db.get_product_types()

        if self._selected_id:
            # Update existing account
            try:
                db.update_account_details(self._selected_id, bank or None, label or None,
                                          name, ptype or None, max_bal, cat or None)
            except Exception as exc:
                messagebox.showerror("Save failed", str(exc))
                return
        else:
            # Create new account
            if not bank:
                messagebox.showwarning("Validation", "Bank is required to create an account.")
                return
            if not label:
                messagebox.showwarning("Validation", "Label is required to create an account.")
                return
            try:
                db.upsert_account(
                    account_name=name,
                    bank=bank,
                    account_type=label,
                    category=cat or None,
                    max_balance_for_rate=max_bal,
                    interest_rate=0.0,
                    allocations={},
                    effective_from=datetime.date.today().isoformat(),
                    note=None,
                    product_type=ptype or None,
                )
            except Exception as exc:
                messagebox.showerror("Create failed", str(exc))
                return
        self._cat_combo["values"] = db.get_account_categories()
        self._clear_selection()
        self.refresh()

    def _deactivate(self):
        if not self._selected_id:
            return
        acc = db.get_account_by_id(self._selected_id)
        if messagebox.askyesno("Confirm", f"Deactivate '{acc['account_name']}'?\n"
                               "It will no longer appear in snapshots but history is kept."):
            db.deactivate_account(self._selected_id)
            self._clear_selection()
            self.refresh()

    def _reactivate(self):
        if not self._selected_id:
            return
        acc = db.get_account_by_id(self._selected_id)
        if messagebox.askyesno("Confirm", f"Reactivate '{acc['account_name']}'?\n"
                               "It will appear in new snapshots again."):
            db.reactivate_account(self._selected_id)
            self._clear_selection()
            self.refresh()

    def _clear_selection(self):
        self._selected_id     = None
        self._selected_active = True
        self.tree.selection_remove(self.tree.selection())
        self._sel_label.config(text="New account", fg=SUBTEXT)
        self._bank_var.set("")
        self._actype_var.set("")
        self._pt_var.set("")
        self._cat_var.set("")
        self._maxbal_var.set("")
        self._save_btn.config(text="Create Account")
        self._toggle_btn.pack_forget()
        self._unselect_btn.pack_forget()


# ---------------------------------------------------------------------------
# Tab 2 — Snapshot entry
# ---------------------------------------------------------------------------

class SnapshotTab(tk.Frame):
    """Single scrollable table — account rows × (balance, rate, one column per category).
    Category cells: type £500 for a fixed amount, 60% for remainder share."""

    _CAT_SHORT = {"Spending": "Spending", "Deposit": "Deposit",
                  "Emergency Fund": "Emerg. Fund", "Long Term Savings": "LT Savings",
                  "Pension": "Pension"}

    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._bal_vars   = {}   # acc_id -> StringVar
        self._rate_vars  = {}   # acc_id -> StringVar  (blank = no change)
        self._cat_vars   = {}   # acc_id -> {cat: StringVar}
        self._accounts   = []
        self._cur_allocs = {}   # acc_id -> {cat: {"fixed": float, "pct": float}}
        self._build()

    def _build(self):
        # Header
        hdr = styled_frame(self)
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        styled_label(hdr, "Log Balance Snapshot", font=STYLE["font_h1"]).pack(side="left")
        styled_button(hdr, "Save Snapshot", self._save, color=GREEN).pack(side="right")
        styled_button(hdr, "Delete Records", self._open_delete_dialog, color=RED).pack(side="right", padx=8)
        styled_button(hdr, "Clear", self._reset, color=SUBTEXT).pack(side="right", padx=8)
        styled_button(hdr, "⟳ Refresh", self._load_previous, color=GREEN).pack(side="right", padx=8)

        # Date + hint row
        date_row = styled_frame(self)
        date_row.pack(fill="x", padx=20, pady=(4, 6))
        styled_label(date_row, "Date / time:").pack(side="left")
        _dfmt = _DATE_FORMATS.get(db.get_setting("date_format", "YYYY-MM-DD"), "%Y-%m-%d")
        self.date_var = tk.StringVar(
            value=datetime.datetime.now().strftime(f"{_dfmt} %H:%M"))
        styled_entry(date_row, width=20, textvariable=self.date_var).pack(side="left", padx=8)
        _dfmt_label = db.get_setting("date_format", "YYYY-MM-DD")
        styled_label(date_row,
                     f"({_dfmt_label} HH:MM)  ·  Category cells: £500 = fixed, 60% = remainder",
                     fg=SUBTEXT).pack(side="left")

        # ---- two-panel body ----
        body = styled_frame(self)
        # Scrollable table with both scrollbars
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True, padx=20, pady=(0, 12))

        self._canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        v_sb = ttk.Scrollbar(outer, orient="vertical",   command=self._canvas.yview)
        h_sb = ttk.Scrollbar(outer, orient="horizontal", command=self._canvas.xview)
        self._canvas.configure(yscrollcommand=v_sb.set, xscrollcommand=h_sb.set)

        self.inner = tk.Frame(self._canvas, bg=BG)
        self._canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self._canvas.configure(
            scrollregion=self._canvas.bbox("all")))

        self._canvas.grid(row=0, column=0, sticky="nsew")
        v_sb.grid(row=0, column=1, sticky="ns")
        h_sb.grid(row=1, column=0, sticky="ew")
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_columnconfigure(0, weight=1)

        # Activate scroll only while the mouse is over this canvas so it
        # doesn't fight with other scrollable areas on other tabs.
        def _scroll(e):
            self._canvas.yview_scroll(-1 * (e.delta // 120), "units")
        self._canvas.bind("<Enter>", lambda e: self._canvas.bind_all("<MouseWheel>", _scroll))
        self._canvas.bind("<Leave>", lambda e: self._canvas.unbind_all("<MouseWheel>"))

        self._populate()

    # ------------------------------------------------------------------
    # Build / reset the table rows
    # ------------------------------------------------------------------

    def rebuild(self):
        """Rebuild after spending categories change."""
        self._populate()

    def _populate(self):
        self.CATS     = db.get_spending_category_names()
        self.CAT_HDRS = [self._CAT_SHORT.get(c, c) for c in self.CATS]
        for w in self.inner.winfo_children():
            w.destroy()
        self._bal_vars    = {}
        self._rate_vars   = {}
        self._cat_vars    = {}
        self._bal_entries  = []
        self._rate_entries = []
        self._cat_entries  = {cat: [] for cat in self.CATS}

        self._accounts = db.get_all_accounts()
        prev           = db.get_latest_balance_per_account()   # most recent per account
        today          = datetime.date.today().isoformat()
        cur_rates      = db._get_rates_on_date(today)
        self._cur_allocs = {acc["id"]: db.get_allocations_on_date(acc["id"], today)
                            for acc in self._accounts}

        # Column definitions: (header, width-in-chars, anchor)
        fixed_cols = [
            ("Account",      22, "w"),
            ("Prev Balance", 13, "e"),
            ("New Balance",  13, "w"),
            ("Cur Rate %",    9, "e"),
            ("New Rate %",   10, "w"),
        ]
        n_fixed  = len(fixed_cols)
        all_cols = fixed_cols + [(h, 11, "w") for h in self.CAT_HDRS]

        # Row 0 — column headers
        for c, (text, w, anchor) in enumerate(all_cols):
            bg = BG3 if c >= n_fixed else BG
            tk.Label(self.inner, text=text, bg=bg, fg=ACCENT,
                     font=STYLE["font_bold"], width=w, anchor=anchor, pady=3
                     ).grid(row=0, column=c, padx=1, pady=(0, 1), sticky="ew")

        # Row 1 — £/% hint under category columns only
        for c in range(n_fixed, len(all_cols)):
            tk.Label(self.inner, text="£ or %", bg=BG3, fg=SUBTEXT,
                     font=("Segoe UI", 8), width=11, anchor="center"
                     ).grid(row=1, column=c, padx=1, pady=(0, 3), sticky="ew")

        # Account rows — flat list sorted by bank then name
        sorted_accounts = sorted(self._accounts,
                                 key=lambda a: (a["bank"] or "", a["account_name"]))

        _SNAP_BANK_BG = [
            "#1a2030",  # slate blue
            "#1a2a1e",  # forest green
            "#2a221a",  # amber
            "#251a2a",  # purple
            "#1a2828",  # teal
            "#2a1a1e",  # rose
            "#1e1a2a",  # indigo
            "#22261a",  # olive
        ]
        _snap_banks = sorted({
            (a.get("bank") or "").strip()
            for a in sorted_accounts
            if (a.get("bank") or "").strip()
        })
        _snap_bank_bg = {bank: _SNAP_BANK_BG[i % len(_SNAP_BANK_BG)]
                         for i, bank in enumerate(_snap_banks)}

        for grid_row, acc in enumerate(sorted_accounts, start=2):
            acc_id   = acc["id"]
            prev_bal = prev.get(acc_id)
            cur_rate = cur_rates.get(acc_id, 0.0)
            allocs   = self._cur_allocs.get(acc_id, {})
            col      = 0

            # Bank-tinted row background so related accounts cluster visually
            _bank_key = (acc.get("bank") or "").strip()
            row_bg = _snap_bank_bg.get(_bank_key, BG if grid_row % 2 == 0 else BG2)

            # Account name
            tk.Label(self.inner, text=acc["account_name"], bg=row_bg, fg=FG,
                     font=STYLE["font"], width=22, anchor="w"
                     ).grid(row=grid_row, column=col, padx=1, pady=0, sticky="ew")
            col += 1

            # Previous balance (read-only)
            tk.Label(self.inner,
                     text=fmt_gbp(prev_bal) if prev_bal is not None else "—",
                     bg=row_bg, fg=SUBTEXT, font=STYLE["font_mono"],
                     width=13, anchor="e"
                     ).grid(row=grid_row, column=col, padx=1, sticky="ew")
            col += 1

            # New balance entry — focus-in autofills from previous balance if empty
            bal_var   = tk.StringVar()
            bal_entry = styled_entry(self.inner, width=13, textvariable=bal_var)
            bal_entry.grid(row=grid_row, column=col, padx=1, pady=1)
            self._bal_vars[acc_id]  = bal_var
            self._bal_entries.append(bal_entry)

            def _colour_entry(*_args, v=bal_var, pv=prev_bal, w=bal_entry):
                raw = v.get().strip().replace("£", "").replace(",", "")
                if not raw:
                    w.config(bg=BG3)
                    return
                try:
                    val = float(raw)
                except ValueError:
                    w.config(bg=BG3)
                    return
                if pv is None or val == pv:
                    w.config(bg=BG3)
                elif val > pv:
                    w.config(bg="#1a3025")
                else:
                    w.config(bg="#3a1a20")
            bal_var.trace_add("write", _colour_entry)

            if prev_bal is not None:
                def _autofill(e, v=bal_var, pv=prev_bal):
                    if v.get() == "":
                        v.set(f"{pv:.2f}")
                        e.widget.after(0, lambda w=e.widget: (
                            w.selection_range(0, tk.END),
                            w.icursor(tk.END),
                        ))
                bal_entry.bind("<FocusIn>", _autofill)
            col += 1

            # Current rate (read-only)
            tk.Label(self.inner,
                     text=f"{cur_rate*100:.2f}%" if cur_rate else "—",
                     bg=row_bg, fg=SUBTEXT, font=STYLE["font_mono"],
                     width=9, anchor="e"
                     ).grid(row=grid_row, column=col, padx=1, sticky="ew")
            col += 1

            # New rate entry (blank = no change)
            rate_var   = tk.StringVar()
            rate_entry = styled_entry(self.inner, width=10, textvariable=rate_var)
            rate_entry.grid(row=grid_row, column=col, padx=1, pady=1)
            self._rate_vars[acc_id]  = rate_var
            self._rate_entries.append(rate_entry)
            col += 1

            # Category cells — pre-filled with current allocation
            self._cat_vars[acc_id] = {}
            for cat in self.CATS:
                current = allocs.get(cat, {"fixed": 0.0, "pct": 0.0})
                if current["fixed"]:
                    default = f"£{current['fixed']:.2f}"
                elif current["pct"]:
                    default = f"{current['pct']*100:.2f}%"
                else:
                    default = ""
                var       = tk.StringVar(value=default)
                cat_entry = styled_entry(self.inner, width=11, textvariable=var)
                cat_entry.grid(row=grid_row, column=col, padx=1, pady=1)
                self._cat_vars[acc_id][cat] = var
                self._cat_entries[cat].append(cat_entry)
                col += 1

        self._setup_tab_order()

    def _setup_tab_order(self):
        """Column-major Tab order: all balance rows → all rate rows → each category column."""
        order = (
            self._bal_entries
            + self._rate_entries
            + [e for cat in self.CATS for e in self._cat_entries[cat]]
        )
        n = len(order)
        if n == 0:
            return
        for i, entry in enumerate(order):
            def _next(e, i=i):
                order[(i + 1) % n].focus_set()
                return "break"
            def _prev(e, i=i):
                order[(i - 1) % n].focus_set()
                return "break"
            entry.bind("<Tab>",       _next)
            entry.bind("<Shift-Tab>", _prev)

    def _load_previous(self):
        self._populate()

    def _open_delete_dialog(self):
        DeleteSnapshotDialog(self, on_done=self._populate)

    def _reset(self):
        _dfmt = _DATE_FORMATS.get(db.get_setting("date_format", "YYYY-MM-DD"), "%Y-%m-%d")
        self.date_var.set(datetime.datetime.now().strftime(f"{_dfmt} %H:%M"))
        for var in self._bal_vars.values():
            var.set("")
        for var in self._rate_vars.values():
            var.set("")
        for cat_dict in self._cat_vars.values():
            for var in cat_dict.values():
                var.set("")

    # ------------------------------------------------------------------
    # Parse / validate
    # ------------------------------------------------------------------

    def _parse_cat_cell(self, raw: str):
        """Parse one category cell.
        Returns ("fixed", £amount), ("pct", fraction), or None if blank.
        No % → fixed £.   Has % → remainder fraction.
        """
        val = raw.strip()
        if not val:
            return None
        if "%" in val:
            try:
                return ("pct", float(val.replace("%", "").strip()) / 100)
            except ValueError:
                raise ValueError(f"invalid %: '{val}'")
        else:
            try:
                return ("fixed", float(val.replace("£", "").replace(",", "").strip()))
            except ValueError:
                raise ValueError(f"invalid amount: '{val}'")

    def _parse_all_cat_vars(self, acc_id):
        """Return {cat: {"fixed": float, "pct": float}}, or None if all cells blank."""
        parsed    = {}
        any_filled = False
        for cat, var in self._cat_vars[acc_id].items():
            result = self._parse_cat_cell(var.get())   # raises ValueError on bad input
            if result is not None:
                any_filled = True
            if result is None:
                parsed[cat] = {"fixed": 0.0, "pct": 0.0}
            elif result[0] == "fixed":
                parsed[cat] = {"fixed": result[1], "pct": 0.0}
            else:
                parsed[cat] = {"fixed": 0.0, "pct": result[1]}
        return parsed if any_filled else None

    def _alloc_changed(self, acc_id, new_alloc) -> bool:
        current = self._cur_allocs.get(acc_id, {})
        for cat, vals in new_alloc.items():
            cur = current.get(cat, {"fixed": 0.0, "pct": 0.0})
            if (abs(vals["fixed"] - cur["fixed"]) > 0.005 or
                    abs(vals["pct"]   - cur["pct"])   > 0.00005):
                return True
        return False

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _save(self):
        raw_date  = self.date_var.get().strip()
        _dfmt     = _DATE_FORMATS.get(db.get_setting("date_format", "YYYY-MM-DD"), "%Y-%m-%d")
        parsed_dt = None
        for _fmt in (f"{_dfmt} %H:%M", f"{_dfmt}", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                parsed_dt = datetime.datetime.strptime(raw_date, _fmt)
                break
            except ValueError:
                pass
        if parsed_dt is None:
            lbl = db.get_setting("date_format", "YYYY-MM-DD")
            messagebox.showerror("Error", f"Invalid date. Expected format: {lbl} HH:MM")
            return
        date_str = parsed_dt.strftime("%Y-%m-%d %H:%M")

        # Balances — blank means "don't record this account" (not £0)
        balances = {}
        for acc_id, var in self._bal_vars.items():
            raw = var.get().strip().replace("£", "").replace(",", "")
            if not raw:
                continue  # skip — leave any existing entry for this account untouched
            try:
                balances[acc_id] = float(raw)
            except ValueError:
                messagebox.showerror("Error", f"Invalid balance: '{raw}'")
                return

        # Rates (blank = no change)
        new_rates = {}
        for acc_id, var in self._rate_vars.items():
            raw = var.get().strip().replace("%", "")
            if not raw:
                continue
            try:
                new_rates[acc_id] = float(raw) / 100
            except ValueError:
                messagebox.showerror("Error", f"Invalid rate: '{raw}'")
                return

        # Allocations — all-blank row = skip; any filled = validate whole row
        new_allocs = {}
        for acc_id in self._cat_vars:
            acc_name = next((a["account_name"] for a in self._accounts
                             if a["id"] == acc_id), str(acc_id))
            try:
                alloc_data = self._parse_all_cat_vars(acc_id)
            except ValueError as exc:
                messagebox.showerror("Error", f"'{acc_name}': {exc}")
                return

            if alloc_data is None:
                continue   # all blank → no allocation change for this account

            total_pct = sum(v["pct"] for v in alloc_data.values())
            if total_pct > 0 and abs(total_pct - 1.0) > 0.001:
                messagebox.showerror("Error",
                    f"'{acc_name}': remainder % must sum to 100 "
                    f"(got {total_pct * 100:.2f}%).")
                return

            if self._alloc_changed(acc_id, alloc_data):
                new_allocs[acc_id] = alloc_data

        # Persist everything
        db.save_snapshot(date_str, balances)
        for acc_id, rate in new_rates.items():
            db.save_account_rate(acc_id, rate, date_str)
        for acc_id, alloc_data in new_allocs.items():
            db.save_account_allocation(acc_id, alloc_data, date_str)

        parts = [f"Snapshot saved for {date_str}"]
        if new_rates:
            parts.append(f"{len(new_rates)} rate(s) updated")
        if new_allocs:
            parts.append(f"{len(new_allocs)} allocation(s) updated")
        messagebox.showinfo("Saved", "\n".join(parts) + ".")
        self._reset()


# ---------------------------------------------------------------------------
# Tab 3 — History charts
# ---------------------------------------------------------------------------

class HistoryTab(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._time_range     = db.get_setting("history_default_range", "ALL")
        self._drilldown      = None   # None = full view; str = single category drill-down
        self._hover_x        = []
        self._hover_data     = []
        self._cids           = []
        self._resize_job     = None
        self._cat_stack_data = None
        self._ax2            = None   # twin y-axis for income overlay
        self._show_income    = tk.BooleanVar(value=False)
        self._build()

    def _build(self):
        hdr = styled_frame(self)
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        styled_label(hdr, "Balance History", font=STYLE["font_h1"]).pack(side="left")
        styled_button(hdr, "⟳ Refresh", self.refresh, color=GREEN).pack(side="right")

        # Options row — back button + income overlay toggle
        ctrl = styled_frame(self)
        ctrl.pack(fill="x", padx=20, pady=(4, 2))
        self._back_btn = styled_button(ctrl, "← All categories",
                                       self._clear_drilldown, color=SUBTEXT)
        # packed/unpacked dynamically by _sync_back_btn
        tk.Checkbutton(ctrl, text="Show income overlay", variable=self._show_income,
                       bg=BG, fg=SUBTEXT, selectcolor=BG3, activebackground=BG,
                       activeforeground=FG, font=STYLE["font"],
                       command=self.refresh).pack(side="right", padx=4)

        # Time range
        range_row = styled_frame(self)
        range_row.pack(fill="x", padx=20, pady=(0, 2))
        styled_label(range_row, "Period:").pack(side="left")
        self._range_btns = {}
        for r in ("ALL", "2Y", "1Y", "6M", "3M", "YTD"):
            btn = tk.Button(range_row, text=r,
                            bg=BG3, fg=FG, relief="flat", font=STYLE["font"],
                            padx=8, pady=2, cursor="hand2",
                            activebackground=BG2, activeforeground=ACCENT,
                            command=lambda r=r: self._set_range(r))
            btn.pack(side="left", padx=2)
            self._range_btns[r] = btn

        # Chart
        self.fig = Figure(figsize=(10, 5), facecolor=BG)
        self.ax  = self.fig.add_subplot(111, facecolor=BG2)
        self.canvas_widget = embed_figure(self, self.fig)
        self.canvas_widget.pack(fill="both", expand=True, padx=20, pady=(4, 16))

        self._update_range_styles()
        self.after_idle(self.refresh)

    # ---- State changes ----

    def _set_range(self, r):
        self._time_range = r
        self._update_range_styles()
        self.refresh()

    def _set_drilldown(self, cat):
        self._drilldown = cat
        self._sync_back_btn()
        self.refresh()

    def _clear_drilldown(self):
        self._drilldown = None
        self._sync_back_btn()
        self.refresh()

    def _update_range_styles(self):
        for r, btn in self._range_btns.items():
            active = (r == self._time_range)
            btn.config(bg=ACCENT if active else BG3,
                       fg=BG   if active else FG)

    def _sync_back_btn(self):
        if self._drilldown:
            self._back_btn.pack(side="left", padx=(0, 0))
        else:
            self._back_btn.pack_forget()

    # ---- Date filtering ----

    def _date_cutoff(self):
        if self._time_range == "ALL":
            return None
        today = datetime.date.today()
        if self._time_range == "YTD":
            start = datetime.date(today.year, 1, 1)
        else:
            days = {"2Y": 730, "1Y": 365, "6M": 182, "3M": 91}[self._time_range]
            start = today - datetime.timedelta(days=days)
        return start.isoformat()

    def _trim(self, items, date_fn):
        cutoff = self._date_cutoff()
        if not cutoff:
            return items
        return [x for x in items if date_fn(x) >= cutoff]

    # ---- Interactive events (legend click + hover tooltip) ----

    def _setup_interactions(self):
        for cid in self._cids:
            try:
                self.fig.canvas.mpl_disconnect(cid)
            except Exception:
                pass
        self._cids = []
        self._bg   = None

        self._annot = self.ax.annotate(
            "", xy=(0, 0), xytext=(12, 12), textcoords="offset points",
            bbox=dict(boxstyle="round,pad=0.5", fc=BG3, ec=SUBTEXT, alpha=0.93),
            color=FG, fontsize=8, visible=False, zorder=10,
        )

        # Capture background only if canvas has a real size; defer if not yet laid out
        if self.fig.bbox.width > 1:
            self._bg = self.fig.canvas.copy_from_bbox(self.fig.bbox)
        else:
            self._bg = None

        def _on_resize(event):
            # Invalidate immediately so hover returns early during drag
            self._bg = None
            self._annot.set_visible(False)
            # Debounce: recapture after resize settles
            if self._resize_job:
                self.after_cancel(self._resize_job)
            self._resize_job = self.after(150, _recapture_bg)

        def _recapture_bg():
            self._resize_job = None
            self.fig.canvas.draw()
            self._bg = self.fig.canvas.copy_from_bbox(self.fig.bbox)

        self._cids.append(
            self.fig.canvas.mpl_connect("resize_event", _on_resize))

        self._cids.append(
            self.fig.canvas.mpl_connect("button_press_event", self._on_click))
        self._cids.append(
            self.fig.canvas.mpl_connect("motion_notify_event", self._on_hover))

    def _hit_test_category(self, xdata, ydata):
        """Return the category name at (xdata, ydata) in the stacked chart, or None."""
        if not self._cat_stack_data:
            return None
        cats, x_vals, ys_mat = self._cat_stack_data
        if not x_vals:
            return None
        idx = min(range(len(x_vals)), key=lambda i: abs(x_vals[i] - xdata))
        has_pos = {n for n, ys in zip(cats, ys_mat) if any(v > 0 for v in ys)}
        has_neg = {n for n, ys in zip(cats, ys_mat) if any(v < 0 for v in ys)}
        pos_cum = 0.0
        neg_cum = 0.0
        for cat, ys in zip(cats, ys_mat):
            pos_val = max(0.0, ys[idx]) if cat in has_pos else 0.0
            neg_val = min(0.0, ys[idx]) if cat in has_neg else 0.0
            if pos_val > 0 and pos_cum <= ydata <= pos_cum + pos_val:
                return cat
            pos_cum += pos_val
            if neg_val < 0 and neg_cum + neg_val <= ydata <= neg_cum:
                return cat
            neg_cum += neg_val
        return None

    def _on_click(self, event):
        if self._drilldown:
            return
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return
        cat = self._hit_test_category(event.xdata, event.ydata)
        if cat:
            self._set_drilldown(cat)

    def _on_hover(self, event):
        if not hasattr(self, "_annot") or not self._hover_x or self._bg is None:
            return

        tk_widget = self.fig.canvas.get_tk_widget()

        def _blit_hide():
            self._annot.set_visible(False)
            self.fig.canvas.restore_region(self._bg)
            self.fig.canvas.blit(self.fig.bbox)

        if event.inaxes != self.ax or event.xdata is None:
            if self._annot.get_visible():
                _blit_hide()
            tk_widget.config(cursor="")
            return

        # Show hand cursor when hovering a clickable category band
        clickable = (not self._drilldown
                     and event.ydata is not None
                     and self._hit_test_category(event.xdata, event.ydata) is not None)
        tk_widget.config(cursor="hand2" if clickable else "")

        idx    = min(range(len(self._hover_x)),
                     key=lambda i: abs(self._hover_x[i] - event.xdata))
        info   = self._hover_data[idx]
        values = info.get("values", {})
        if not values:
            if self._annot.get_visible():
                _blit_hide()
            return

        raw        = info["date"]
        date_label = format_date(raw)

        sorted_vals = sorted(values.items(), key=lambda kv: -kv[1])
        lines = [date_label]
        for name, val in sorted_vals:
            lines.append(f"{name}: {fmt_gbp(val)}")
        total = sum(values.values())
        lines += ["─" * max(len(l) for l in lines), f"Total: {fmt_gbp(total)}"]

        self._annot.set_text("\n".join(lines))
        self._annot.xy = (self._hover_x[idx], event.ydata)
        self._annot.set_visible(True)
        self.fig.canvas.restore_region(self._bg)
        self.ax.draw_artist(self._annot)
        self.fig.canvas.blit(self.fig.bbox)

    # ---- Refresh ----

    def refresh(self):
        # Remove twin axis from previous render
        if self._ax2 is not None:
            try:
                self._ax2.remove()
            except Exception:
                pass
            self._ax2 = None

        self._hover_x        = []
        self._hover_data     = []
        self._cat_stack_data = None
        self.ax.clear()
        self.ax.set_facecolor(BG2)
        self.fig.patch.set_facecolor(BG)
        for spine in self.ax.spines.values():
            spine.set_edgecolor(BG3)
        self.ax.tick_params(colors=SUBTEXT)
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
        self.ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        self.fig.autofmt_xdate()

        if self._drilldown:
            self._plot_category_drilldown(self._drilldown)
        else:
            self._plot_by_category()
        if self._show_income.get():
            self._overlay_income()

        self.ax.yaxis.set_major_formatter(
            matplotlib.ticker.FuncFormatter(lambda x, _: f"£{x:,.2f}"))
        self.ax.legend(facecolor=BG3, edgecolor=BG3, labelcolor=FG,
                       fontsize=8, loc="upper left")
        self.fig.canvas.draw()
        self._setup_interactions()

    def _dates_to_mpl(self, dates):
        result = []
        for d in dates:
            for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    result.append(mdates.date2num(datetime.datetime.strptime(d, fmt)))
                    break
                except ValueError:
                    pass
        return result

    # ---- Helpers ----

    def _signed_stackplot(self, x, names, ys_mat, colours):
        has_pos = {n for n, ys in zip(names, ys_mat) if any(v > 0 for v in ys)}
        has_neg = {n for n, ys in zip(names, ys_mat) if any(v < 0 for v in ys)}

        pos = [(n, [max(0.0, v) for v in ys], c)
               for n, ys, c in zip(names, ys_mat, colours) if n in has_pos]
        neg = [(n, [min(0.0, v) for v in ys], c)
               for n, ys, c in zip(names, ys_mat, colours) if n in has_neg]

        if pos:
            pn, pys, pc = zip(*pos)
            self.ax.stackplot(x, pys, labels=pn, colors=pc, alpha=0.7)

        if neg:
            nn, nys, nc = zip(*neg)
            polys = self.ax.stackplot(x, nys, colors=nc, alpha=0.7)
            for poly, name in zip(polys, nn):
                if name not in has_pos:
                    poly.set_label(name)

        self.ax.axhline(0, color=SUBTEXT, linewidth=0.5, linestyle="--")

    # ---- Plot methods ----

    def _overlay_income(self):
        """Overlay individual income entries as a line on the main axis (same scale)."""
        rows = db.get_all_income()
        if not rows:
            return

        rows = sorted(rows, key=lambda r: r["entry_date"])
        rows = self._trim(rows, date_fn=lambda r: r["entry_date"])
        if not rows:
            return

        x_inc = self._dates_to_mpl([r["entry_date"] for r in rows])
        y_inc = [r["amount"] for r in rows]

        self.ax.plot(x_inc, y_inc, color=ACCENT, linewidth=1.4,
                     marker="o", markersize=3, zorder=5, label="Income")

    def _plot_by_category(self):
        history = self._trim(db.get_category_history(),
                             date_fn=lambda h: h["date"])
        if not history:
            self._cat_stack_data = None
            return
        cats    = list(history[0]["totals"].keys())
        x       = self._dates_to_mpl([h["date"] for h in history])
        ys_mat  = [[h["totals"].get(cat, 0.0) for h in history] for cat in cats]
        colours = [CAT_COLOURS.get(cat, SUBTEXT) for cat in cats]
        self._signed_stackplot(x, cats, ys_mat, colours)
        self._cat_stack_data = (cats, list(x), ys_mat)
        self._hover_x    = list(x)
        self._hover_data = [{"date": h["date"], "values": dict(h["totals"])}
                            for h in history]
        self.ax.set_title(
            "Balance by Spending Category  ·  click a section to drill down",
            color=FG, pad=10)

    def _plot_category_drilldown(self, cat_name):
        history = self._trim(db.get_category_account_breakdown(cat_name),
                             date_fn=lambda h: h["date"])
        if not history:
            self.ax.set_title(f"{cat_name} — no data in range", color=FG, pad=10)
            return
        all_accs = sorted({name for h in history for name in h["accounts"]})
        tab20    = plt.cm.tab20.colors
        x        = self._dates_to_mpl([h["date"] for h in history])
        ys_mat   = [[h["accounts"].get(acc, 0.0) for h in history] for acc in all_accs]
        colours  = [tab20[i % len(tab20)] for i in range(len(all_accs))]
        self._signed_stackplot(x, all_accs, ys_mat, colours)
        self._hover_x    = list(x)
        self._hover_data = [{"date": h["date"], "values": dict(h["accounts"])}
                            for h in history]
        self.ax.set_title(f"{cat_name} — by account  ·  use ← All categories to go back",
                          color=FG, pad=10)


# ---------------------------------------------------------------------------
# Tab 4 — Categories breakdown
# ---------------------------------------------------------------------------

class CategoriesTab(tk.Frame):
    def __init__(self, parent, on_change=None):
        super().__init__(parent, bg=BG)
        self._on_change = on_change
        self._build()

    def _build(self):
        hdr = styled_frame(self)
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        styled_label(hdr, "Category Breakdown", font=STYLE["font_h1"]).pack(side="left")
        styled_button(hdr, "⟳ Refresh", self.refresh, color=GREEN).pack(side="right")

        # Manage categories
        manage = tk.Frame(self, bg=BG2)
        manage.pack(fill="x", padx=20, pady=(0, 6))
        tk.Label(manage, text="Add category:", bg=BG2, fg=SUBTEXT,
                 font=STYLE["font"]).pack(side="left", padx=(10, 4), pady=6)
        self._new_cat_var = tk.StringVar()
        tk.Entry(manage, textvariable=self._new_cat_var, bg=BG3, fg=FG,
                 insertbackground=FG, relief="flat",
                 font=STYLE["font"], width=18).pack(side="left", padx=(0, 6))
        styled_button(manage, "+ Add", self._add_category, color=GREEN).pack(side="left")

        self._cat_list_frame = tk.Frame(self, bg=BG)
        self._cat_list_frame.pack(fill="x", padx=20, pady=(0, 4))
        self._rebuild_cat_list()

        # Latest snapshot summary
        section_label(self, "  Current Allocation").pack(fill="x", padx=20, pady=(8, 2))

        tree_frame = styled_frame(self)
        tree_frame.pack(fill="x", padx=20, pady=(0, 8))

        cols = ("category", "value", "pct")
        self.tree, sb = make_tree(tree_frame, cols, height=7)
        for col, hdr_text, w, anch in [
            ("category", "Category", 200, "w"),
            ("value", "Value", 160, "e"),
            ("pct", "% of Total", 120, "e"),
        ]:
            self.tree.heading(col, text=hdr_text)
            self.tree.column(col, width=w, anchor=anch)
        self.tree.pack(side="left", fill="x", expand=True)
        sb.pack(side="right", fill="y")

        # Pie chart
        self.fig = Figure(figsize=(5, 4), facecolor=BG)
        self.ax  = self.fig.add_subplot(111, facecolor=BG)
        self.canvas_widget = embed_figure(self, self.fig)
        self.canvas_widget.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        self.refresh()

    def _rebuild_cat_list(self):
        for w in self._cat_list_frame.winfo_children():
            w.destroy()
        cats = db.get_spending_categories()
        row = tk.Frame(self._cat_list_frame, bg=BG)
        row.pack(fill="x")
        for cat in cats:
            chip = tk.Frame(row, bg=BG3, padx=6, pady=2)
            chip.pack(side="left", padx=(0, 6), pady=2)
            tk.Label(chip, text=cat["name"], bg=BG3, fg=FG,
                     font=STYLE["font"]).pack(side="left")
            tk.Button(chip, text="✕", bg=BG3, fg=RED,
                      activebackground=BG2, activeforeground=RED,
                      relief="flat", font=STYLE["font"], cursor="hand2",
                      command=lambda cid=cat["id"], cname=cat["name"]: self._delete_category(cid, cname)
                      ).pack(side="left", padx=(4, 0))

    def _add_category(self):
        name = self._new_cat_var.get().strip()
        if not name:
            return
        db.add_spending_category(name)
        self._new_cat_var.set("")
        self._rebuild_cat_list()
        self.refresh()
        if self._on_change:
            self._on_change()

    def _delete_category(self, cat_id: int, cat_name: str):
        if not messagebox.askyesno(
            "Remove category",
            f"Remove '{cat_name}'?\n\nAll allocation rules for this category will also be deleted.",
        ):
            return
        db.delete_spending_category(cat_id)
        self._rebuild_cat_list()
        self.refresh()
        if self._on_change:
            self._on_change()

    def refresh(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        self.ax.clear()
        self.ax.set_facecolor(BG)
        self.fig.patch.set_facecolor(BG)

        history = db.get_category_history()
        if not history:
            return

        latest = history[-1]
        totals = latest["totals"]
        grand  = latest["grand_total"] or 1

        labels, sizes, colours = [], [], []
        for cat, val in totals.items():
            if val != 0:
                pct = val / grand * 100
                self.tree.insert("", "end", values=(cat, fmt_gbp(val), f"{pct:.2f}%"))
                labels.append(cat)
                sizes.append(abs(val))
                colours.append(CAT_COLOURS.get(cat, SUBTEXT))

        if sizes:
            wedges, texts, autotexts = self.ax.pie(
                sizes, labels=labels, colors=colours,
                autopct="%1.1f%%", startangle=140,
                textprops={"color": FG, "fontsize": 9},
                wedgeprops={"edgecolor": BG, "linewidth": 2}
            )
            for at in autotexts:
                at.set_color(BG)
                at.set_fontweight("bold")

        self.ax.set_title("Spending Category Allocation", color=FG, pad=10)
        self.fig.canvas.draw()


# ---------------------------------------------------------------------------
# Tab 5 — Interest
# ---------------------------------------------------------------------------

class InterestTab(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._build()

    def _build(self):
        hdr = styled_frame(self)
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        styled_label(hdr, "Interest & Projection", font=STYLE["font_h1"]).pack(side="left")

        # Projection control
        ctrl = styled_frame(self)
        ctrl.pack(fill="x", padx=20, pady=4)
        styled_label(ctrl, "Project forward:").pack(side="left")
        self.months_var = tk.StringVar(value="12")
        e = styled_entry(ctrl, width=6, textvariable=self.months_var)
        e.pack(side="left", padx=8)
        styled_label(ctrl, "months").pack(side="left")
        styled_button(ctrl, "Calculate", self.refresh, color=ACCENT).pack(side="left", padx=16)

        # Summary labels
        self.summary_frame = styled_frame(self)
        self.summary_frame.pack(fill="x", padx=20, pady=4)

        section_label(self, "  Account Detail").pack(fill="x", padx=20, pady=(8, 2))
        tree_outer = styled_frame(self)
        tree_outer.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        tree_inner = tk.Frame(tree_outer, bg=BG)
        tree_inner.pack(fill="both", expand=True)
        tree_inner.rowconfigure(0, weight=1)
        tree_inner.columnconfigure(0, weight=1)

        cols = ("account", "balance", "rate", "yearly", "daily", "projected", "gain")
        self.tree, sb = make_tree(tree_inner, cols, height=20)
        h_sb = ttk.Scrollbar(tree_inner, orient="horizontal", command=self.tree.xview)
        self.tree.configure(xscrollcommand=h_sb.set)

        for col, hdr_text, w in [
            ("account", "Account", 220), ("balance", "Balance", 120),
            ("rate", "Rate", 70), ("yearly", "Yearly Int", 110),
            ("daily", "Daily Int", 90), ("projected", "Projected", 120), ("gain", "Gain", 110),
        ]:
            self.tree.heading(col, text=hdr_text)
            self.tree.column(col, width=w, minwidth=w,
                             anchor="e" if col != "account" else "w", stretch=False)
        self.tree.column("account", stretch=True)

        self.tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        h_sb.grid(row=1, column=0, sticky="ew")

        self.refresh()

    def refresh(self):
        for w in self.summary_frame.winfo_children():
            w.destroy()
        for row in self.tree.get_children():
            self.tree.delete(row)

        try:
            months = int(self.months_var.get())
        except ValueError:
            months = 12

        summary = db.get_current_interest_summary()
        projection = {r["account_name"]: r for r in db.project_balances(months)}

        total_yearly = sum(r["yearly_interest"] for r in summary)
        total_daily  = sum(r["daily_interest"] for r in summary)
        total_gain   = sum(r["gain"] for r in projection.values() if r["gain"] > 0)

        for label, val, colour in [
            ("Total Yearly Interest", fmt_gbp(total_yearly), YELLOW),
            ("Total Daily Interest",  fmt_gbp(total_daily),  YELLOW),
            (f"Projected Gain ({months}mo)", fmt_gbp(total_gain), GREEN),
        ]:
            f = tk.Frame(self.summary_frame, bg=BG3, padx=14, pady=8)
            tk.Label(f, text=label, bg=BG3, fg=SUBTEXT, font=STYLE["font"]).pack(anchor="w")
            tk.Label(f, text=val, bg=BG3, fg=colour,
                     font=("Segoe UI", 14, "bold")).pack(anchor="w")
            f.pack(side="left", padx=(0, 12))

        for r in summary:
            proj = projection.get(r["account_name"], {})
            self.tree.insert("", "end", values=(
                r["account_name"],
                fmt_gbp(r["balance"]),
                fmt_pct(r["rate"]),
                fmt_gbp(r["yearly_interest"]),
                fmt_gbp(r["daily_interest"]),
                fmt_gbp(proj.get("projected", r["balance"])),
                fmt_gbp(proj.get("gain", 0.0)),
            ))


# ---------------------------------------------------------------------------
# Tab 6 — Mortgage
# ---------------------------------------------------------------------------

class MortgageTab(tk.Frame):
    # (key, display label, hint text, pct flag)
    _FIXED_FIELDS = [
        ("income",  "Annual salary (£):",        "e.g. 35 000",  False),
        ("bonus",   "Annual bonus (£):",          "e.g. 0",       False),
        ("pension", "Pension contribution (%):",  "e.g. 5",       True),
    ]
    _PROP_FIELDS = [
        ("price",   "Property price (£):",        "e.g. 200 000", False),
        ("overbid", "Over-bid rate (%):",          "e.g. 5",       True),
        ("fees",    "Fees & moving costs (£):",    "e.g. 5 000",   False),
        ("term",    "Mortgage term (years):",      "e.g. 25",      False),
        ("boe",     "BoE base rate (%):",          "e.g. 4.5",     True),
    ]

    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._fixed_vars      = {}   # key → StringVar
        self._fixed_hints     = {}   # key → hint string
        self._fixed_entries   = {}   # key → Entry widget
        self._income_items    = []   # [{label_var, amount_var, frame}]
        self._expense_items   = []   # [{label_var, amount_var, frame}]
        self._left_canvas     = None
        self._deposit_mode    = tk.StringVar(value="category")
        self._deposit_cat_var = tk.StringVar()
        self._deposit_custom_var = tk.StringVar()
        self._deposit_cat_combo  = None
        self._deposit_custom_ent = None
        self._results_fig        = None   # matplotlib figure; closed before recreating
        self._calc_state         = None   # stores last calc inputs for what-if
        self._wi_dep_var         = None   # set in _build_whatif_sliders
        self._wi_sal_var         = None
        self._wi_dep_lbl         = None
        self._wi_sal_lbl         = None
        self._wi_dep_scale       = None
        self._wi_updating        = False  # guard against recursive slider traces
        self._build()

    # ---- Placeholder helper ----

    @staticmethod
    def _hint_entry(entry, var, hint):
        """Attach greyed placeholder text to an Entry that uses a StringVar."""
        def _show():
            if not var.get():
                var.set(hint)
                entry.config(fg=SUBTEXT)

        def _focus_in(_):
            if var.get() == hint:
                var.set("")
                entry.config(fg=FG)

        def _focus_out(_):
            if not var.get():
                _show()
            else:
                entry.config(fg=FG)

        entry.bind("<FocusIn>",  _focus_in)
        entry.bind("<FocusOut>", _focus_out)
        _show()

    # ---- Layout ----

    def _build(self):
        hdr = styled_frame(self)
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        styled_label(hdr, "Mortgage Calculator", font=STYLE["font_h1"]).pack(side="left")

        body = styled_frame(self)
        body.pack(fill="both", expand=True, padx=20, pady=(0, 12))

        # ---- LEFT: scrollable inputs ----
        left_outer = styled_frame(body)
        left_outer.pack(side="left", fill="y", padx=(0, 16))

        lc = tk.Canvas(left_outer, bg=BG, highlightthickness=0, width=330)
        lsb = ttk.Scrollbar(left_outer, orient="vertical", command=lc.yview)
        left = tk.Frame(lc, bg=BG)
        left.bind("<Configure>", lambda e: lc.configure(scrollregion=lc.bbox("all")))
        _lc_win = lc.create_window((0, 0), window=left, anchor="nw")
        lc.configure(yscrollcommand=lsb.set)
        lc.bind("<Configure>", lambda e, _w=_lc_win: lc.itemconfigure(_w, width=e.width))
        lc.pack(side="left", fill="y", expand=False)
        lsb.pack(side="right", fill="y")
        lc.bind("<MouseWheel>", lambda e: lc.yview_scroll(-1*(e.delta//120), "units"))
        self._left_canvas = lc

        # Fixed income
        section_label(left, "Income").pack(anchor="w", pady=(4, 2))
        for key, lbl, hint, _ in self._FIXED_FIELDS:
            self._fixed_row(left, key, lbl, hint)

        # Property
        section_label(left, "Property").pack(anchor="w", pady=(10, 2))
        for key, lbl, hint, _ in self._PROP_FIELDS:
            self._fixed_row(left, key, lbl, hint)

        # Deposit source
        section_label(left, "Deposit").pack(anchor="w", pady=(10, 2))
        self._build_deposit_section(left)

        # Dynamic monthly income
        inc_hdr = styled_frame(left)
        inc_hdr.pack(fill="x", pady=(10, 2))
        section_label(inc_hdr, "Monthly Income").pack(side="left")
        tk.Button(inc_hdr, text="+ Add", bg=BG3, fg=GREEN, relief="flat",
                  font=STYLE["font"], padx=6, pady=1, cursor="hand2",
                  activebackground=BG2, activeforeground=GREEN,
                  command=self._add_income_row).pack(side="right")
        self._income_list_frame = tk.Frame(left, bg=BG)
        self._income_list_frame.pack(fill="x")

        # Dynamic monthly expenses
        exp_hdr = styled_frame(left)
        exp_hdr.pack(fill="x", pady=(10, 2))
        section_label(exp_hdr, "Monthly Expenses").pack(side="left")
        tk.Button(exp_hdr, text="+ Add", bg=BG3, fg=GREEN, relief="flat",
                  font=STYLE["font"], padx=6, pady=1, cursor="hand2",
                  activebackground=BG2, activeforeground=GREEN,
                  command=self._add_expense_row).pack(side="right")
        self._expense_list_frame = tk.Frame(left, bg=BG)
        self._expense_list_frame.pack(fill="x")

        # Calculate button
        styled_button(left, "Save & Calculate", self._calc, color=GREEN).pack(
            anchor="w", pady=(16, 8))

        # ---- RIGHT: what-if sliders (fixed) + scrollable results ----
        right_outer = styled_frame(body)
        right_outer.pack(side="left", fill="both", expand=True)

        # Slider panel — lives above the scroll area and is never destroyed
        self._wi_frame = tk.Frame(right_outer, bg=BG2)
        self._wi_frame.pack(fill="x")
        self._build_whatif_sliders()

        # Scrollable results below
        rc_wrap = tk.Frame(right_outer, bg=BG)
        rc_wrap.pack(fill="both", expand=True)
        rc = tk.Canvas(rc_wrap, bg=BG, highlightthickness=0)
        rsb = ttk.Scrollbar(rc_wrap, orient="vertical", command=rc.yview)
        self._results = styled_frame(rc)
        self._results.bind("<Configure>", lambda e: rc.configure(scrollregion=rc.bbox("all")))
        _rc_win = rc.create_window((0, 0), window=self._results, anchor="nw")
        rc.configure(yscrollcommand=rsb.set)
        rc.bind("<Configure>", lambda e, _w=_rc_win: rc.itemconfigure(_w, width=e.width))
        rc.pack(side="left", fill="both", expand=True)
        rsb.pack(side="right", fill="y")
        rc.bind_all("<MouseWheel>", lambda e: rc.yview_scroll(-1*(e.delta//120), "units"))

        self._load_from_db()
        self.after_idle(self._calc)

    def _fixed_row(self, parent, key, label, hint):
        row = styled_frame(parent)
        row.pack(fill="x", pady=1)
        tk.Label(row, text=label, bg=BG, fg=FG, font=STYLE["font"],
                 width=24, anchor="w").pack(side="left")
        var = tk.StringVar()
        ent = styled_entry(row, width=10, textvariable=var)
        ent.pack(side="left", padx=4)
        self._hint_entry(ent, var, hint)
        self._fixed_vars[key]   = var
        self._fixed_hints[key]  = hint
        self._fixed_entries[key] = ent

    def _build_deposit_section(self, parent):
        cats = db.get_spending_category_names()

        # Row 1: "From category" radio + combobox + live amount
        r1 = tk.Frame(parent, bg=BG)
        r1.pack(fill="x", pady=1)
        tk.Radiobutton(r1, text="From category:", variable=self._deposit_mode, value="category",
                       bg=BG, fg=FG, selectcolor=BG3, activebackground=BG, font=STYLE["font"],
                       command=self._on_deposit_mode_change).pack(side="left")
        self._deposit_cat_combo = ttk.Combobox(r1, textvariable=self._deposit_cat_var,
                                               values=cats, state="readonly", width=14,
                                               font=STYLE["font"])
        self._deposit_cat_combo.pack(side="left", padx=6)
        if cats and not self._deposit_cat_var.get():
            self._deposit_cat_var.set(cats[0])

        self._deposit_amount_label = tk.Label(r1, text="", bg=BG, fg=GREEN,
                                              font=STYLE["font_mono"])
        self._deposit_amount_label.pack(side="left", padx=(2, 0))

        # Row 2: "Custom amount" radio + entry
        r2 = tk.Frame(parent, bg=BG)
        r2.pack(fill="x", pady=1)
        tk.Radiobutton(r2, text="Custom amount (£):", variable=self._deposit_mode, value="custom",
                       bg=BG, fg=FG, selectcolor=BG3, activebackground=BG, font=STYLE["font"],
                       command=self._on_deposit_mode_change).pack(side="left")
        self._deposit_custom_ent = styled_entry(r2, width=10, textvariable=self._deposit_custom_var)
        self._deposit_custom_ent.pack(side="left", padx=4)
        self._hint_entry(self._deposit_custom_ent, self._deposit_custom_var, "e.g. 20 000")

        self._deposit_cat_var.trace_add("write", lambda *_: self._update_deposit_preview())
        self._on_deposit_mode_change()

    def _update_deposit_preview(self):
        if not hasattr(self, "_deposit_amount_label"):
            return
        if self._deposit_mode.get() != "category":
            self._deposit_amount_label.config(text="")
            return
        cat = self._deposit_cat_var.get()
        if not cat:
            self._deposit_amount_label.config(text="")
            return
        try:
            total = db.get_category_current_total(cat)
            self._deposit_amount_label.config(text=fmt_gbp(total))
        except Exception:
            self._deposit_amount_label.config(text="")

    def _on_deposit_mode_change(self):
        is_cat = self._deposit_mode.get() == "category"
        if self._deposit_cat_combo:
            self._deposit_cat_combo.config(state="readonly" if is_cat else "disabled")
        if self._deposit_custom_ent:
            self._deposit_custom_ent.config(state="normal" if not is_cat else "disabled")
        self._update_deposit_preview()

    def refresh_categories(self):
        """Called when spending categories are added or removed."""
        if not self._deposit_cat_combo:
            return
        cats    = db.get_spending_category_names()
        current = self._deposit_cat_var.get()
        self._deposit_cat_combo.config(values=cats)
        if current not in cats:
            self._deposit_cat_var.set(cats[0] if cats else "")
        self._update_deposit_preview()

    def _dynamic_row(self, parent, item_list, label="", amount=""):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=1)
        label_var  = tk.StringVar()
        amount_var = tk.StringVar()
        lbl_ent = styled_entry(row, width=16, textvariable=label_var)
        lbl_ent.pack(side="left")
        amt_ent = styled_entry(row, width=8, textvariable=amount_var)
        amt_ent.pack(side="left", padx=4)
        self._hint_entry(lbl_ent, label_var, "Label")
        self._hint_entry(amt_ent, amount_var, "£/mo")
        # Set real values after hints are wired (bypasses the empty-check)
        if label:
            label_var.set(label)
            lbl_ent.config(fg=FG)
        if amount:
            amount_var.set(str(amount))
            amt_ent.config(fg=FG)
        entry = {"label_var": label_var, "amount_var": amount_var,
                 "frame": row, "lbl_ent": lbl_ent, "amt_ent": amt_ent}

        def _delete(e=entry, r=row):
            item_list.remove(e)
            r.destroy()

        tk.Button(row, text="×", bg=BG3, fg=RED, relief="flat",
                  font=STYLE["font"], padx=4, cursor="hand2",
                  activebackground=BG2, activeforeground=RED,
                  command=_delete).pack(side="left")
        item_list.append(entry)

    def _add_income_row(self, label="", amount=""):
        self._dynamic_row(self._income_list_frame, self._income_items, label, amount)
        if self._left_canvas:
            self._left_canvas.yview_moveto(1.0)

    def _add_expense_row(self, label="", amount=""):
        self._dynamic_row(self._expense_list_frame, self._expense_items, label, amount)
        if self._left_canvas:
            self._left_canvas.yview_moveto(1.0)

    # ---- DB load / save ----

    def _load_from_db(self):
        fixed = db.get_mortgage_fixed()
        for key, var in self._fixed_vars.items():
            if key in fixed and fixed[key] != 0.0:
                var.set(str(fixed[key]))
                if key in self._fixed_entries:
                    self._fixed_entries[key].config(fg=FG)

        # Deposit settings
        mode = db.get_setting("mortgage_deposit_mode", "category")
        self._deposit_mode.set(mode)
        cat = db.get_setting("mortgage_deposit_category", "")
        if cat:
            self._deposit_cat_var.set(cat)
        fixed_all = db.get_mortgage_fixed()
        if "deposit_custom" in fixed_all:
            self._deposit_custom_var.set(str(fixed_all["deposit_custom"]))
        self._on_deposit_mode_change()

        for item in db.get_mortgage_income_items():
            self._add_income_row(item["label"], item["amount"])
        for item in db.get_mortgage_expense_items():
            self._add_expense_row(item["label"], item["amount"])

        self._update_deposit_preview()

    def _parse_fixed(self, key, pct=False):
        raw = self._fixed_vars[key].get()
        if raw == self._fixed_hints.get(key, ""):
            raw = ""
        raw = raw.replace(",", "").replace("£", "").replace("%", "").replace(" ", "").strip()
        val = float(raw) if raw else 0.0
        return val / 100 if pct else val

    def _read_dynamic_item(self, item):
        """Return (label, amount) stripping placeholder hints."""
        lbl = item["label_var"].get()
        if lbl == "Label":
            lbl = ""
        raw = item["amount_var"].get()
        if raw == "£/mo":
            raw = ""
        raw = raw.replace(",", "").replace("£", "").replace(" ", "").strip()
        amt = float(raw) if raw else 0.0
        return lbl, amt

    def _save_to_db(self):
        fixed_data = {k: self._parse_fixed(k) for k in self._fixed_vars}

        # Deposit custom amount
        dep_raw = self._deposit_custom_var.get()
        if dep_raw != "e.g. 20 000":
            dep_raw = dep_raw.replace(",", "").replace("£", "").replace(" ", "").strip()
            try:
                fixed_data["deposit_custom"] = float(dep_raw) if dep_raw else 0.0
            except ValueError:
                pass
        db.save_mortgage_fixed(fixed_data)
        db.set_setting("mortgage_deposit_mode",     self._deposit_mode.get())
        db.set_setting("mortgage_deposit_category", self._deposit_cat_var.get())

        income_items = []
        for item in self._income_items:
            lbl, amt = self._read_dynamic_item(item)
            income_items.append({"label": lbl, "amount": amt})
        db.save_mortgage_income_items(income_items)

        expense_items = []
        for item in self._expense_items:
            lbl, amt = self._read_dynamic_item(item)
            expense_items.append({"label": lbl, "amount": amt})
        db.save_mortgage_expense_items(expense_items)

    # ---- What-if sliders ----

    def _build_whatif_sliders(self):
        p = self._wi_frame
        section_label(p, "What-if Explorer").pack(anchor="w", padx=14, pady=(8, 4))

        self._wi_dep_var = tk.IntVar(value=0)
        self._wi_sal_var = tk.IntVar(value=0)

        def _row(parent, label, var):
            row = tk.Frame(parent, bg=BG2)
            row.pack(fill="x", padx=14, pady=3)
            tk.Label(row, text=label, bg=BG2, fg=SUBTEXT, font=STYLE["font"],
                     width=16, anchor="w").pack(side="left")
            # Track in a contrasting frame so the trough is clearly visible
            track_frame = tk.Frame(row, bg="#0e1e2e", bd=1, relief="solid")
            track_frame.pack(side="left", fill="x", expand=True, padx=(6, 8))
            sl = tk.Scale(track_frame, variable=var, from_=0, to=100_000,
                          resolution=500, orient="horizontal",
                          bg="#0e1e2e", fg=ACCENT, troughcolor="#1e3a50",
                          highlightthickness=0, showvalue=0,
                          activebackground=GREEN, sliderrelief="flat",
                          sliderlength=22, bd=0, width=12)
            sl.pack(fill="x")
            val_lbl = tk.Label(row, bg=BG2, fg=ACCENT,
                               font=STYLE["font_bold"], width=12, anchor="w")
            val_lbl.pack(side="left")
            return sl, val_lbl

        self._wi_dep_scale, self._wi_dep_lbl = _row(p, "Extra deposit:", self._wi_dep_var)
        self._wi_sal_scale, self._wi_sal_lbl = _row(p, "Extra salary:",  self._wi_sal_var)
        self._wi_dep_lbl.config(text="£0")
        self._wi_sal_lbl.config(text="£0")

        tk.Frame(p, bg=BG3, height=1).pack(fill="x", pady=(8, 0))

        self._wi_dep_var.trace_add("write", lambda *_: self._on_whatif_change())
        self._wi_sal_var.trace_add("write", lambda *_: self._on_whatif_change())

    def _on_whatif_change(self):
        if self._calc_state is None or self._wi_updating:
            return
        cs   = self._calc_state
        xdep = self._wi_dep_var.get()
        xsal = self._wi_sal_var.get()

        self._wi_dep_lbl.config(text=f"+£{xdep:,}" if xdep else "£0")
        self._wi_sal_lbl.config(text=f"+£{xsal:,}" if xsal else "£0")

        r_adj = db.mortgage_estimate(
            annual_income        = cs["income"] + xsal,
            bonus                = cs["bonus"],
            pension_pct          = cs["pension"],
            extra_monthly_income = cs["extra_monthly"],
            property_price       = cs["price"],
            overbid_rate         = cs["overbid"],
            fees                 = cs["r"]["fees"],
            boe_rate             = cs["boe"],
            term_years           = cs["term"],
            expenses             = cs["expenses"],
            deposit_raw          = cs["r"]["deposit_raw"] + xdep,
        )
        self._render_results(r_adj, cs["term"], cs["pension"], cs["income_items"])

    # ---- Calculate ----

    def _calc(self):
        try:
            self._save_to_db()
        except ValueError:
            messagebox.showerror("Error", "Invalid input — check all fields are numbers.")
            return

        income  = self._parse_fixed("income")
        bonus   = self._parse_fixed("bonus")
        pension = self._parse_fixed("pension", pct=True)
        price   = self._parse_fixed("price")
        overbid = self._parse_fixed("overbid", pct=True)
        fees    = self._parse_fixed("fees")
        term    = int(self._parse_fixed("term") or 25)
        boe     = self._parse_fixed("boe", pct=True)

        if self._deposit_mode.get() == "custom":
            dep_raw = self._deposit_custom_var.get()
            if dep_raw == "e.g. 20 000":
                dep_raw = ""
            dep_raw = dep_raw.replace(",", "").replace("£", "").replace(" ", "").strip()
            deposit_override = float(dep_raw) if dep_raw else 0.0
            deposit_category = None
        else:
            deposit_override = None
            deposit_category = self._deposit_cat_var.get() or "Deposit"

        income_items  = []
        for item in self._income_items:
            lbl, amt = self._read_dynamic_item(item)
            income_items.append((lbl, amt))
        extra_monthly = sum(amt for _, amt in income_items)

        expenses = {}
        for item in self._expense_items:
            lbl, amt = self._read_dynamic_item(item)
            if lbl:
                expenses[lbl] = amt

        r = db.mortgage_estimate(
            annual_income=income, bonus=bonus, pension_pct=pension,
            extra_monthly_income=extra_monthly,
            property_price=price, overbid_rate=overbid,
            fees=fees, boe_rate=boe, term_years=term, expenses=expenses,
            deposit_raw=deposit_override, deposit_category=deposit_category or "Deposit",
        )

        # Store state so what-if sliders can recompute without re-reading DB
        self._calc_state = {
            "r": r, "income": income, "bonus": bonus, "pension": pension,
            "boe": boe, "term": term, "extra_monthly": extra_monthly,
            "expenses": expenses, "income_items": income_items,
            "price": price, "overbid": overbid,
        }

        # Update slider range and reset to zero (suppress trace during reset)
        wi_max_dep = min(max(50_000, int(max(0, r["mortgage_amount"] - r["est_borrow_45x"])) + 50_000), 500_000)
        self._wi_updating = True
        self._wi_dep_scale.config(to=wi_max_dep)
        self._wi_dep_var.set(0)
        self._wi_sal_var.set(0)
        self._wi_dep_lbl.config(text="£0")
        self._wi_sal_lbl.config(text="£0")
        self._wi_updating = False

        self._render_results(r, term, pension, income_items)

    def _render_results(self, r, term, pension, income_items):
        for w in self._results.winfo_children():
            w.destroy()

        if self._results_fig is not None:
            try:
                plt.close(self._results_fig)
            except Exception:
                pass
            self._results_fig = None

        rf          = self._results
        surplus     = r["monthly_surplus"]
        surplus_c   = GREEN if surplus >= 0 else RED
        surplus_lbl = "Surplus" if surplus >= 0 else "Shortfall"

        def div(pady=(8, 0)):
            tk.Frame(rf, bg=BG3, height=1).pack(fill="x", pady=pady)

        def stat_card(parent, title, value, col, sub="", sub_col=None):
            f = tk.Frame(parent, bg=BG3, padx=12, pady=8)
            tk.Frame(f, bg=BG3, width=140, height=1).pack()
            tk.Label(f, text=title, bg=BG3, fg=SUBTEXT, font=STYLE["font"],
                     anchor="w").pack(fill="x")
            tk.Label(f, text=value, bg=BG3, fg=col,
                     font=("Segoe UI", 15, "bold"), anchor="w").pack(fill="x")
            tk.Label(f, text=sub, bg=BG3, fg=sub_col or SUBTEXT, font=STYLE["font"],
                     anchor="w").pack(fill="x")
            return f

        def brow(parent, label, val, col, bold=False):
            row = tk.Frame(parent, bg=BG)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=label, bg=BG, fg=SUBTEXT, font=STYLE["font"],
                     width=24, anchor="w").pack(side="left")
            tk.Label(row, text=val, bg=BG, fg=col,
                     font=STYLE["font_bold"] if bold else STYLE["font_mono"],
                     anchor="e").pack(side="left", padx=4)

        # ── Hero cards ────────────────────────────────────────────────────
        cards = tk.Frame(rf, bg=BG)
        cards.pack(fill="x", pady=(10, 6), padx=2)
        for col in range(3):
            cards.columnconfigure(col, weight=1, uniform="hero")

        monthly_saving = r["monthly_mortgage"] - r["next_ltv_monthly"]
        stat_card(cards, "Monthly Payment",       fmt_gbp(r["monthly_mortgage"]),
                  RED,   f"over {term} yrs  ·  {fmt_pct(r['interest_rate'])} rate"
                  ).grid(row=0, column=0, padx=4, pady=4, sticky="nsew")
        stat_card(cards, "LTV",                   fmt_pct(r["ltv"]),
                  YELLOW, f"mortgage {fmt_gbp(r['mortgage_amount'])}"
                  ).grid(row=0, column=1, padx=4, pady=4, sticky="nsew")
        stat_card(cards, surplus_lbl,             fmt_gbp(abs(surplus)),
                  surplus_c, "per month after all costs"
                  ).grid(row=0, column=2, padx=4, pady=4, sticky="nsew")
        stat_card(cards, "Net Monthly Income",    fmt_gbp(r["total_net_monthly"]),
                  GREEN,  f"net annual {fmt_gbp(r['net_annual'])}"
                  ).grid(row=1, column=0, padx=4, pady=4, sticky="nsew")
        stat_card(cards, "Deposit (after costs)", fmt_gbp(r["deposit_after"]),
                  ACCENT, f"{fmt_gbp(r['deposit_raw'])} available"
                  ).grid(row=1, column=1, padx=4, pady=4, sticky="nsew")
        stat_card(cards, "Est. Max Borrow",       fmt_gbp(r["est_borrow_45x"]),
                  ACCENT, "4.5× salary guideline"
                  ).grid(row=1, column=2, padx=4, pady=4, sticky="nsew")

        # ── Salary warning banner ─────────────────────────────────────────
        if r["salary_required"] is not None:
            req = r["salary_required"] / (1 - pension) if pension < 1 else r["salary_required"]
            warn = tk.Frame(rf, bg="#2d2010", padx=14, pady=8)
            warn.pack(fill="x", pady=(0, 4), padx=2)
            tk.Label(warn, text=f"⚠  To break even you'd need {fmt_gbp(req)} gross/yr",
                     bg="#2d2010", fg=YELLOW, font=STYLE["font_bold"]).pack(anchor="w")

        div()

        # ── Property & LTV bar ────────────────────────────────────────────
        section_label(rf, "Property  &  LTV").pack(anchor="w", pady=(8, 4))

        ltv_c = tk.Canvas(rf, bg=BG, height=70, highlightthickness=0)
        ltv_c.pack(fill="x", padx=2, pady=(0, 6))

        _C_DEP  = "#2d7a4f"
        _C_BORR = "#7a6500"
        _C_SHRT = "#8a2020"
        _C_OVER = "#1e6b68"
        _C_FEES = "#5a2d8a"

        def _draw_ltv(_=None):
            ltv_c.delete("all")
            w = ltv_c.winfo_width()
            if w < 20:
                return
            price = r["property_price"]
            if price <= 0:
                ltv_c.create_text(w // 2, 35, fill=SUBTEXT, font=STYLE["font"],
                                  text="Enter a property price to see the breakdown")
                return
            dep        = max(0.0, r["deposit_after"])
            mort       = max(0.0, r["mortgage_amount"])
            can_borrow = min(mort, r["est_borrow_45x"])
            shortfall  = max(0.0, mort - r["est_borrow_45x"])
            overbid    = r["overbid_amount"]
            fees_v     = r["fees"]
            total_cost = price + overbid + fees_v
            scale      = w / total_cost
            segs = [
                (dep,        _C_DEP,  "Deposit",    fmt_gbp(dep)),
                (can_borrow, _C_BORR, "Can borrow", fmt_gbp(can_borrow)),
                (shortfall,  _C_SHRT, "Shortfall",  fmt_gbp(shortfall)),
                (overbid,    _C_OVER, "Over-bid",   fmt_gbp(overbid)),
                (fees_v,     _C_FEES, "Fees",       fmt_gbp(fees_v)),
            ]
            BAR_Y1, BAR_Y2 = 14, 36
            x = 0
            seg_rects = []
            for i, (val, col, lbl, val_text) in enumerate(segs):
                px = int(val * scale) if i < len(segs) - 1 else w - x
                if px > 0:
                    ltv_c.create_rectangle(x, BAR_Y1, x + px, BAR_Y2, fill=col, outline="")
                seg_rects.append((x, x + px, col, lbl, val_text))
                x += px
            ltv_c.create_text(w, 2, anchor="ne", fill=FG, font=STYLE["font"],
                              text=f"Total cost  {fmt_gbp(total_cost)}")
            for x0, x1, col, lbl, val_text in seg_rects:
                seg_w = x1 - x0
                cx = (x0 + x1) // 2
                if seg_w >= 110:
                    ltv_c.create_text(cx, 44, anchor="center", fill=col,
                                      font=STYLE["font"], text=f"{lbl}  {val_text}")
                elif seg_w >= 52:
                    ltv_c.create_text(cx, 44, anchor="center", fill=col,
                                      font=STYLE["font"], text=val_text)
            x_leg = 0
            for _, col, lbl, _ in segs:
                ltv_c.create_rectangle(x_leg, 57, x_leg + 10, 66, fill=col, outline="")
                ltv_c.create_text(x_leg + 14, 61, anchor="w", fill=SUBTEXT,
                                  font=STYLE["font"], text=lbl)
                x_leg += 90

        ltv_c.bind("<Configure>", _draw_ltv)
        ltv_c.after(20, _draw_ltv)

        if r["additional_deposit"] > 0:
            nudge = tk.Frame(rf, bg=BG2, padx=12, pady=6)
            nudge.pack(fill="x", padx=2, pady=(0, 4))
            tk.Label(nudge, text="Next LTV band:", bg=BG2, fg=SUBTEXT,
                     font=STYLE["font"]).pack(side="left")
            tk.Label(nudge, text=f"  {r['next_ltv_label']}  ", bg=BG2, fg=YELLOW,
                     font=STYLE["font_bold"]).pack(side="left")
            tk.Label(nudge, text=f"add {fmt_gbp(r['additional_deposit'])} deposit  →  save ",
                     bg=BG2, fg=SUBTEXT, font=STYLE["font"]).pack(side="left")
            tk.Label(nudge, text=f"{fmt_gbp(monthly_saving)}/mo",
                     bg=BG2, fg=GREEN, font=STYLE["font_bold"]).pack(side="left")

        div()

        # ── Monthly Budget: donut + breakdown ─────────────────────────────
        section_label(rf, "Monthly Budget").pack(anchor="w", pady=(8, 4))
        budget_outer = tk.Frame(rf, bg=BG)
        budget_outer.pack(fill="x", padx=2)

        slices, colours_d = [], []
        slice_palette = ["#4a5568", "#5a6578", "#3a4558", "#6a7588",
                         "#2a3548", "#7a8598", "#525f72", "#404e62"]
        pal_i = 0
        for k, v in r["expenses"].items():
            if v > 0:
                slices.append((k, v))
                colours_d.append(slice_palette[pal_i % len(slice_palette)])
                pal_i += 1
        slices.append(("Mortgage", r["monthly_mortgage"]))
        colours_d.append(RED)
        if surplus > 0:
            slices.append((surplus_lbl, surplus))
            colours_d.append(GREEN)

        fig = Figure(figsize=(3.2, 3.2), facecolor=BG)
        self._results_fig = fig
        ax = fig.add_subplot(111, facecolor=BG)
        fig.subplots_adjust(0, 0, 1, 1)
        sizes = [s[1] for s in slices]
        if sum(sizes) > 0:
            ax.pie(sizes, colors=colours_d, startangle=90,
                   wedgeprops=dict(width=0.48, edgecolor=BG, linewidth=1.5))
        ax.text(0,  0.10, fmt_gbp(r["total_net_monthly"]),
                ha="center", va="center", fontsize=9, color=FG, fontweight="bold",
                fontfamily="monospace")
        ax.text(0, -0.18, "monthly in",
                ha="center", va="center", fontsize=7, color=SUBTEXT)
        ax.set_aspect("equal")
        cw = embed_figure(budget_outer, fig)
        cw.pack(side="left", padx=(0, 12))

        tbl = tk.Frame(budget_outer, bg=BG)
        tbl.pack(side="left", fill="both", expand=True, pady=4)
        brow(tbl, "Net income", fmt_gbp(r["total_net_monthly"]), GREEN, bold=True)
        for name, amt in income_items:
            if name and amt:
                brow(tbl, f"  + {name}", fmt_gbp(amt), ACCENT)
        tk.Frame(tbl, bg=BG3, height=1).pack(fill="x", pady=3)
        for k, v in r["expenses"].items():
            brow(tbl, f"  − {k}", fmt_gbp(v), SUBTEXT)
        brow(tbl, "  − Mortgage", fmt_gbp(r["monthly_mortgage"]), RED)
        tk.Frame(tbl, bg=BG3, height=1).pack(fill="x", pady=3)
        brow(tbl, surplus_lbl, fmt_gbp(abs(surplus)), surplus_c, bold=True)

        div(pady=(10, 0))

        # ── Income breakdown ──────────────────────────────────────────────
        section_label(rf, "Income Breakdown").pack(anchor="w", pady=(8, 4))
        brow(rf, "Gross (salary + bonus)", fmt_gbp(r["gross_taxable"]),    FG)
        brow(rf, "Net annual",             fmt_gbp(r["net_annual"]),       GREEN)
        brow(rf, "Net monthly salary",     fmt_gbp(r["net_monthly"]),      GREEN)
        for name, amt in income_items:
            if name and amt:
                brow(rf, f"  + {name}", fmt_gbp(amt) + "/mo", ACCENT)
        brow(rf, "Total net monthly",      fmt_gbp(r["total_net_monthly"]), GREEN, bold=True)

        div(pady=(10, 4))
        tk.Label(rf, text="⚠  Estimates only. Lenders assess affordability individually.",
                 bg=BG, fg=SUBTEXT, font=STYLE["font"], wraplength=480,
                 justify="left").pack(anchor="w", pady=(0, 8))


# ---------------------------------------------------------------------------
# Tab 7 — Raw recorded balances pivot
# ---------------------------------------------------------------------------

class EditBalanceDialog(tk.Toplevel):
    """Modal dialog for editing or deleting a single balance snapshot entry."""

    def __init__(self, parent, *, acc_name: str, date_str: str,
                 current_balance: float, on_done):
        super().__init__(parent)
        self.title("Edit Balance Entry")
        self.resizable(False, False)
        self.configure(bg=BG)
        self._on_done  = on_done
        self._acc_name = acc_name
        self._date_str = date_str   # raw stored date
        self._acc_id   = None
        for acc in getattr(parent, "_accounts", []):
            if acc["account_name"] == acc_name:
                self._acc_id = acc["id"]
                break

        pad = {"padx": 16, "pady": 6}

        tk.Label(self, text="Account", bg=BG, fg=SUBTEXT, font=STYLE["font"]).grid(
            row=0, column=0, sticky="e", **pad)
        tk.Label(self, text=acc_name, bg=BG, fg=FG, font=STYLE["font_bold"]).grid(
            row=0, column=1, sticky="w", **pad)

        tk.Label(self, text="Date", bg=BG, fg=SUBTEXT, font=STYLE["font"]).grid(
            row=1, column=0, sticky="e", **pad)
        tk.Label(self, text=format_date(date_str), bg=BG, fg=FG,
                 font=STYLE["font_bold"]).grid(row=1, column=1, sticky="w", **pad)

        tk.Label(self, text="Balance (£)", bg=BG, fg=SUBTEXT, font=STYLE["font"]).grid(
            row=2, column=0, sticky="e", **pad)
        self._bal_var = tk.StringVar(value=f"{current_balance:.2f}")
        bal_entry = ttk.Entry(self, textvariable=self._bal_var, width=18,
                              font=STYLE["font"])
        bal_entry.grid(row=2, column=1, sticky="w", **pad)
        bal_entry.selection_range(0, tk.END)
        bal_entry.focus_set()

        btn_frame = tk.Frame(self, bg=BG)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=(8, 16))
        styled_button(btn_frame, "Save", self._save, color=GREEN).pack(
            side="left", padx=6)
        styled_button(btn_frame, "Delete Entry", self._delete, color=RED).pack(
            side="left", padx=6)
        styled_button(btn_frame, "Cancel", self.destroy, color=BG3).pack(
            side="left", padx=6)

        self.transient(parent)
        self.grab_set()
        self.wait_visibility()
        self.update_idletasks()
        px = parent.winfo_rootx() + parent.winfo_width()  // 2 - self.winfo_width()  // 2
        py = parent.winfo_rooty() + parent.winfo_height() // 2 - self.winfo_height() // 2
        self.geometry(f"+{px}+{py}")

    def _save(self):
        if self._acc_id is None:
            messagebox.showerror("Error", "Account not found.", parent=self)
            return
        try:
            new_bal = float(
                self._bal_var.get().replace(",", "").replace("£", "").strip()
            )
        except ValueError:
            messagebox.showerror("Invalid input", "Please enter a valid number.", parent=self)
            return
        db.update_balance_entry(self._acc_id, self._date_str, new_bal)
        self.destroy()
        self._on_done()

    def _delete(self):
        if self._acc_id is None:
            messagebox.showerror("Error", "Account not found.", parent=self)
            return
        if not messagebox.askyesno(
            "Confirm Delete",
            f"Delete the balance entry for\n{self._acc_name}"
            f" on {format_date(self._date_str)}?",
            parent=self,
        ):
            return
        db.delete_snapshot_entry(self._acc_id, self._date_str)
        self.destroy()
        self._on_done()


class CalcedBalancesTab(tk.Frame):
    DATE_W = 110
    COL_W  = 110

    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._accounts       = []   # ordered list matching column positions
        self._raw_dates      = []   # stored date strings matching row positions
        self._sel_acc_id     = None
        self._sel_acc_name   = None
        self._sel_date       = None
        self._sel_balance    = None
        self._build()

    def _build(self):
        hdr = styled_frame(self)
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        styled_label(hdr, "Recorded Balances", font=STYLE["font_h1"]).pack(side="left")
        self._edit_btn = styled_button(hdr, "✎ Edit Selected", self._open_edit, color=YELLOW)
        self._edit_btn.pack(side="right")
        self._edit_btn.config(state="disabled")
        styled_button(hdr, "⟳ Refresh", self.refresh, color=GREEN).pack(side="right", padx=8)

        self._sel_label = tk.Label(self, text="Click a balance cell to select it",
                                   bg=BG, fg=SUBTEXT, font=STYLE["font"])
        self._sel_label.pack(fill="x", padx=24, pady=(0, 2))

        self._tree_frame = tk.Frame(self, bg=BG)
        self._tree_frame.pack(fill="both", expand=True, padx=20, pady=(2, 16))

        self.refresh()

    def _clear_selection(self):
        self._sel_acc_id   = None
        self._sel_acc_name = None
        self._sel_date     = None
        self._sel_balance  = None
        self._sel_label.config(text="Click a balance cell to select it", fg=SUBTEXT)
        self._edit_btn.config(state="disabled")

    def refresh(self):
        self._clear_selection()
        for w in self._tree_frame.winfo_children():
            w.destroy()

        accounts      = db.get_all_accounts(include_inactive=True)
        all_histories = db.get_all_balance_histories()

        if not accounts:
            styled_label(self._tree_frame, "No accounts found.", fg=SUBTEXT).pack(pady=20)
            return

        self._accounts = sorted(accounts, key=lambda a: (a["bank"] or "", a["account_name"]))

        self._raw_dates = sorted(
            {d for hist in all_histories.values() for d, _ in hist},
            reverse=True,
        )
        if not self._raw_dates:
            styled_label(self._tree_frame, "No snapshot data yet.", fg=SUBTEXT).pack(pady=20)
            return

        lookup = {
            acc_id: {d: b for d, b in hist}
            for acc_id, hist in all_histories.items()
        }

        dw, cw  = self.DATE_W, self.COL_W
        total_w = dw + cw * len(self._accounts)

        make_tree(self._tree_frame, [], height=1)
        date_col = "date"
        acc_cols = [f"a{acc['id']}" for acc in self._accounts]
        cols     = [date_col] + acc_cols

        tree = ttk.Treeview(self._tree_frame, columns=cols, show="headings",
                            style="Finance.Treeview", height=30)

        tree.heading(date_col, text="Date")
        tree.column(date_col, width=dw, anchor="w", stretch=False, minwidth=dw)
        for acc in self._accounts:
            cid    = f"a{acc['id']}"
            bank   = acc.get("bank") or ""
            name   = acc["account_name"]
            prefix = f"{bank} - "
            label  = name[len(prefix):] if bank and name.startswith(prefix) else name
            tree.heading(cid, text=label)
            tree.column(cid, width=cw, anchor="e", stretch=False, minwidth=cw)

        # Bank-name canvas row
        bank_h      = 22
        bank_canvas = tk.Canvas(self._tree_frame, bg=BG3, height=bank_h,
                                highlightthickness=0,
                                scrollregion=(0, 0, total_w, bank_h))
        bank_canvas.create_rectangle(0, 0, dw, bank_h, fill=BG3, outline=BG2, width=1)
        x = dw
        i = 0
        while i < len(self._accounts):
            bank = self._accounts[i].get("bank") or ""
            j = i
            while j < len(self._accounts) and (self._accounts[j].get("bank") or "") == bank:
                j += 1
            span = cw * (j - i)
            bank_canvas.create_rectangle(x, 0, x + span, bank_h,
                                         fill=BG3, outline=BG2, width=1)
            if bank:
                bank_canvas.create_text(x + span // 2, bank_h // 2, text=bank,
                                        fill=ACCENT, font=STYLE["font_bold"], anchor="center")
            x += span
            i  = j

        # Scrollbars
        v_sb = ttk.Scrollbar(self._tree_frame, orient="vertical",   command=tree.yview)
        h_sb = ttk.Scrollbar(self._tree_frame, orient="horizontal")

        def _xscroll(first, last):
            h_sb.set(first, last)
            bank_canvas.xview_moveto(first)

        tree.configure(yscrollcommand=v_sb.set, xscrollcommand=_xscroll)
        h_sb.configure(command=lambda *a: (tree.xview(*a), bank_canvas.xview(*a)))

        bank_canvas.grid(row=0, column=0, sticky="ew")
        tree.grid(row=1, column=0, sticky="nsew")
        v_sb.grid(row=1, column=1, sticky="ns")
        h_sb.grid(row=2, column=0, sticky="ew")
        self._tree_frame.grid_rowconfigure(1, weight=1)
        self._tree_frame.grid_columnconfigure(0, weight=1)

        # Populate rows — store raw date in iid for easy lookup
        for i, date_str in enumerate(self._raw_dates):
            values = [format_date(date_str)]
            for acc in self._accounts:
                bal = lookup.get(acc["id"], {}).get(date_str)
                values.append(fmt_gbp(bal) if bal is not None else "")
            tree.insert("", "end", iid=date_str, values=values,
                        tags=("odd" if i % 2 else "even",))

        tree.tag_configure("even", background=BG2)
        tree.tag_configure("odd",  background=BG)
        tree.tag_configure("selected_cell", background=BG3, foreground=ACCENT)

        # Cell click — identify which (date, account) was clicked
        def _on_click(event):
            region = tree.identify_region(event.x, event.y)
            if region != "cell":
                self._clear_selection()
                return
            row_iid = tree.identify_row(event.y)
            col_id  = tree.identify_column(event.x)
            if not row_iid:
                return
            col_idx = int(col_id.replace("#", "")) - 1   # 0 = date col, 1+ = accounts
            if col_idx == 0:
                self._clear_selection()
                return
            acc_idx = col_idx - 1
            if acc_idx >= len(self._accounts):
                return
            acc     = self._accounts[acc_idx]
            bal_str = tree.item(row_iid, "values")[col_idx]
            if not bal_str:
                self._clear_selection()
                self._sel_label.config(
                    text=f"No entry for {acc['account_name']} on {format_date(row_iid)}",
                    fg=SUBTEXT)
                return
            # Parse balance back from fmt_gbp output ("-£1,234.56")
            neg  = bal_str.startswith("-")
            val  = float(bal_str.replace("-", "").replace("£", "").replace(",", ""))
            self._sel_acc_id  = acc["id"]
            self._sel_acc_name = acc["account_name"]
            self._sel_date    = row_iid          # raw stored date string
            self._sel_balance = -val if neg else val
            self._sel_label.config(
                text=f"Selected:  {acc['account_name']}  ·  {format_date(row_iid)}  ·  {bal_str}",
                fg=FG)
            self._edit_btn.config(state="normal")

        tree.bind("<ButtonRelease-1>", _on_click)
        tree.bind("<Double-Button-1>", lambda e: (_on_click(e), self._open_edit()))

        def _scroll(e):
            tree.yview_scroll(-1 * (e.delta // 120), "units")
        tree.bind("<Enter>", lambda e: tree.bind_all("<MouseWheel>", _scroll))
        tree.bind("<Leave>", lambda e: tree.unbind_all("<MouseWheel>"))

    def _open_edit(self):
        if self._sel_acc_id is None:
            return
        EditBalanceDialog(
            self,
            acc_name=self._sel_acc_name,
            date_str=self._sel_date,
            current_balance=self._sel_balance,
            on_done=self.refresh,
        )


# ---------------------------------------------------------------------------
# Tab 8 — Settings
# ---------------------------------------------------------------------------

class SettingsTab(tk.Frame):
    _SETTINGS = [
        {
            "section": "Display",
            "items": [
                {
                    "key":     "date_format",
                    "label":   "Date display format",
                    "type":    "select",
                    "options": ["YYYY-MM-DD", "DD/MM/YYYY", "DD Mon YYYY", "MM/DD/YYYY"],
                    "default": "YYYY-MM-DD",
                },
            ],
        },
        {
            "section": "History chart defaults",
            "items": [
                {
                    "key":     "history_default_range",
                    "label":   "Default time range",
                    "type":    "select",
                    "options": ["ALL", "2Y", "1Y", "6M", "3M", "YTD"],
                    "default": "ALL",
                },
            ],
        },
    ]

    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._vars    = {}
        self._preview = {}
        self._build()

    def _build(self):
        hdr = styled_frame(self)
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        styled_label(hdr, "Settings", font=STYLE["font_h1"]).pack(side="left")
        styled_button(hdr, "Save", self._save, color=GREEN).pack(side="right")

        content = styled_frame(self)
        content.pack(fill="x", padx=20, pady=8)

        for group in self._SETTINGS:
            section_label(content, f"  {group['section']}").pack(fill="x", pady=(16, 4))

            for item in group["items"]:
                key     = item["key"]
                current = db.get_setting(key, item["default"])
                var     = tk.StringVar(value=current)
                self._vars[key] = var

                row = styled_frame(content)
                row.pack(fill="x", pady=5)

                tk.Label(row, text=item["label"], bg=BG, fg=FG,
                         font=STYLE["font"], width=26, anchor="w").pack(side="left")

                cb = ttk.Combobox(row, textvariable=var, values=item["options"],
                                  state="readonly", width=22, font=STYLE["font"])
                cb.pack(side="left", padx=(0, 16))

                if key == "date_format":
                    lbl = tk.Label(row, text="", bg=BG, fg=SUBTEXT,
                                   font=STYLE["font_mono"])
                    lbl.pack(side="left")
                    self._preview[key] = lbl
                    var.trace_add("write", lambda *_, k=key: self._update_preview(k))
                    self._update_preview(key)

        self._status = tk.Label(content, text="", bg=BG, fg=GREEN, font=STYLE["font"])
        self._status.pack(anchor="w", pady=(24, 0))

    def _update_preview(self, key):
        if key == "date_format":
            fmt = _DATE_FORMATS.get(self._vars[key].get(), "%Y-%m-%d")
            sample = datetime.date.today().strftime(fmt)
            self._preview[key].config(text=f"e.g. {sample}")

    def _save(self):
        for key, var in self._vars.items():
            db.set_setting(key, var.get())
        self._status.config(text="✓ Saved")
        self.after(2000, lambda: self._status.config(text=""))


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------

class DeleteSnapshotDialog(tk.Toplevel):
    """Two-panel dialog: date list on the left, entries for the selected date on the right."""

    def __init__(self, parent, on_done=None):
        super().__init__(parent, bg=BG)
        self.title("Delete Snapshot Records")
        self.geometry("720x480")
        self.resizable(True, True)
        self.grab_set()
        self._on_done = on_done
        self._build()

    def _build(self):
        # Header
        hdr = tk.Frame(self, bg=BG)
        hdr.pack(fill="x", padx=16, pady=(12, 6))
        tk.Label(hdr, text="Delete Snapshot Records", bg=BG, fg=FG,
                 font=STYLE["font_h2"]).pack(side="left")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        # ---- Left: date list ----
        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="y", padx=(0, 8))

        tk.Label(left, text="Snapshot dates", bg=BG, fg=ACCENT,
                 font=STYLE["font_bold"]).pack(anchor="w", pady=(0, 4))

        date_cols = ("date", "entries")
        self._date_tree, dsb = make_tree(left, date_cols, height=18)
        self._date_tree.heading("date",    text="Date / Time")
        self._date_tree.heading("entries", text="Entries")
        self._date_tree.column("date",    width=140)
        self._date_tree.column("entries", width=55, anchor="e")
        self._date_tree.pack(side="left", fill="y")
        dsb.pack(side="right", fill="y")
        self._date_tree.bind("<<TreeviewSelect>>", self._on_date_select)

        styled_button(left, "Delete entire date", self._delete_date,
                      color=RED).pack(fill="x", pady=(6, 0))

        # ---- Right: entries for selected date ----
        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        tk.Label(right, text="Entries for selected date", bg=BG, fg=ACCENT,
                 font=STYLE["font_bold"]).pack(anchor="w", pady=(0, 4))

        entry_cols = ("account", "balance")
        self._entry_tree, esb = make_tree(right, entry_cols, height=18)
        self._entry_tree.heading("account", text="Account")
        self._entry_tree.heading("balance", text="Balance")
        self._entry_tree.column("account", width=240)
        self._entry_tree.column("balance", width=120, anchor="e")
        self._entry_tree.pack(side="left", fill="both", expand=True)
        esb.pack(side="right", fill="y")

        styled_button(right, "Delete selected entries", self._delete_entries,
                      color=RED).pack(anchor="w", pady=(6, 0))

        # Footer
        styled_button(self, "Close", self.destroy,
                      color=SUBTEXT).pack(side="right", padx=16, pady=8)

        self._load_dates()

    def _load_dates(self):
        for row in self._date_tree.get_children():
            self._date_tree.delete(row)
        for date_str in db.get_snapshot_dates():
            entries = db.get_snapshot_with_names(date_str)
            self._date_tree.insert("", "end", iid=date_str,
                                   values=(date_str, len(entries)))

    def _on_date_select(self, _event=None):
        sel = self._date_tree.selection()
        if not sel:
            return
        date_str = sel[0]
        for row in self._entry_tree.get_children():
            self._entry_tree.delete(row)
        for r in db.get_snapshot_with_names(date_str):
            self._entry_tree.insert("", "end",
                                    iid=str(r["account_id"]),
                                    values=(r["account_name"], fmt_gbp(r["balance"])))

    def _delete_date(self):
        sel = self._date_tree.selection()
        if not sel:
            messagebox.showwarning("No selection", "Select a date first.", parent=self)
            return
        date_str = sel[0]
        if not messagebox.askyesno("Confirm",
                                   f"Delete ALL entries for {date_str}?\nThis cannot be undone.",
                                   parent=self):
            return
        db.delete_snapshot_date(date_str)
        for row in self._entry_tree.get_children():
            self._entry_tree.delete(row)
        self._load_dates()
        if self._on_done:
            self._on_done()

    def _delete_entries(self):
        date_sel = self._date_tree.selection()
        entry_sel = self._entry_tree.selection()
        if not date_sel:
            messagebox.showwarning("No date", "Select a date first.", parent=self)
            return
        if not entry_sel:
            messagebox.showwarning("No entries", "Select one or more entries to delete.", parent=self)
            return
        date_str = date_sel[0]
        n = len(entry_sel)
        if not messagebox.askyesno("Confirm",
                                   f"Delete {n} entr{'y' if n == 1 else 'ies'} from {date_str}?",
                                   parent=self):
            return
        for acc_id_str in entry_sel:
            db.delete_snapshot_entry(int(acc_id_str), date_str)
        self._on_date_select()   # refresh entry list
        self._load_dates()       # refresh counts
        if self._on_done:
            self._on_done()


class BaseDialog(tk.Toplevel):
    def __init__(self, parent, title):
        super().__init__(parent, bg=BG)
        self.title(title)
        self.resizable(False, False)
        self.grab_set()
        self._fields = {}

    def _field(self, parent, label, default="", width=24):
        row = styled_frame(parent)
        row.pack(fill="x", pady=3)
        styled_label(row, label, width=22, anchor="w").pack(side="left")
        var = tk.StringVar(value=default)
        styled_entry(row, width=width, textvariable=var).pack(side="left", padx=8)
        self._fields[label] = var
        return var

    def _val(self, label):
        return self._fields[label].get().strip()




# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Income tab
# ---------------------------------------------------------------------------

class IncomeTab(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._build()

    def _build(self):
        # Header
        hdr = styled_frame(self)
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        styled_label(hdr, "Income", font=STYLE["font_h1"]).pack(side="left")
        styled_button(hdr, "⟳ Refresh", self.refresh, color=GREEN).pack(side="right")

        self._chart_group = tk.StringVar(value="source")
        for val, label in (("source", "By Source"), ("subsource", "By Sub-source")):
            tk.Radiobutton(
                hdr, text=label, variable=self._chart_group, value=val,
                bg=BG, fg=FG, selectcolor=BG3, activebackground=BG,
                activeforeground=ACCENT, font=STYLE["font"],
                command=self._redraw_chart,
            ).pack(side="right", padx=4)

        self._sel_month  = None   # "YYYY-MM" when a bar is clicked, None = all
        self._month_list = []     # ordered list of months matching bar x-positions

        # Chart
        self.fig = Figure(figsize=(10, 3), facecolor=BG)
        self.ax  = self.fig.add_subplot(111, facecolor=BG)
        self.fig.subplots_adjust(left=0.07, right=0.98, top=0.88, bottom=0.15)
        self.canvas_widget = embed_figure(self, self.fig)
        self.canvas_widget.pack(fill="x", padx=20, pady=(0, 6))
        self.fig.canvas.mpl_connect("button_press_event", self._on_bar_click)

        # Month drill-down bar (hidden until a bar is clicked)
        self._drill_bar = tk.Frame(self, bg=BG2)
        self._drill_bar.pack(fill="x", padx=20, pady=(0, 4))
        self._drill_label = tk.Label(self._drill_bar, text="", bg=BG2, fg=ACCENT,
                                      font=STYLE["font_bold"])
        self._drill_label.pack(side="left", padx=(10, 12), pady=4)
        styled_button(self._drill_bar, "← All months", self._clear_drill,
                      color=SUBTEXT).pack(side="left")
        self._drill_bar.pack_forget()   # hidden initially

        # Entry form
        form = tk.Frame(self, bg=BG2)
        form.pack(fill="x", padx=20, pady=(4, 8))

        def _lbl(text):
            return tk.Label(form, text=text, bg=BG2, fg=SUBTEXT, font=STYLE["font"])

        def _ent(var, w=14):
            return tk.Entry(form, textvariable=var, bg=BG3, fg=FG,
                            insertbackground=FG, relief="flat",
                            font=STYLE["font"], width=w)

        # Date
        _lbl("Date:").pack(side="left", padx=(10, 3), pady=8)
        self._date_var = tk.StringVar()
        _dfmt = _DATE_FORMATS.get(db.get_setting("date_format", "YYYY-MM-DD"), "%Y-%m-%d")
        self._date_var.set(datetime.datetime.now().strftime(f"{_dfmt} %H:%M"))
        _ent(self._date_var, 16).pack(side="left", padx=(0, 10))

        # Amount
        _lbl("Amount £:").pack(side="left", padx=(0, 3))
        self._amount_var = tk.StringVar()
        _ent(self._amount_var, 10).pack(side="left", padx=(0, 10))

        # Source
        _lbl("Source:").pack(side="left", padx=(0, 3))
        self._source_var = tk.StringVar()
        self._source_combo = ttk.Combobox(form, textvariable=self._source_var,
                                           width=16, font=STYLE["font"], state="normal")
        self._source_combo["values"] = db.get_income_sources()
        self._source_combo.pack(side="left", padx=(0, 10))

        # Sub-source (dynamic — updates when source changes)
        _lbl("Sub-source:").pack(side="left", padx=(0, 3))
        self._cat_var = tk.StringVar()
        self._subsource_combo = ttk.Combobox(form, textvariable=self._cat_var,
                                              width=16, font=STYLE["font"], state="normal")
        self._subsource_combo["values"] = db.get_income_sub_sources()
        self._subsource_combo.pack(side="left", padx=(0, 10))

        def _on_source_change(*_):
            src = self._source_var.get().strip()
            self._subsource_combo["values"] = db.get_income_sub_sources(src or None)

        self._source_var.trace_add("write", _on_source_change)
        self._source_combo.bind("<<ComboboxSelected>>", _on_source_change)

        styled_button(form, "Save", self._save, color=GREEN).pack(side="left", padx=(0, 6))
        styled_button(form, "Clear", self._clear_form, color=BG3).pack(side="left")

        # Delete selected button (right-aligned)
        styled_button(form, "🗑 Delete selected", self._delete_selected,
                      color=RED).pack(side="right", padx=10)

        # Tree
        tree_frame = styled_frame(self)
        tree_frame.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        cols = ("date", "amount", "source", "subcategory")
        self.tree, sb = make_tree(tree_frame, cols, height=28)
        for col, hdr_text, w, anch in [
            ("date",        "Date",       140, "w"),
            ("amount",      "Amount",     110, "e"),
            ("source",      "Source",     160, "w"),
            ("subcategory", "Sub-source",  160, "w"),
        ]:
            self.tree.heading(col, text=hdr_text)
            self.tree.column(col, width=w, anchor=anch)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        def _scroll(e):
            self.tree.yview_scroll(-1 * (e.delta // 120), "units")
        self.tree.bind("<Enter>", lambda e: self.tree.bind_all("<MouseWheel>", _scroll))
        self.tree.bind("<Leave>", lambda e: self.tree.unbind_all("<MouseWheel>"))

        self.refresh()

    def _save(self):
        raw_date   = self._date_var.get().strip()
        raw_amount = self._amount_var.get().strip().replace("£", "").replace(",", "")
        source     = self._source_var.get().strip()
        cat        = self._cat_var.get().strip()

        # Parse date using configured format
        _dfmt = _DATE_FORMATS.get(db.get_setting("date_format", "YYYY-MM-DD"), "%Y-%m-%d")
        parsed_dt = None
        for _fmt in (f"{_dfmt} %H:%M", _dfmt, "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                parsed_dt = datetime.datetime.strptime(raw_date, _fmt)
                break
            except ValueError:
                pass
        if parsed_dt is None:
            messagebox.showerror("Invalid date",
                                 f"Could not parse date. Expected format: {_dfmt} HH:MM")
            return

        if not raw_amount:
            messagebox.showwarning("Validation", "Amount is required.")
            return
        try:
            amount = float(raw_amount)
        except ValueError:
            messagebox.showwarning("Validation", "Amount must be a number.")
            return

        date_str = parsed_dt.strftime("%Y-%m-%d %H:%M")
        db.add_income(date_str, amount, source or None, cat or None)

        # Refresh source/sub-source lists in case new values were typed
        self._source_combo["values"] = db.get_income_sources()
        self._subsource_combo["values"] = db.get_income_sub_sources(source or None)
        self._clear_form()
        self.refresh()

    def _clear_form(self):
        _dfmt = _DATE_FORMATS.get(db.get_setting("date_format", "YYYY-MM-DD"), "%Y-%m-%d")
        self._date_var.set(datetime.datetime.now().strftime(f"{_dfmt} %H:%M"))
        self._amount_var.set("")
        self._source_var.set("")
        self._cat_var.set("")

    def _delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("No selection", "Select one or more rows to delete.")
            return
        if not messagebox.askyesno("Confirm",
                                   f"Delete {len(sel)} income entr"
                                   f"{'y' if len(sel) == 1 else 'ies'}?"):
            return
        for iid in sel:
            db.delete_income(int(iid))
        self.refresh()

    def _on_bar_click(self, event):
        if event.inaxes != self.ax or not self._month_list:
            return
        idx = int(round(event.xdata)) if event.xdata is not None else -1
        if 0 <= idx < len(self._month_list):
            if self._month_list[idx] == self._sel_month:
                self._clear_drill()
                return
            self._sel_month = self._month_list[idx]
            try:
                display = datetime.datetime.strptime(
                    self._sel_month, "%Y-%m").strftime("%B %Y")
            except ValueError:
                display = self._sel_month
            self._drill_label.config(
                text=f"Showing: {display}  ·  click another bar or ← to show all")
            self._drill_bar.pack(fill="x", padx=20, pady=(0, 4))
            self._draw_chart(self._last_entries)
            self._populate_tree(self._last_entries)

    def _clear_drill(self):
        self._sel_month = None
        self._drill_bar.pack_forget()
        self._draw_chart(self._last_entries)
        self._populate_tree(self._last_entries)

    def _redraw_chart(self):
        if hasattr(self, "_last_entries"):
            self._draw_chart(self._last_entries)

    def _draw_chart(self, entries):
        self._last_entries = entries
        self.ax.clear()
        self.ax.set_facecolor(BG)
        self.fig.patch.set_facecolor(BG)

        if not entries:
            self.ax.set_visible(False)
            self.fig.canvas.draw()
            return
        self.ax.set_visible(True)

        by_sub = self._chart_group.get() == "subsource"

        # Group by month (YYYY-MM) × chosen grouping
        from collections import defaultdict
        monthly: dict = defaultdict(lambda: defaultdict(float))
        for e in entries:
            month = e["entry_date"][:7]   # "YYYY-MM"
            if by_sub:
                label = e["subcategory"] or e["source"] or "Other"
            else:
                label = e["source"] or "Other"
            monthly[month][label] += e["amount"]

        months  = sorted(monthly.keys())
        self._month_list = months
        labels  = sorted({lbl for m in monthly.values() for lbl in m})

        x      = range(len(months))
        bottom = [0.0] * len(months)

        _palette = [ACCENT, GREEN, YELLOW, MAUVE, TEAL, PINK, RED]
        for i, lbl in enumerate(labels):
            vals   = [monthly[m].get(lbl, 0.0) for m in months]
            colour = _palette[i % len(_palette)]
            alphas = [1.0 if (self._sel_month is None or m == self._sel_month) else 0.25
                      for m in months]
            for j, (v, b, a) in enumerate(zip(vals, bottom, alphas)):
                self.ax.bar(j, v, bottom=b, color=colour,
                            alpha=a, width=0.6,
                            label=lbl if j == 0 else "_nolegend_")
            bottom = [b + v for b, v in zip(bottom, vals)]

        # X axis — show month labels
        month_labels = []
        for m in months:
            try:
                month_labels.append(
                    datetime.datetime.strptime(m, "%Y-%m").strftime("%b %Y"))
            except ValueError:
                month_labels.append(m)

        self.ax.set_xticks(list(x))
        self.ax.set_xticklabels(month_labels, rotation=30, ha="right",
                                color=SUBTEXT, fontsize=8)
        self.ax.tick_params(axis="y", colors=SUBTEXT, labelsize=8)
        self.ax.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda v, _: f"£{v:,.0f}"))
        self.ax.spines[:].set_visible(False)
        group_label = "sub-source" if by_sub else "source"
        self.ax.set_title(f"Income by month · grouped by {group_label}",
                          color=FG, fontsize=9, pad=6)

        if labels:
            self.ax.legend(fontsize=7, facecolor=BG2, labelcolor=FG,
                           framealpha=0.8, loc="upper left")

        self.fig.canvas.draw()

    def _populate_tree(self, entries):
        visible = [e for e in entries
                   if self._sel_month is None or e["entry_date"][:7] == self._sel_month]
        for row in self.tree.get_children():
            self.tree.delete(row)
        for i, entry in enumerate(visible):
            self.tree.insert("", "end", iid=str(entry["id"]),
                             values=(
                                 format_date(entry["entry_date"]),
                                 fmt_gbp(entry["amount"]),
                                 entry["source"] or "—",
                                 entry["subcategory"] or "—",
                             ),
                             tags=("even" if i % 2 == 0 else "odd",))
        self.tree.tag_configure("even", background=BG2)
        self.tree.tag_configure("odd",  background=BG)

    def refresh(self):
        entries = db.get_all_income()
        self._draw_chart(entries)
        self._populate_tree(entries)


# ---------------------------------------------------------------------------
# Main app window
# ---------------------------------------------------------------------------

class FinanceApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Personal Finance Tracker")
        self.geometry("1200x780")
        self.minsize(900, 600)
        self.configure(bg=BG)

        db.init_db()

        self._build_nav()
        self._build_tabs()
        self._show_tab("dashboard")

    def _build_nav(self):
        nav = tk.Frame(self, bg=BG2, width=160)
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)

        tk.Label(nav, text="💷 Finance", bg=BG2, fg=ACCENT,
                 font=("Segoe UI", 13, "bold"), pady=20).pack(fill="x")

        self._nav_buttons = {}
        tabs = [
            ("dashboard",  "📊  Dashboard"),
            ("snapshot",   "📝  Log Snapshot"),
            ("history",    "📈  History"),
            ("categories", "🗂   Categories"),
            ("income",     "💷  Income"),
            ("interest",   "💰  Interest"),
            ("mortgage",   "🏠  Mortgage"),
            ("calced",     "🗃   Rec. Balances"),
            ("settings",   "⚙   Settings"),
        ]
        for key, label in tabs:
            btn = tk.Button(nav, text=label, bg=BG2, fg=FG, activebackground=BG3,
                            activeforeground=ACCENT, relief="flat", anchor="w",
                            font=STYLE["font"], padx=16, pady=10, cursor="hand2",
                            command=lambda k=key: self._show_tab(k))
            btn.pack(fill="x")
            self._nav_buttons[key] = btn

        tk.Frame(nav, bg=BG2).pack(fill="both", expand=True)
        tk.Label(nav, text="v1.0", bg=BG2, fg=SUBTEXT, font=STYLE["font"]).pack(pady=8)

    def _build_tabs(self):
        self.container = tk.Frame(self, bg=BG)
        self.container.pack(side="right", fill="both", expand=True)
        self._tabs = {
            "dashboard":  DashboardTab(self.container),
            "snapshot":   SnapshotTab(self.container),
            "history":    HistoryTab(self.container),
            "categories": CategoriesTab(self.container,
                                         on_change=self._on_categories_changed),
            "income":     IncomeTab(self.container),
            "interest":   InterestTab(self.container),
            "mortgage":   MortgageTab(self.container),
            "calced":     CalcedBalancesTab(self.container),
            "settings":   SettingsTab(self.container),
        }

    def _on_categories_changed(self):
        self._tabs["dashboard"].rebuild()
        self._tabs["snapshot"].rebuild()
        self._tabs["mortgage"].refresh_categories()

    def _show_tab(self, key):
        for k, tab in self._tabs.items():
            tab.pack_forget()
            self._nav_buttons[k].config(bg=BG2, fg=FG)

        self._tabs[key].pack(fill="both", expand=True)
        self._nav_buttons[key].config(bg=BG3, fg=ACCENT)

        # Auto-refresh lightweight tabs on switch; heavy chart tabs refresh on demand
        refresh_fn = getattr(self._tabs[key], "refresh", None)
        if refresh_fn and key in ("dashboard", "interest"):
            refresh_fn()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = FinanceApp()
    app.mainloop()
