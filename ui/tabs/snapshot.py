"""
ui/tabs/snapshot.py — SnapshotTab: log balance snapshots.
"""
import datetime
import tkinter as tk
from tkinter import ttk, messagebox

import db
from ui.constants import *
from ui.helpers import (
    fmt_gbp, format_date, _DATE_FORMATS,
    styled_frame, styled_label, styled_entry, styled_button,
)
from ui.dialogs.delete_snapshot import DeleteSnapshotDialog
from ui.tabs.income import IncomeTab


class SnapshotTab(tk.Frame):
    """Single scrollable table — account rows × (balance, rate, one column per category).
    Category cells: type £500 for a fixed amount, 60% for remainder share."""

    _CAT_SHORT = {"Spending": "Spending", "Deposit": "Deposit",
                  "Emergency Fund": "Emerg. Fund", "Long Term Savings": "LT Savings",
                  "Pension": "Pension"}

    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._bal_vars   = {}
        self._rate_vars  = {}
        self._cat_vars   = {}
        self._accounts   = []
        self._cur_allocs = {}
        self._build()

    def _build(self):
        hdr = styled_frame(self)
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        styled_label(hdr, "Log Balance Snapshot", font=STYLE["font_h1"]).pack(side="left")
        styled_button(hdr, "Save Snapshot", self._save, color=GREEN).pack(side="right")
        styled_button(hdr, "Delete Records", self._open_delete_dialog, color=RED).pack(side="right", padx=8)

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

        # One scrollable page: snapshot grid on top, income section stacked below.
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True, padx=20, pady=(0, 12))

        self._canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        self._v_sb = ttk.Scrollbar(outer, orient="vertical",   command=self._canvas.yview)
        self._h_sb = ttk.Scrollbar(outer, orient="horizontal", command=self._canvas.xview)
        self._canvas.configure(yscrollcommand=self._on_yscroll,
                               xscrollcommand=self._on_xscroll)

        # self._page holds everything and is what actually scrolls
        self._page = tk.Frame(self._canvas, bg=BG)
        self._canvas.create_window((0, 0), window=self._page, anchor="nw")
        self._page.bind("<Configure>", lambda e: self._canvas.configure(
            scrollregion=self._canvas.bbox("all")))

        self._canvas.grid(row=0, column=0, sticky="nsew")
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_columnconfigure(0, weight=1)

        # Snapshot accounts grid
        self.inner = tk.Frame(self._page, bg=BG)
        self.inner.pack(fill="x", anchor="nw")
        self._populate()

        # Divider + income section directly beneath
        tk.Frame(self._page, bg=BG3, height=1).pack(fill="x", pady=(12, 0))
        self._income = IncomeTab(self._page)
        self._income.pack(fill="both", expand=True)

        def _scroll(e):
            top, bot = self._canvas.yview()
            if top > 0.0 or bot < 1.0:
                self._canvas.yview_scroll(-1 * (e.delta // 120), "units")
        self._canvas.bind("<Enter>", lambda e: self._canvas.bind_all("<MouseWheel>", _scroll))
        self._canvas.bind("<Leave>", lambda e: self._canvas.unbind_all("<MouseWheel>"))

    # ---- Dynamic scrollbars (auto-hide when content fits) ----

    def _on_yscroll(self, first, last):
        self._v_sb.set(first, last)
        if float(first) <= 0.0 and float(last) >= 1.0:
            self._v_sb.grid_remove()
        else:
            self._v_sb.grid(row=0, column=1, sticky="ns")

    def _on_xscroll(self, first, last):
        self._h_sb.set(first, last)
        if float(first) <= 0.0 and float(last) >= 1.0:
            self._h_sb.grid_remove()
        else:
            self._h_sb.grid(row=1, column=0, sticky="ew")

    def rebuild(self):
        self._populate()

    def refresh(self):
        """Auto-called on tab focus — reloads accounts, prev balances and rates."""
        _dfmt = _DATE_FORMATS.get(db.get_setting("date_format", "YYYY-MM-DD"), "%Y-%m-%d")
        self.date_var.set(datetime.datetime.now().strftime(f"{_dfmt} %H:%M"))
        self._populate()
        if hasattr(self, "_income"):
            self._income.refresh()

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
        prev           = db.get_latest_balance_per_account()
        now_str        = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        cur_rates      = db._get_rates_on_date(now_str)
        self._cur_allocs = {acc["id"]: db.get_allocations_on_date(acc["id"], now_str)
                            for acc in self._accounts}

        fixed_cols = [
            ("Account",      22, "w"),
            ("Prev Balance", 13, "e"),
            ("New Balance",  13, "w"),
            ("Cur Rate %",    9, "e"),
            ("New Rate %",   10, "w"),
        ]
        n_fixed  = len(fixed_cols)
        all_cols = fixed_cols + [(h, 11, "w") for h in self.CAT_HDRS]

        for c, (text, w, anchor) in enumerate(all_cols):
            bg = BG3 if c >= n_fixed else BG
            tk.Label(self.inner, text=text, bg=bg, fg=ACCENT,
                     font=STYLE["font_bold"], width=w, anchor=anchor, pady=3
                     ).grid(row=0, column=c, padx=1, pady=(0, 1), sticky="ew")

        for c in range(n_fixed, len(all_cols)):
            tk.Label(self.inner, text="£ or %", bg=BG3, fg=SUBTEXT,
                     font=("Segoe UI", 8), width=11, anchor="center"
                     ).grid(row=1, column=c, padx=1, pady=(0, 3), sticky="ew")

        sorted_accounts = sorted(self._accounts,
                                 key=lambda a: (a["bank"] or "", a["account_name"]))

        _SNAP_BANK_BG = [
            "#1a2030",
            "#1a2a1e",
            "#2a221a",
            "#251a2a",
            "#1a2828",
            "#2a1a1e",
            "#1e1a2a",
            "#22261a",
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

            _bank_key = (acc.get("bank") or "").strip()
            row_bg = _snap_bank_bg.get(_bank_key, BG if grid_row % 2 == 0 else BG2)

            tk.Label(self.inner, text=acc["account_name"], bg=row_bg, fg=FG,
                     font=STYLE["font"], width=22, anchor="w"
                     ).grid(row=grid_row, column=col, padx=1, pady=0, sticky="ew")
            col += 1

            tk.Label(self.inner,
                     text=fmt_gbp(prev_bal) if prev_bal is not None else "—",
                     bg=row_bg, fg=SUBTEXT, font=STYLE["font_mono"],
                     width=13, anchor="e"
                     ).grid(row=grid_row, column=col, padx=1, sticky="ew")
            col += 1

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

            def _norm_bal(e, v=bal_var):
                raw = v.get().strip().replace("£", "").replace(",", "")
                if not raw:
                    return
                try:
                    v.set(f"£{float(raw):,.2f}")
                except ValueError:
                    v.set("")
            bal_entry.bind("<FocusOut>", _norm_bal)
            col += 1

            tk.Label(self.inner,
                     text=f"{cur_rate*100:.2f}%" if cur_rate else "—",
                     bg=row_bg, fg=SUBTEXT, font=STYLE["font_mono"],
                     width=9, anchor="e"
                     ).grid(row=grid_row, column=col, padx=1, sticky="ew")
            col += 1

            rate_var   = tk.StringVar()
            rate_entry = styled_entry(self.inner, width=10, textvariable=rate_var)
            rate_entry.grid(row=grid_row, column=col, padx=1, pady=1)
            self._rate_vars[acc_id]  = rate_var
            self._rate_entries.append(rate_entry)

            def _norm_rate(e, v=rate_var):
                raw = v.get().strip().replace("%", "")
                if not raw:
                    return
                try:
                    v.set(f"{float(raw):.2f}%")
                except ValueError:
                    v.set("")
            rate_entry.bind("<FocusOut>", _norm_rate)
            col += 1

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

                def _norm_cat(e, v=var):
                    raw = v.get().strip()
                    if not raw:
                        return
                    if "%" in raw:
                        try:
                            v.set(f"{float(raw.replace('%', '').strip()):.2f}%")
                        except ValueError:
                            v.set("")
                    else:
                        try:
                            v.set(f"£{float(raw.replace('£', '').replace(',', '').strip()):,.2f}")
                        except ValueError:
                            v.set("")
                cat_entry.bind("<FocusOut>", _norm_cat)
                col += 1

        self._setup_tab_order()

    def _setup_tab_order(self):
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

    def _open_delete_dialog(self):
        DeleteSnapshotDialog(self, on_done=self._populate)

    def _parse_cat_cell(self, raw: str):
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
        parsed    = {}
        any_filled = False
        for cat, var in self._cat_vars[acc_id].items():
            result = self._parse_cat_cell(var.get())
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

        balances = {}
        for acc_id, var in self._bal_vars.items():
            raw = var.get().strip().replace("£", "").replace(",", "")
            if not raw:
                continue
            try:
                balances[acc_id] = float(raw)
            except ValueError:
                messagebox.showerror("Error", f"Invalid balance: '{raw}'")
                return

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
                continue

            total_pct = sum(v["pct"] for v in alloc_data.values())
            if total_pct > 0 and abs(total_pct - 1.0) > 0.001:
                messagebox.showerror("Error",
                    f"'{acc_name}': remainder % must sum to 100 "
                    f"(got {total_pct * 100:.2f}%).")
                return

            if self._alloc_changed(acc_id, alloc_data):
                new_allocs[acc_id] = alloc_data

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
        self.refresh()
