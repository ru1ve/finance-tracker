"""
ui/tabs/dashboard.py — DashboardTab: balances, totals, account management,
and spending category management (add / remove categories).
"""
import datetime
import tkinter as tk
from tkinter import ttk, messagebox

import db
from ui.constants import *
from ui.helpers import (
    fmt_gbp, fmt_pct, format_date,
    styled_frame, styled_label, styled_entry, styled_button, section_label,
    add_tooltip, make_tree,
)


class DashboardTab(tk.Frame):
    def __init__(self, parent, on_cat_change=None,
                 on_show_category=None, on_open_interest=None):
        super().__init__(parent, bg=BG)
        self._selected_id      = None
        self._selected_active  = True
        self._on_cat_change    = on_cat_change      # called when spending categories change
        self._on_show_category = on_show_category   # (cat_name) -> open History drilldown
        self._on_open_interest = on_open_interest   # () -> open Interest window
        self._build()

    def _build(self):
        hdr = styled_frame(self)
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        styled_label(hdr, "Dashboard", font=STYLE["font_h1"]).pack(side="left")
        styled_button(hdr, "⟳ Refresh", self.refresh, color=GREEN).pack(side="right", padx=8)
        if self._on_open_interest:
            styled_button(hdr, "\U0001f4b0  Interest", self._on_open_interest,
                          color=YELLOW).pack(side="right", padx=(0, 4))

        # ── Summary cards ──────────────────────────────────────────────────────
        self.cards_frame = styled_frame(self)
        self.cards_frame.pack(fill="x", padx=20, pady=(4, 2))

        # ── Spending Categories — management + allocation cards ────────────────
        cat_hdr = tk.Frame(self, bg=BG)
        cat_hdr.pack(fill="x", padx=20, pady=(6, 0))
        section_label(cat_hdr, "  Spending Categories").pack(side="left")

        # Add-category input inline in the header row
        tk.Label(cat_hdr, text="Add:", bg=BG, fg=SUBTEXT,
                 font=STYLE["font"]).pack(side="left", padx=(20, 4))
        self._new_cat_var = tk.StringVar()
        tk.Entry(cat_hdr, textvariable=self._new_cat_var,
                 bg=BG3, fg=FG, insertbackground=FG, relief="flat",
                 font=STYLE["font"], width=16).pack(side="left", padx=(0, 4))
        styled_button(cat_hdr, "+ Add", self._add_category, color=GREEN).pack(side="left")

        # Chips row — one chip per spending category with a ✕ delete button
        self._cat_list_frame = tk.Frame(self, bg=BG)
        self._cat_list_frame.pack(fill="x", padx=20, pady=(4, 0))
        self._rebuild_cat_list()

        # Category total cards (balance allocated to each category)
        self.cat_cards_frame = styled_frame(self)
        self.cat_cards_frame.pack(fill="x", padx=20, pady=(4, 4))

        # ── Account Editor ─────────────────────────────────────────────────────
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

        # Row 2 — action buttons
        action_row = tk.Frame(edit_bar, bg=BG2)
        action_row.pack(fill="x", padx=8, pady=(0, 4))

        self._sel_label = tk.Label(action_row, text="New account",
                                   bg=BG2, fg=SUBTEXT, font=STYLE["font"], anchor="w")
        self._sel_label.pack(side="left", padx=(0, 10))

        tk.Frame(action_row, bg=BG3, width=1).pack(side="left", fill="y", pady=2)

        self._save_btn = styled_button(action_row, "Create Account", self._save_edits, color=GREEN)
        self._save_btn.pack(side="left", padx=(8, 0))

        self._toggle_btn = styled_button(action_row, "⊗ Deactivate", self._deactivate, color=RED)
        self._unselect_btn = tk.Button(
            action_row, text="← Unselect", bg=BG3, fg=SUBTEXT,
            relief="flat", font=STYLE["font"], padx=8, pady=3,
            cursor="hand2", activebackground=BG2, activeforeground=FG,
            command=self._clear_selection)

        tk.Label(action_row, text="Rates & allocations → Log Snapshot",
                 bg=BG2, fg=SUBTEXT, font=STYLE["font"]).pack(side="right", padx=(0, 4))

        for var in (self._bank_var, self._actype_var):
            var.trace_add("write", lambda *_: self._update_create_preview())

        # ── Current Balances treeview ──────────────────────────────────────────
        section_label(self, "  Current Balances").pack(fill="x", padx=20, pady=(4, 2))
        self._tree_frame = styled_frame(self)
        self._tree_frame.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        self._build_tree()

    # ── Category management ────────────────────────────────────────────────────

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
                      command=lambda cid=cat["id"], cname=cat["name"]:
                          self._delete_category(cid, cname)
                      ).pack(side="left", padx=(4, 0))

    def _add_category(self):
        name = self._new_cat_var.get().strip()
        if not name:
            return
        db.add_spending_category(name)
        self._new_cat_var.set("")
        self._rebuild_cat_list()
        self.rebuild()
        if self._on_cat_change:
            self._on_cat_change()

    def _delete_category(self, cat_id: int, cat_name: str):
        if not messagebox.askyesno(
            "Remove category",
            f"Remove '{cat_name}'?\n\nAll allocation rules for this category will also be deleted.",
        ):
            return
        db.delete_spending_category(cat_id)
        self._rebuild_cat_list()
        self.rebuild()
        if self._on_cat_change:
            self._on_cat_change()

    # ── Tree ──────────────────────────────────────────────────────────────────

    def _build_tree(self):
        for w in self._tree_frame.winfo_children():
            w.destroy()

        self._spend_cats = db.get_spending_category_names()
        _cat_short = {"Spending": "Spending", "Deposit": "Deposit",
                      "Emergency Fund": "Emerg. Fund", "Long Term Savings": "LT Savings",
                      "Pension": "Pension"}
        cat_cols = [c.lower().replace(" ", "_") for c in self._spend_cats]
        cols = ("name", "bank", "product_type", "rate", "max_for_rate",
                "balance", "yearly_int", "last_recorded") + tuple(cat_cols)
        self.tree, sb = make_tree(self._tree_frame, cols, height=22)
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

    # ── Cards ─────────────────────────────────────────────────────────────────

    def _make_card(self, parent, label, value, colour, subtitle=None,
                   subtitle_colour=None, on_click=None):
        f = tk.Frame(parent, bg=BG3, padx=16, pady=10)
        tk.Frame(f, bg=BG3, width=170, height=1).pack()
        lbl_text = f"{label}   ↗" if on_click else label
        tk.Label(f, text=lbl_text, bg=BG3, fg=SUBTEXT, font=STYLE["font"],
                 anchor="w").pack(fill="x")
        tk.Label(f, text=value, bg=BG3, fg=colour,
                 font=("Segoe UI", 16, "bold"), anchor="w").pack(fill="x")
        sub_text   = subtitle or ""
        sub_colour = subtitle_colour if subtitle else BG3
        tk.Label(f, text=sub_text, bg=BG3, fg=sub_colour,
                 font=STYLE["font"], anchor="w").pack(fill="x", pady=(2, 0))

        if on_click:
            def _enter(_e, w=f):
                for c in [w] + list(w.winfo_children()):
                    c.config(bg=BG2)
            def _leave(_e, w=f):
                for c in [w] + list(w.winfo_children()):
                    c.config(bg=BG3)
            for w in [f] + list(f.winfo_children()):
                w.config(cursor="hand2")
                w.bind("<Button-1>", lambda _e: on_click())
                w.bind("<Enter>", _enter)
                w.bind("<Leave>", _leave)
        return f

    def _mom_sub(self, history, current_val):
        pct, gbp = self._mom_change_from(history, current_val)
        if pct is None:
            return None, None
        arrow  = "↑" if gbp >= 0 else "↓"
        sign   = "+" if gbp >= 0 else ""
        colour = GREEN if gbp >= 0 else RED
        return f"{arrow} {abs(pct):.2f}%  {sign}{fmt_gbp(gbp)}  vs 1 mo", colour

    def _mom_change_from(self, history, current_val: float):
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

    # ── Refresh ───────────────────────────────────────────────────────────────

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

        assets_hist = db.get_assets_history()
        debt_hist   = db.get_debt_history()
        nw_hist     = db.get_net_worth_history()

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

        # Category allocation cards
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
            on_click     = (lambda c=cat: self._on_show_category(c)) \
                           if self._on_show_category else None
            self._make_card(self.cat_cards_frame, cat, fmt_gbp(cur_val), colour,
                            subtitle=sub, subtitle_colour=sub_col,
                            on_click=on_click).pack(
                side="left", padx=(0, 10), pady=4)

        # Tree rows
        for row in self.tree.get_children():
            self.tree.delete(row)

        now_str    = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        all_accs   = db.get_all_accounts(include_inactive=True)
        snapshot   = db.get_latest_balance_per_account()
        last_dates = db.get_last_recorded_dates()
        rates      = db._get_rates_on_date(now_str)
        allocs     = db.get_all_allocations_on_date(now_str)

        yearly_int = {
            acc["id"]: max(0.0, snapshot.get(acc["id"], 0.0)) * rates.get(acc["id"], 0.0)
            for acc in all_accs
        }

        active   = [a for a in all_accs if a["is_active"]]
        inactive = [a for a in all_accs if not a["is_active"]]

        _BANK_BG = [
            "#1a2030", "#1a2a1e", "#2a221a", "#251a2a",
            "#1a2828", "#2a1a1e", "#1e1a2a", "#22261a",
        ]
        banks = sorted({
            (a.get("bank") or "").strip()
            for a in all_accs if (a.get("bank") or "").strip()
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
        yr_int = yearly_int.get(acc_id, 0.0)

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

    # ── Edit bar helpers ──────────────────────────────────────────────────────

    def _update_create_preview(self):
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
        self._sel_label.config(text=f"Editing: {acc.get('account_name', '')}", fg=ACCENT)
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
            try:
                db.update_account_details(self._selected_id, bank or None, label or None,
                                          name, ptype or None, max_bal, cat or None)
            except Exception as exc:
                messagebox.showerror("Save failed", str(exc))
                return
        else:
            if not bank:
                messagebox.showwarning("Validation", "Bank is required to create an account.")
                return
            if not label:
                messagebox.showwarning("Validation", "Label is required to create an account.")
                return
            try:
                db.upsert_account(
                    account_name=name, bank=bank, account_type=label,
                    category=cat or None, max_balance_for_rate=max_bal,
                    interest_rate=0.0, allocations={},
                    effective_from=datetime.date.today().isoformat(),
                    note=None, product_type=ptype or None,
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
        if messagebox.askyesno("Confirm",
                               f"Deactivate '{acc['account_name']}'?\n"
                               "It will no longer appear in snapshots but history is kept."):
            db.deactivate_account(self._selected_id)
            self._clear_selection()
            self.refresh()

    def _reactivate(self):
        if not self._selected_id:
            return
        acc = db.get_account_by_id(self._selected_id)
        if messagebox.askyesno("Confirm",
                               f"Reactivate '{acc['account_name']}'?\n"
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
