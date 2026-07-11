"""
app.py — Personal Finance Tracker
Tkinter + Matplotlib UI over SQLite backend.

Tabs:
  1. Dashboard      — current balances, totals, interest summary
  2. Snapshot       — log a new balance snapshot for all accounts
  3. History        — charts of account / category history over time
  4. Categories     — spending allocation breakdown over time
  5. Interest       — current interest summary + forward projection
  6. Mortgage       — affordability estimator
  7. Accounts       — add / edit accounts, manage rates & allocations
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
        self._build()

    def _build(self):
        # Header row
        hdr = styled_frame(self)
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        styled_label(hdr, "Dashboard", font=STYLE["font_h1"]).pack(side="left")
        styled_button(hdr, "⟳ Refresh", self.refresh, color=GREEN).pack(side="right")

        # Summary cards row
        self.cards_frame = styled_frame(self)
        self.cards_frame.pack(fill="x", padx=20, pady=8)

        # Treeview — current balances
        section_label(self, "  Current Balances").pack(fill="x", padx=20, pady=(8, 2))
        tree_frame = styled_frame(self)
        tree_frame.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        cols = ("bank", "account", "category", "balance", "rate", "yearly_int", "daily_int")
        self.tree, sb = make_tree(tree_frame, cols, height=18)
        headers = ("Bank", "Account", "Category", "Balance", "Rate", "Yearly Int", "Daily Int")
        widths   = (120, 220, 130, 110, 70, 110, 90)
        for col, hdr_text, w in zip(cols, headers, widths):
            self.tree.heading(col, text=hdr_text)
            self.tree.column(col, width=w, anchor="e" if col in ("balance","rate","yearly_int","daily_int") else "w")

        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.refresh()

    def _make_card(self, parent, label, value, colour):
        f = tk.Frame(parent, bg=BG3, padx=16, pady=12)
        tk.Label(f, text=label, bg=BG3, fg=SUBTEXT, font=STYLE["font"]).pack(anchor="w")
        tk.Label(f, text=value, bg=BG3, fg=colour,
                 font=("Segoe UI", 18, "bold")).pack(anchor="w")
        return f

    def refresh(self):
        # Clear cards
        for w in self.cards_frame.winfo_children():
            w.destroy()

        summary = db.get_current_interest_summary()
        date_str, snapshot = db.get_latest_snapshot()

        total_balance = sum(r["balance"] for r in summary)
        total_interest = sum(r["yearly_interest"] for r in summary)
        total_debt = sum(r["balance"] for r in summary if r["balance"] < 0)
        net = total_balance - abs(total_debt) if total_debt else total_balance

        cards = [
            ("Total Assets", fmt_gbp(total_balance), GREEN),
            ("Total Debt",   fmt_gbp(abs(total_debt)), RED),
            ("Net Worth",    fmt_gbp(net), ACCENT),
            ("Yearly Interest", fmt_gbp(total_interest), YELLOW),
            ("Last Snapshot", date_str or "None", SUBTEXT),
        ]
        for label, val, colour in cards:
            c = self._make_card(self.cards_frame, label, val, colour)
            c.pack(side="left", padx=(0, 12), pady=4)

        # Populate tree
        for row in self.tree.get_children():
            self.tree.delete(row)

        for r in summary:
            colour_tag = "pos" if r["balance"] >= 0 else "neg"
            self.tree.insert("", "end", values=(
                r["bank"] or "",
                r["account_name"],
                r["category"] or "",
                fmt_gbp(r["balance"]),
                fmt_pct(r["rate"]),
                fmt_gbp(r["yearly_interest"]),
                f"£{r['daily_interest']:.4f}",
            ), tags=(colour_tag,))

        self.tree.tag_configure("pos", foreground=FG)
        self.tree.tag_configure("neg", foreground=RED)


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
        self.date_var = tk.StringVar(
            value=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
        styled_entry(date_row, width=18, textvariable=self.date_var).pack(side="left", padx=8)
        styled_label(date_row,
                     "(YYYY-MM-DD HH:MM)  ·  Category cells: £500 = fixed, 60% = remainder",
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
        self._bal_vars  = {}
        self._rate_vars = {}
        self._cat_vars  = {}

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

            # New balance entry
            bal_var = tk.StringVar(value=f"") #{prev_bal:.2f}" if prev_bal is not None else
            styled_entry(self.inner, width=13, textvariable=bal_var
                         ).grid(row=grid_row, column=col, padx=1, pady=1)
            self._bal_vars[acc_id] = bal_var
            col += 1

            # Current rate (read-only)
            tk.Label(self.inner,
                     text=f"{cur_rate*100:.4f}%" if cur_rate else "—",
                     bg=row_bg, fg=SUBTEXT, font=STYLE["font_mono"],
                     width=9, anchor="e"
                     ).grid(row=grid_row, column=col, padx=1, sticky="ew")
            col += 1

            # New rate entry (blank = no change)
            rate_var = tk.StringVar()
            styled_entry(self.inner, width=10, textvariable=rate_var
                         ).grid(row=grid_row, column=col, padx=1, pady=1)
            self._rate_vars[acc_id] = rate_var
            col += 1

            # Category cells — pre-filled with current allocation
            self._cat_vars[acc_id] = {}
            for cat in self.CATS:
                current = allocs.get(cat, {"fixed": 0.0, "pct": 0.0})
                if current["fixed"]:
                    default = f"£{current['fixed']:.2f}"
                elif current["pct"]:
                    default = f"{current['pct']*100:.4f}%"
                else:
                    default = ""
                var = tk.StringVar(value=default)
                styled_entry(self.inner, width=11, textvariable=var
                             ).grid(row=grid_row, column=col, padx=1, pady=1)
                self._cat_vars[acc_id][cat] = var
                col += 1

    def _load_previous(self):
        self._populate()

    def _open_delete_dialog(self):
        DeleteSnapshotDialog(self, on_done=self._populate)

    def _reset(self):
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
        date_str = self.date_var.get().strip()
        for _fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                datetime.datetime.strptime(date_str, _fmt)
                break
            except ValueError:
                pass
        else:
            messagebox.showerror("Error", "Invalid date. Use YYYY-MM-DD or YYYY-MM-DD HH:MM.")
            return

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


# ---------------------------------------------------------------------------
# Tab 3 — History charts
# ---------------------------------------------------------------------------

class HistoryTab(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._build()

    def _build(self):
        hdr = styled_frame(self)
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        styled_label(hdr, "Balance History", font=STYLE["font_h1"]).pack(side="left")
        styled_button(hdr, "⟳ Refresh", self.refresh, color=GREEN).pack(side="right")

        ctrl = styled_frame(self)
        ctrl.pack(fill="x", padx=20, pady=4)

        styled_label(ctrl, "View:").pack(side="left")
        self.mode = tk.StringVar(value="Net Worth")
        for opt in ["Net Worth", "By Account", "By Category"]:
            tk.Radiobutton(ctrl, text=opt, variable=self.mode, value=opt,
                           bg=BG, fg=FG, selectcolor=BG3, activebackground=BG,
                           font=STYLE["font"], command=self.refresh).pack(side="left", padx=8)

        self.fig = Figure(figsize=(10, 5), facecolor=BG)
        self.ax  = self.fig.add_subplot(111, facecolor=BG2)
        self.canvas_widget = embed_figure(self, self.fig)
        self.canvas_widget.pack(fill="both", expand=True, padx=20, pady=(4, 16))

        self.refresh()

    def refresh(self):
        self.ax.clear()
        self.ax.set_facecolor(BG2)
        self.fig.patch.set_facecolor(BG)
        for spine in self.ax.spines.values():
            spine.set_edgecolor(BG3)
        self.ax.tick_params(colors=SUBTEXT)
        self.ax.xaxis.label.set_color(SUBTEXT)
        self.ax.yaxis.label.set_color(SUBTEXT)
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
        self.ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        self.fig.autofmt_xdate()

        mode = self.mode.get()

        if mode == "Net Worth":
            self._plot_net_worth()
        elif mode == "By Account":
            self._plot_by_account()
        else:
            self._plot_by_category()

        self.ax.yaxis.set_major_formatter(
            matplotlib.ticker.FuncFormatter(lambda x, _: f"£{x:,.0f}"))
        self.ax.legend(facecolor=BG3, edgecolor=BG3, labelcolor=FG,
                       fontsize=8, loc="upper left")
        self.fig.canvas.draw()

    def _dates_to_mpl(self, dates):
        import matplotlib.dates as mdates
        result = []
        for d in dates:
            for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    result.append(mdates.date2num(datetime.datetime.strptime(d, fmt)))
                    break
                except ValueError:
                    pass
        return result

    def _plot_net_worth(self):
        history = db.get_net_worth_history()
        if not history:
            return
        dates, totals = zip(*history)
        x = self._dates_to_mpl(dates)
        self.ax.plot(x, totals, color=ACCENT, linewidth=2, label="Net Worth")
        self.ax.fill_between(x, totals, alpha=0.15, color=ACCENT)
        self.ax.set_title("Net Worth Over Time", color=FG, pad=10)

    def _plot_by_account(self):
        accounts = db.get_all_accounts()
        dates = db.get_snapshot_dates()[::-1]
        if not dates:
            return
        all_histories = db.get_all_balance_histories()
        colours = plt.cm.tab20.colors
        x = self._dates_to_mpl(dates)
        for i, acc in enumerate(accounts):
            history = dict(all_histories.get(acc["id"], []))
            ys = [history.get(d, 0.0) for d in dates]
            if any(y != 0 for y in ys):
                self.ax.plot(x, ys, label=acc["account_name"],
                             color=colours[i % len(colours)], linewidth=1.5)
        self.ax.set_title("Balance by Account", color=FG, pad=10)

    def _plot_by_category(self):
        history = db.get_category_history()
        if not history:
            return
        cats = list(history[0]["totals"].keys())
        x = self._dates_to_mpl([h["date"] for h in history])
        bottoms = [0.0] * len(history)
        for cat in cats:
            ys = [h["totals"].get(cat, 0.0) for h in history]
            colour = CAT_COLOURS.get(cat, SUBTEXT)
            self.ax.fill_between(x, bottoms, [b + y for b, y in zip(bottoms, ys)],
                                  alpha=0.7, color=colour, label=cat)
            self.ax.plot(x, [b + y for b, y in zip(bottoms, ys)],
                         color=colour, linewidth=0.5)
            bottoms = [b + y for b, y in zip(bottoms, ys)]
        self.ax.set_title("Balance by Spending Category", color=FG, pad=10)


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
                self.tree.insert("", "end", values=(cat, fmt_gbp(val), f"{pct:.1f}%"))
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
                f"£{r['daily_interest']:.4f}",
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
# Tab 7 — Accounts management
# ---------------------------------------------------------------------------

class AccountsTab(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._selected_id = None
        self._build()

    def _build(self):
        # ---- header row ----
        hdr = styled_frame(self)
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        styled_label(hdr, "Accounts", font=STYLE["font_h1"]).pack(side="left")
        styled_button(hdr, "⊗ Deactivate", self._deactivate, color=RED).pack(side="right")
        styled_button(hdr, "⟳ Refresh", self.refresh, color=ACCENT).pack(side="right", padx=8)
        styled_button(hdr, "+ Add Account", self._add_account, color=GREEN).pack(side="right", padx=8)

        # ---- selected-account edit bar ----
        edit_bar = tk.Frame(self, bg=BG2)
        edit_bar.pack(fill="x", padx=20, pady=(0, 6))

        self._sel_label = tk.Label(edit_bar, text="Select an account to edit its type",
                                   bg=BG2, fg=SUBTEXT, font=STYLE["font"],
                                   width=32, anchor="w")
        self._sel_label.pack(side="left", padx=(12, 8), pady=6)

        tk.Frame(edit_bar, bg=BG3, width=1).pack(side="left", fill="y", pady=4)

        tk.Label(edit_bar, text="Account type:", bg=BG2, fg=FG,
                 font=STYLE["font"]).pack(side="left", padx=(12, 4))

        self._pt_var = tk.StringVar()
        self._pt_combo = ttk.Combobox(edit_bar, textvariable=self._pt_var, width=22,
                                       font=STYLE["font"], state="normal")
        self._pt_combo["values"] = db.get_product_types()
        self._pt_combo.pack(side="left", padx=(0, 6))

        styled_button(edit_bar, "+ New type", self._add_type_inline,
                      color=YELLOW).pack(side="left", padx=(0, 4))
        styled_button(edit_bar, "Save type", self._save_type,
                      color=GREEN).pack(side="left")

        tk.Label(edit_bar, text="Rates & allocations → Log Snapshot",
                 bg=BG2, fg=SUBTEXT, font=STYLE["font"]).pack(side="right", padx=12)

        # ---- full-width tree ----
        tree_frame = styled_frame(self)
        tree_frame.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        cols = ("name", "product_type", "rate", "balance")
        self.tree, sb = make_tree(tree_frame, cols, height=30)
        for col, hdr_text, w, anch in [
            ("name",         "Account Name",  260, "w"),
            ("product_type", "Account Type",  160, "w"),
            ("rate",         "Rate %",         90, "e"),
            ("balance",      "Balance",        120, "e"),
        ]:
            self.tree.heading(col, text=hdr_text)
            self.tree.column(col, width=w, anchor=anch)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        self.refresh()

    def refresh(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        _, snapshot = db.get_latest_snapshot()
        today = datetime.date.today().isoformat()
        rates = db._get_rates_on_date(today)
        for acc in db.get_all_accounts():
            acc_id = acc["id"]
            rate   = rates.get(acc_id, 0.0)
            self.tree.insert("", "end", iid=str(acc_id), values=(
                acc["account_name"],
                acc.get("product_type") or "—",
                f"{rate * 100:.4f}%" if rate else "—",
                fmt_gbp(snapshot.get(acc_id)),
            ))

    def _on_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        self._selected_id = int(sel[0])
        acc = db.get_account_by_id(self._selected_id)
        self._sel_label.config(text=acc["account_name"], fg=FG)
        self._pt_var.set(acc.get("product_type") or "")

    def _add_type_inline(self):
        name = simpledialog.askstring("New Account Type",
                                      "Enter new account type name:",
                                      parent=self)
        if name and name.strip():
            db.add_product_type(name.strip())
            self._pt_combo["values"] = db.get_product_types()
            self._pt_var.set(name.strip())

    def _save_type(self):
        if not self._selected_id:
            messagebox.showwarning("No selection", "Select an account first.")
            return
        ptype = self._pt_var.get().strip()
        # Persist a brand-new type if the user typed one that's not in the list
        if ptype and ptype not in db.get_product_types():
            db.add_product_type(ptype)
            self._pt_combo["values"] = db.get_product_types()
        db.update_account_product_type(self._selected_id, ptype or None)
        self.refresh()
        # Re-select the same row so the edit bar stays populated
        self.tree.selection_set(str(self._selected_id))

    def _deactivate(self):
        if not self._selected_id:
            messagebox.showwarning("No selection", "Select an account first.")
            return
        acc = db.get_account_by_id(self._selected_id)
        if messagebox.askyesno("Confirm", f"Deactivate '{acc['account_name']}'?\n"
                               "It will no longer appear in snapshots but history is kept."):
            db.deactivate_account(self._selected_id)
            self._selected_id = None
            self._sel_label.config(text="Select an account to edit its type", fg=SUBTEXT)
            self._pt_var.set("")
            self.refresh()

    def _add_account(self):
        AddAccountDialog(self, self.refresh)


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
            ("interest",   "💰  Interest"),
            ("mortgage",   "🏠  Mortgage"),
            ("accounts",   "⚙   Accounts"),
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
            "interest":   InterestTab(self.container),
            "mortgage":   MortgageTab(self.container),
            "accounts":   AccountsTab(self.container),
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
