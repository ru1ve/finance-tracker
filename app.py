"""
app.py — Personal Finance Tracker
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
        # Header
        hdr = styled_frame(self)
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        styled_label(hdr, "Dashboard", font=STYLE["font_h1"]).pack(side="left")
        self._toggle_btn = styled_button(hdr, "⊗ Deactivate", self._deactivate, color=RED)
        self._toggle_btn.pack(side="right")
        styled_button(hdr, "⟳ Refresh", self.refresh, color=GREEN).pack(side="right", padx=8)
        styled_button(hdr, "+ Add Account", self._add_account, color=GREEN).pack(side="right", padx=8)

        # Summary cards (main row)
        self.cards_frame = styled_frame(self)
        self.cards_frame.pack(fill="x", padx=20, pady=(4, 2))

        # Category allocation cards (second row)
        self.cat_cards_frame = styled_frame(self)
        self.cat_cards_frame.pack(fill="x", padx=20, pady=(0, 6))

        # Edit bar — single row
        edit_bar = tk.Frame(self, bg=BG2)
        edit_bar.pack(fill="x", padx=20, pady=(0, 6))

        def _lbl(text):
            return tk.Label(edit_bar, text=text, bg=BG2, fg=SUBTEXT, font=STYLE["font"])

        def _ent(var, w):
            return tk.Entry(edit_bar, textvariable=var, bg=BG3, fg=FG,
                            insertbackground=FG, relief="flat",
                            font=STYLE["font"], width=w)

        self._sel_label = tk.Label(edit_bar, text="Select an account to edit",
                                   bg=BG2, fg=SUBTEXT, font=STYLE["font"],
                                   width=20, anchor="w")
        self._sel_label.pack(side="left", padx=(10, 6), pady=6)

        tk.Frame(edit_bar, bg=BG3, width=1).pack(side="left", fill="y", pady=4)

        _lbl("Bank:").pack(side="left", padx=(8, 3))
        self._bank_var = tk.StringVar()
        _ent(self._bank_var, 12).pack(side="left", padx=(0, 8))

        _lbl("Label:").pack(side="left", padx=(0, 3))
        self._actype_var = tk.StringVar()
        _ent(self._actype_var, 12).pack(side="left", padx=(0, 8))

        _lbl("Type:").pack(side="left", padx=(0, 3))
        self._pt_var = tk.StringVar()
        self._pt_combo = ttk.Combobox(edit_bar, textvariable=self._pt_var, width=14,
                                       font=STYLE["font"], state="normal")
        self._pt_combo["values"] = db.get_product_types()
        self._pt_combo.pack(side="left", padx=(0, 8))

        _lbl("Rate Max £:").pack(side="left", padx=(0, 3))
        self._maxbal_var = tk.StringVar()
        _ent(self._maxbal_var, 10).pack(side="left", padx=(0, 8))

        styled_button(edit_bar, "Save", self._save_edits, color=GREEN).pack(side="left")

        tk.Label(edit_bar, text="Rates & allocations → Log Snapshot",
                 bg=BG2, fg=SUBTEXT, font=STYLE["font"]).pack(side="right", padx=12)

        # Tree
        section_label(self, "  Current Balances").pack(fill="x", padx=20, pady=(4, 2))
        tree_frame = styled_frame(self)
        tree_frame.pack(fill="both", expand=True, padx=20, pady=(0, 16))

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

        for acc in active:
            self._insert_row(acc, snapshot, rates, last_dates, allocs, yearly_int, tag="active")

        if inactive:
            n_cols = 8 + len(self._spend_cats)
            self.tree.insert("", "end", iid="__sep__",
                             values=("── Deactivated ──",) + ("",) * (n_cols - 1),
                             tags=("sep",))
            self.tree.tag_configure("sep", foreground=SUBTEXT)
            for acc in inactive:
                self._insert_row(acc, snapshot, rates, last_dates, allocs, yearly_int,
                                 tag="inactive")

        if sel and self.tree.exists(str(sel)):
            self.tree.selection_set(str(sel))

    def _insert_row(self, acc, snapshot, rates, last_dates, allocs, yearly_int, tag):
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
        ) + cat_vals, tags=(tag,))

    def _on_select(self, event):
        sel = self.tree.selection()
        if not sel or sel[0] == "__sep__":
            return
        self._selected_id = int(sel[0])
        acc = db.get_account_by_id(self._selected_id)
        self._selected_active = bool(acc["is_active"])
        self._sel_label.config(text="Editing:", fg=ACCENT)
        self._bank_var.set(acc.get("bank") or "")
        self._actype_var.set(acc.get("account_type") or "")
        self._pt_var.set(acc.get("product_type") or "")
        mb = acc.get("max_balance_for_rate")
        try:
            mb = float(mb) if mb not in (None, "", "None") else None
        except (TypeError, ValueError):
            mb = None
        self._maxbal_var.set(f"{mb:.2f}" if mb is not None else "")
        if self._selected_active:
            self._toggle_btn.config(text="⊗ Deactivate", fg=RED, command=self._deactivate)
        else:
            self._toggle_btn.config(text="↺ Reactivate", fg=GREEN, command=self._reactivate)

    def _add_type_inline(self):
        name = simpledialog.askstring("New Account Type",
                                      "Enter new account type name:", parent=self)
        if name and name.strip():
            db.add_product_type(name.strip())
            self._pt_combo["values"] = db.get_product_types()
            self._pt_var.set(name.strip())

    def _save_edits(self):
        if not self._selected_id:
            messagebox.showwarning("No selection", "Select an account first.")
            return
        bank   = self._bank_var.get().strip()
        label  = self._actype_var.get().strip()
        ptype  = self._pt_var.get().strip()
        mb_raw = self._maxbal_var.get().strip().replace("£", "").replace(",", "")

        if not bank and not label:
            messagebox.showwarning("Validation", "Bank or label cannot both be blank.")
            return
        name = f"{bank} - {label}" if bank and label else (bank or label)
        try:
            max_bal = float(mb_raw) if mb_raw else None
        except ValueError:
            messagebox.showwarning("Validation", "Rate Max £ must be a number.")
            return

        if ptype and ptype not in db.get_product_types():
            db.add_product_type(ptype)
            self._pt_combo["values"] = db.get_product_types()

        try:
            db.update_account_details(self._selected_id, bank or None, label or None,
                                      name, ptype or None, max_bal)
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            return
        self.refresh()

    def _deactivate(self):
        if not self._selected_id:
            messagebox.showwarning("No selection", "Select an account first.")
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
        self._sel_label.config(text="Select an account to edit", fg=SUBTEXT)
        self._bank_var.set("")
        self._actype_var.set("")
        self._pt_var.set("")
        self._maxbal_var.set("")
        self._toggle_btn.config(text="⊗ Deactivate", fg=RED, command=self._deactivate)

    def _add_account(self):
        AddAccountDialog(self, self.refresh)


# ---------------------------------------------------------------------------
# Tab 2 — Snapshot entry
# ---------------------------------------------------------------------------

class SnapshotTab(tk.Frame):
    """Single scrollable table — account rows × (balance, rate, one column per category).
    Category cells: type £500 for a fixed amount, 60% for remainder share."""

    CATS     = ["Spending", "Deposit", "Emergency Fund", "Long Term Savings", "Pension"]
    CAT_HDRS = ["Spending", "Deposit", "Emerg. Fund", "LT Savings", "Pension"]

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
        styled_button(hdr, "Reset", self._reset, color=SUBTEXT).pack(side="right", padx=8)
        styled_button(hdr, "Load Previous", self._load_previous, color=YELLOW).pack(side="right", padx=8)

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

    def _populate(self):
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

        for grid_row, acc in enumerate(sorted_accounts, start=2):
            acc_id   = acc["id"]
            prev_bal = prev.get(acc_id)
            cur_rate = cur_rates.get(acc_id, 0.0)
            allocs   = self._cur_allocs.get(acc_id, {})
            col      = 0

            # Alternate row shading for readability
            row_bg = BG if grid_row % 2 == 0 else BG2

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
    CATS = ["Spending", "Deposit", "Emergency Fund", "Long Term Savings", "Pension"]

    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._time_range = db.get_setting("history_default_range", "ALL")
        self._drilldown  = None   # None = full view; str = single category drill-down
        self._hover_x    = []     # matplotlib date numbers for each data point
        self._hover_data = []     # [{"date": str, "values": {name: float}}, ...]
        self._cids       = []     # matplotlib event connection IDs
        self._build()

    def _build(self):
        hdr = styled_frame(self)
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        styled_label(hdr, "Balance History", font=STYLE["font_h1"]).pack(side="left")
        styled_button(hdr, "⟳ Refresh", self.refresh, color=GREEN).pack(side="right")

        # Mode row — back button lives here and is shown only during drill-down
        ctrl = styled_frame(self)
        ctrl.pack(fill="x", padx=20, pady=(4, 2))
        styled_label(ctrl, "View:").pack(side="left")
        self.mode = tk.StringVar(value=db.get_setting("history_default_view", "By Category"))
        for opt in ("By Account", "By Category"):
            tk.Radiobutton(ctrl, text=opt, variable=self.mode, value=opt,
                           bg=BG, fg=FG, selectcolor=BG3, activebackground=BG,
                           font=STYLE["font"],
                           command=self._on_mode_change).pack(side="left", padx=8)
        self._back_btn = styled_button(ctrl, "← All categories",
                                       self._clear_drilldown, color=SUBTEXT)
        # packed/unpacked dynamically by _sync_back_btn

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
        self.refresh()

    # ---- State changes ----

    def _on_mode_change(self):
        self._drilldown = None
        self._sync_back_btn()
        self.refresh()

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
        if self._drilldown and self.mode.get() == "By Category":
            self._back_btn.pack(side="left", padx=(16, 0))
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

        # Capture the already-drawn background (annotation is invisible so not included)
        self._bg = self.fig.canvas.copy_from_bbox(self.fig.bbox)

        leg = self.ax.get_legend()
        if leg:
            for text in leg.get_texts():
                text.set_picker(5)
            for handle in leg.legend_handles:
                if handle is not None:
                    handle.set_picker(5)

        self._cids.append(
            self.fig.canvas.mpl_connect("pick_event", self._on_pick))
        self._cids.append(
            self.fig.canvas.mpl_connect("motion_notify_event", self._on_hover))

    def _on_pick(self, event):
        if self.mode.get() != "By Category" or self._drilldown:
            return
        leg = self.ax.get_legend()
        if not leg:
            return
        for text, handle in zip(leg.get_texts(), leg.legend_handles):
            if event.artist in (text, handle):
                cat_name = text.get_text()
                if cat_name in self.CATS:
                    self._set_drilldown(cat_name)
                return

    def _on_hover(self, event):
        if not hasattr(self, "_annot") or not self._hover_x or self._bg is None:
            return

        def _blit_hide():
            self._annot.set_visible(False)
            self.fig.canvas.restore_region(self._bg)
            self.fig.canvas.blit(self.fig.bbox)

        if event.inaxes != self.ax or event.xdata is None:
            if self._annot.get_visible():
                _blit_hide()
            return

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
        self._hover_x    = []
        self._hover_data = []
        self.ax.clear()
        self.ax.set_facecolor(BG2)
        self.fig.patch.set_facecolor(BG)
        for spine in self.ax.spines.values():
            spine.set_edgecolor(BG3)
        self.ax.tick_params(colors=SUBTEXT)
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
        self.ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        self.fig.autofmt_xdate()

        if self.mode.get() == "By Account":
            self._plot_by_account()
        elif self._drilldown:
            self._plot_category_drilldown(self._drilldown)
        else:
            self._plot_by_category()

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

    def _plot_by_account(self):
        accounts = db.get_all_accounts(include_inactive=True)
        if not accounts:
            return
        all_histories = db.get_all_balance_histories()
        active_ids = {acc["id"] for acc in accounts if acc["is_active"]}

        active_dates = sorted({
            d for acc_id, hist in all_histories.items()
            if acc_id in active_ids for d, _ in hist
        })
        active_dates = self._trim(active_dates, date_fn=lambda d: d)
        if not active_dates:
            return

        colours    = plt.cm.tab20.colors
        x          = self._dates_to_mpl(active_dates)
        hover_vals = [{} for _ in active_dates]

        for i, acc in enumerate(accounts):
            hist = all_histories.get(acc["id"], [])
            if not hist:
                continue
            hd = {d: b for d, b in hist}
            if acc["is_active"]:
                last, ys = None, []
                for j, d in enumerate(active_dates):
                    if d in hd:
                        last = hd[d]
                    val = last if last is not None else 0.0
                    ys.append(val)
                    if val:
                        hover_vals[j][acc["account_name"]] = val
            else:
                ys = [hd.get(d, 0.0) for d in active_dates]
                for j, val in enumerate(ys):
                    if val:
                        hover_vals[j][acc["account_name"]] = val

            if any(y != 0 for y in ys):
                self.ax.plot(x, ys, label=acc["account_name"],
                             color=colours[i % len(colours)], linewidth=1.5)

        self._hover_x    = list(x)
        self._hover_data = [{"date": d, "values": hv}
                            for d, hv in zip(active_dates, hover_vals)]
        self.ax.set_title("Balance by Account", color=FG, pad=10)

    def _plot_by_category(self):
        history = self._trim(db.get_category_history(),
                             date_fn=lambda h: h["date"])
        if not history:
            return
        cats    = list(history[0]["totals"].keys())
        x       = self._dates_to_mpl([h["date"] for h in history])
        ys_mat  = [[h["totals"].get(cat, 0.0) for h in history] for cat in cats]
        colours = [CAT_COLOURS.get(cat, SUBTEXT) for cat in cats]
        self._signed_stackplot(x, cats, ys_mat, colours)
        self._hover_x    = list(x)
        self._hover_data = [{"date": h["date"], "values": dict(h["totals"])}
                            for h in history]
        self.ax.set_title(
            "Balance by Spending Category  ·  click a legend entry to drill down",
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
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._build()

    def _build(self):
        hdr = styled_frame(self)
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        styled_label(hdr, "Category Breakdown", font=STYLE["font_h1"]).pack(side="left")
        styled_button(hdr, "⟳ Refresh", self.refresh, color=GREEN).pack(side="right")

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
        tree_frame = styled_frame(self)
        tree_frame.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        cols = ("account", "balance", "rate", "yearly", "daily", "projected", "gain")
        self.tree, sb = make_tree(tree_frame, cols, height=20)
        for col, hdr_text, w in [
            ("account", "Account", 220), ("balance", "Balance", 120),
            ("rate", "Rate", 70), ("yearly", "Yearly Int", 110),
            ("daily", "Daily Int", 90), ("projected", "Projected", 120), ("gain", "Gain", 110),
        ]:
            self.tree.heading(col, text=hdr_text)
            self.tree.column(col, width=w, anchor="e" if col != "account" else "w")

        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

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

DEFAULT_EXPENSES = {
    "Food + Essentials":  350.0,
    "Fun":                500.0,
    "Utility":             80.0,
    "Wifi":                25.0,
    "Holidays":           250.0,
    "Savings":            250.0,
    "Home Insurance":      25.0,
    "Transport + Car":    150.0,
    "Council Tax Band C": 200.0,
    "AI":                  20.0,
    "Monzo Max":           17.0,
    "Climbing Gym":        39.0,
    "Emergency Fund":     200.0,
}

class MortgageTab(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._expense_vars = {}
        self._build()

    def _build(self):
        hdr = styled_frame(self)
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        styled_label(hdr, "Mortgage Calculator", font=STYLE["font_h1"]).pack(side="left")
        styled_button(hdr, "⟳ Calculate", self._calc, color=GREEN).pack(side="right")

        # Two-column layout: inputs left, results right
        body = styled_frame(self)
        body.pack(fill="both", expand=True, padx=20, pady=(0, 12))

        # ---- LEFT: inputs ----
        left = styled_frame(body)
        left.pack(side="left", fill="y", padx=(0, 16))

        section_label(left, "Income").pack(anchor="w", pady=(4, 2))
        self._inputs = {}
        income_fields = [
            ("Annual salary (£):",       "income",    "32500"),
            ("Annual bonus (£):",         "bonus",     "605"),
            ("Pension contribution (%):", "pension",   "6"),
            ("Lodger income (£/mo):",     "lodger",    "525"),
        ]
        for label, key, default in income_fields:
            self._input_row(left, label, key, default)

        section_label(left, "Property").pack(anchor="w", pady=(10, 2))
        property_fields = [
            ("Property price (£):",       "price",     "200000"),
            ("Over-bid rate (%):",         "overbid",   "5"),
            ("Fees & moving costs (£):",   "fees",      "5000"),
            ("Mortgage term (years):",     "term",      "20"),
            ("BoE base rate (%):",         "boe",       "3.75"),
        ]
        for label, key, default in property_fields:
            self._input_row(left, label, key, default)

        section_label(left, "Monthly Expenses").pack(anchor="w", pady=(10, 2))
        for name, default in DEFAULT_EXPENSES.items():
            row = styled_frame(left)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=name + ":", bg=BG, fg=FG, font=STYLE["font"],
                     width=24, anchor="w").pack(side="left")
            var = tk.StringVar(value=str(default))
            styled_entry(row, width=8, textvariable=var).pack(side="left", padx=4)
            self._expense_vars[name] = var

        # ---- RIGHT: results (scrollable) ----
        right_outer = styled_frame(body)
        right_outer.pack(side="left", fill="both", expand=True)

        canvas = tk.Canvas(right_outer, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(right_outer, orient="vertical", command=canvas.yview)
        self._results = styled_frame(canvas)
        self._results.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self._results, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-1*(e.delta//120), "units"))

        self._calc()

    def _input_row(self, parent, label, key, default):
        row = styled_frame(parent)
        row.pack(fill="x", pady=1)
        tk.Label(row, text=label, bg=BG, fg=FG, font=STYLE["font"],
                 width=24, anchor="w").pack(side="left")
        var = tk.StringVar(value=default)
        styled_entry(row, width=10, textvariable=var).pack(side="left", padx=4)
        self._inputs[key] = var

    def _flt(self, key, pct=False):
        val = float(self._inputs[key].get().replace(",","").replace("£","").replace("%",""))
        return val / 100 if pct else val

    def _calc(self):
        for w in self._results.winfo_children():
            w.destroy()

        try:
            income  = self._flt("income")
            bonus   = self._flt("bonus")
            pension = self._flt("pension", pct=True)
            lodger  = self._flt("lodger")
            price   = self._flt("price")
            overbid = self._flt("overbid", pct=True)
            fees    = self._flt("fees")
            term    = int(self._flt("term"))
            boe     = self._flt("boe", pct=True)
            expenses = {k: float(v.get() or 0) for k, v in self._expense_vars.items()}
        except ValueError:
            messagebox.showerror("Error", "Invalid input — check all fields are numbers.")
            return

        r = db.mortgage_estimate(
            annual_income=income, bonus=bonus, pension_pct=pension,
            lodger_monthly=lodger, property_price=price, overbid_rate=overbid,
            fees=fees, boe_rate=boe, term_years=term, expenses=expenses,
        )

        rf = self._results

        # ---- Income summary ----
        section_label(rf, "Income").pack(anchor="w", pady=(8, 4))
        income_rows = [
            ("Gross taxable income",  fmt_gbp(r["gross_taxable"]),      FG),
            ("Net annual salary",     fmt_gbp(r["net_annual"]),         GREEN),
            ("Net monthly salary",    fmt_gbp(r["net_monthly"]),        GREEN),
            ("Lodger income",         fmt_gbp(r["lodger_monthly"]) + "/mo", ACCENT),
            ("Total net monthly",     fmt_gbp(r["total_net_monthly"]),  ACCENT),
        ]
        self._result_table(rf, income_rows)

        # ---- Deposit ----
        section_label(rf, "Deposit").pack(anchor="w", pady=(12, 4))
        dep_rows = [
            ("Available deposit (from accounts)", fmt_gbp(r["deposit_raw"]),    FG),
            ("Over-bid amount",                   fmt_gbp(-r["overbid_amount"]), RED),
            ("Fees & moving costs",               fmt_gbp(-r["fees"]),           RED),
            ("Deposit after costs",               fmt_gbp(r["deposit_after"]),   GREEN),
        ]
        self._result_table(rf, dep_rows)

        # ---- Mortgage ----
        section_label(rf, "Mortgage").pack(anchor="w", pady=(12, 4))
        surplus_colour = GREEN if r["monthly_surplus"] >= 0 else RED
        surplus_label  = "Monthly surplus" if r["monthly_surplus"] >= 0 else "Monthly shortfall"
        mort_rows = [
            ("Property price",      fmt_gbp(r["property_price"]),   FG),
            ("Mortgage amount",     fmt_gbp(r["mortgage_amount"]),  FG),
            ("LTV",                 fmt_pct(r["ltv"]),              YELLOW),
            ("Interest rate",       fmt_pct(r["interest_rate"]),    YELLOW),
            ("Monthly repayment",   fmt_gbp(r["monthly_mortgage"]), RED),
            ("Est. borrow (4.5x salary)", fmt_gbp(r["est_borrow_45x"]), ACCENT),
            ("Remaining vs. est.",  fmt_gbp(r["remaining_vs_est"]),
             RED if r["remaining_vs_est"] > 0 else GREEN),
            (surplus_label,         fmt_gbp(abs(r["monthly_surplus"])), surplus_colour),
        ]
        self._result_table(rf, mort_rows)

        if r["salary_required"] is not None:
            req = r["salary_required"] / (1 - pension)  # back to gross
            tk.Label(rf, text=f"  ⚠  Salary needed to break even: {fmt_gbp(req)} gross/yr",
                     bg=BG, fg=YELLOW, font=STYLE["font_bold"]).pack(anchor="w", pady=2)

        # ---- Next LTV band ----
        section_label(rf, "Next LTV Band").pack(anchor="w", pady=(12, 4))
        ltv_rows = [
            ("Next band target",         r["next_ltv_label"],                    FG),
            ("Additional deposit needed", fmt_gbp(r["additional_deposit"]),      ACCENT),
            ("Rate at next band",         fmt_pct(r["next_ltv_rate"]),           YELLOW),
            ("Monthly saving vs now",
             fmt_gbp(r["monthly_mortgage"] - r["next_ltv_monthly"]),             GREEN),
        ]
        self._result_table(rf, ltv_rows)

        # ---- Monthly budget breakdown ----
        section_label(rf, "Monthly Budget").pack(anchor="w", pady=(12, 4))
        budget_rows = [("Net income + lodger", fmt_gbp(r["total_net_monthly"]), GREEN)]
        budget_rows += [(f"  {k}", fmt_gbp(-v), RED) for k, v in r["expenses"].items()]
        budget_rows += [("  Mortgage",         fmt_gbp(-r["monthly_mortgage"]), RED)]
        budget_rows += [(surplus_label,        fmt_gbp(abs(r["monthly_surplus"])), surplus_colour)]
        self._result_table(rf, budget_rows)

        tk.Label(rf, text="⚠  Estimates only. Lenders assess affordability individually.",
                 bg=BG, fg=SUBTEXT, font=STYLE["font"], wraplength=500,
                 justify="left").pack(anchor="w", pady=(12, 4))

    def _result_table(self, parent, rows):
        """Render a list of (label, value, colour) rows as a compact table."""
        for label, value, colour in rows:
            row = styled_frame(parent)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=label, bg=BG, fg=SUBTEXT, font=STYLE["font"],
                     width=30, anchor="w").pack(side="left")
            tk.Label(row, text=value, bg=BG, fg=colour,
                     font=STYLE["font_mono"], anchor="e").pack(side="left", padx=8)


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
                    "key":     "history_default_view",
                    "label":   "Default view",
                    "type":    "select",
                    "options": ["By Category", "By Account"],
                    "default": "By Category",
                },
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


class AddAccountDialog(BaseDialog):
    def __init__(self, parent, on_done):
        super().__init__(parent, "Add Account")
        self._on_done = on_done
        self._build()

    def _build(self):
        f = styled_frame(self)
        f.pack(padx=24, pady=16)

        styled_label(f, 'Name is auto-generated as  "Bank - Account label"',
                     fg=SUBTEXT).pack(pady=(0, 10), anchor="w")

        # Bank
        self._field(f, "Bank:")

        # Account label (used in name, e.g. "Current", "Flex Saver")
        self._field(f, "Account label:")

        # Live name preview
        self._preview = styled_label(f, "", fg=ACCENT, font=STYLE["font_bold"])
        self._preview.pack(pady=(4, 10), anchor="w")
        for key in ("Bank:", "Account label:"):
            self._fields[key].trace_add("write", lambda *_: self._update_preview())

        # Account product type (configurable list)
        tk.Frame(f, bg=BG, height=1).pack(fill="x", pady=(0, 8))
        styled_label(f, "Account type  (Cash, LISA, S&S ISA, etc.):").pack(anchor="w", pady=(0, 4))

        type_row = styled_frame(f)
        type_row.pack(fill="x", pady=(0, 4))
        self._pt_var = tk.StringVar()
        self._pt_combo = ttk.Combobox(type_row, textvariable=self._pt_var, width=22,
                                       font=STYLE["font"], state="normal")
        self._pt_combo["values"] = db.get_product_types()
        self._pt_combo.pack(side="left")
        styled_button(type_row, "+ New type", self._add_product_type,
                      color=YELLOW).pack(side="left", padx=(8, 0))

        styled_button(f, "Add Account", self._save, color=GREEN).pack(pady=(16, 4), anchor="e")

    def _update_preview(self):
        bank  = self._fields["Bank:"].get().strip()
        label = self._fields["Account label:"].get().strip()
        name  = f"{bank} - {label}" if bank and label else (bank or label)
        self._preview.config(text=f"→  {name}" if name else "")

    def _add_product_type(self):
        name = simpledialog.askstring("New Account Type",
                                      "Enter new account type name:",
                                      parent=self)
        if name and name.strip():
            db.add_product_type(name.strip())
            self._pt_combo["values"] = db.get_product_types()
            self._pt_var.set(name.strip())

    def _save(self):
        bank  = self._val("Bank:").strip()
        label = self._val("Account label:").strip()
        ptype = self._pt_var.get().strip()
        if not bank:
            messagebox.showerror("Error", "Bank is required.")
            return
        if not label:
            messagebox.showerror("Error", "Account label is required.")
            return
        account_name = f"{bank} - {label}"
        # If user typed a brand-new product type, persist it
        if ptype and ptype not in db.get_product_types():
            db.add_product_type(ptype)
        db.upsert_account(
            account_name=account_name,
            bank=bank,
            account_type=label,
            category=None,
            max_balance_for_rate=None,
            interest_rate=0.0,
            allocations={},
            effective_from=datetime.date.today().isoformat(),
            note=None,
            product_type=ptype or None,
        )
        self._on_done()
        self.destroy()


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
            "categories": CategoriesTab(self.container),
            "income":     IncomeTab(self.container),
            "interest":   InterestTab(self.container),
            "mortgage":   MortgageTab(self.container),
            "calced":     CalcedBalancesTab(self.container),
            "settings":   SettingsTab(self.container),
        }

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
