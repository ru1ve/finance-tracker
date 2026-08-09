"""
ui/tabs/mortgage.py — MortgageTab: mortgage affordability estimator.
"""
import tkinter as tk
from tkinter import ttk, messagebox

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import db
from ui.constants import *
from ui.helpers import (
    fmt_gbp, fmt_pct,
    styled_frame, styled_label, styled_entry, styled_button, section_label,
)


class MortgageTab(tk.Frame):
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
        self._fixed_vars         = {}
        self._fixed_hints        = {}
        self._fixed_entries      = {}
        self._income_items       = []
        self._expense_items      = []
        self._left_canvas        = None
        self._deposit_mode       = tk.StringVar(value="category")
        self._deposit_cat_var    = tk.StringVar()
        self._deposit_custom_var = tk.StringVar()
        self._deposit_cat_combo  = None
        self._deposit_custom_ent = None
        self._calc_state         = None
        self._calc_after_id      = None
        self._results_built      = False
        self._ltv_r              = None   # latest result dict for canvas redraws
        self._budget_fig         = None
        self._budget_fig_canvas  = None
        self._wi_dep_var         = None
        self._wi_sal_var         = None
        self._wi_dep_lbl         = None
        self._wi_sal_lbl         = None
        self._wi_dep_scale       = None
        self._wi_updating        = False
        self._build()

    @staticmethod
    def _hint_entry(entry, var, hint):
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

    def _build(self):
        hdr = styled_frame(self)
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        styled_label(hdr, "Mortgage Calculator", font=STYLE["font_h1"]).pack(side="left")

        body = styled_frame(self)
        body.pack(fill="both", expand=True, padx=20, pady=(0, 12))

        left_outer = styled_frame(body)
        left_outer.pack(side="left", fill="y", padx=(0, 16))

        lc = tk.Canvas(left_outer, bg=BG, highlightthickness=0, width=330)
        lsb = ttk.Scrollbar(left_outer, orient="vertical", command=lc.yview)
        left = tk.Frame(lc, bg=BG)
        left.bind("<Configure>", lambda e: lc.configure(scrollregion=lc.bbox("all")))
        lc.create_window((0, 0), window=left, anchor="nw")
        lc.configure(yscrollcommand=lsb.set)
        lc.pack(side="left", fill="y", expand=False)
        lsb.pack(side="right", fill="y")
        lc.bind("<MouseWheel>", lambda e: lc.yview_scroll(-1*(e.delta//120), "units"))
        self._left_canvas = lc

        section_label(left, "Income").pack(anchor="w", pady=(4, 2))
        for key, lbl, hint, _ in self._FIXED_FIELDS:
            self._fixed_row(left, key, lbl, hint)

        section_label(left, "Property").pack(anchor="w", pady=(10, 2))
        for key, lbl, hint, _ in self._PROP_FIELDS:
            self._fixed_row(left, key, lbl, hint)

        # Wire all fixed fields to auto-recalculate
        for var in self._fixed_vars.values():
            var.trace_add("write", self._schedule_calc)

        section_label(left, "Deposit").pack(anchor="w", pady=(10, 2))
        self._build_deposit_section(left)

        inc_hdr = styled_frame(left)
        inc_hdr.pack(fill="x", pady=(10, 2))
        section_label(inc_hdr, "Monthly Income").pack(side="left")
        tk.Button(inc_hdr, text="+ Add", bg=BG3, fg=GREEN, relief="flat",
                  font=STYLE["font"], padx=6, pady=1, cursor="hand2",
                  activebackground=BG2, activeforeground=GREEN,
                  command=self._add_income_row).pack(side="right")
        self._income_list_frame = tk.Frame(left, bg=BG)
        self._income_list_frame.pack(fill="x")

        exp_hdr = styled_frame(left)
        exp_hdr.pack(fill="x", pady=(10, 2))
        section_label(exp_hdr, "Monthly Expenses").pack(side="left")
        tk.Button(exp_hdr, text="+ Add", bg=BG3, fg=GREEN, relief="flat",
                  font=STYLE["font"], padx=6, pady=1, cursor="hand2",
                  activebackground=BG2, activeforeground=GREEN,
                  command=self._add_expense_row).pack(side="right")
        self._expense_list_frame = tk.Frame(left, bg=BG)
        self._expense_list_frame.pack(fill="x")

        # Wire deposit custom var for auto-calc
        self._deposit_custom_var.trace_add("write", self._schedule_calc)

        right_outer = styled_frame(body)
        right_outer.pack(side="left", fill="both", expand=True)

        self._wi_frame = tk.Frame(right_outer, bg=BG2)
        self._wi_frame.pack(fill="x")
        self._build_whatif_sliders()

        rc_wrap = tk.Frame(right_outer, bg=BG)
        rc_wrap.pack(fill="both", expand=True)
        rc = tk.Canvas(rc_wrap, bg=BG, highlightthickness=0)
        rsb = ttk.Scrollbar(rc_wrap, orient="vertical", command=rc.yview)
        self._results = styled_frame(rc)
        self._results.bind("<Configure>", lambda e: rc.configure(scrollregion=rc.bbox("all")))
        rc.create_window((0, 0), window=self._results, anchor="nw")
        rc.configure(yscrollcommand=rsb.set)
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
        self._fixed_vars[key]    = var
        self._fixed_hints[key]   = hint
        self._fixed_entries[key] = ent

    def _build_deposit_section(self, parent):
        cats = db.get_spending_category_names()

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

        r2 = tk.Frame(parent, bg=BG)
        r2.pack(fill="x", pady=1)
        tk.Radiobutton(r2, text="Custom amount (£):", variable=self._deposit_mode, value="custom",
                       bg=BG, fg=FG, selectcolor=BG3, activebackground=BG, font=STYLE["font"],
                       command=self._on_deposit_mode_change).pack(side="left")
        self._deposit_custom_ent = styled_entry(r2, width=10, textvariable=self._deposit_custom_var)
        self._deposit_custom_ent.pack(side="left", padx=4)
        self._hint_entry(self._deposit_custom_ent, self._deposit_custom_var, "e.g. 20 000")

        self._deposit_cat_var.trace_add("write", lambda *_: (
            self._update_deposit_preview(), self._schedule_calc()))
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
        self._schedule_calc()

    def refresh(self):
        self.refresh_categories()

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
        if label:
            label_var.set(label)
            lbl_ent.config(fg=FG)
        if amount:
            amount_var.set(str(amount))
            amt_ent.config(fg=FG)
        label_var.trace_add("write",  self._schedule_calc)
        amount_var.trace_add("write", self._schedule_calc)

        entry = {"label_var": label_var, "amount_var": amount_var,
                 "frame": row, "lbl_ent": lbl_ent, "amt_ent": amt_ent}

        def _delete(e=entry, r=row):
            item_list.remove(e)
            r.destroy()
            self._schedule_calc()

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

    def _load_from_db(self):
        fixed = db.get_mortgage_fixed()
        for key, var in self._fixed_vars.items():
            if key in fixed and fixed[key] != 0.0:
                var.set(str(fixed[key]))
                if key in self._fixed_entries:
                    self._fixed_entries[key].config(fg=FG)

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

        self._calc_state = {
            "r": r, "income": income, "bonus": bonus, "pension": pension,
            "boe": boe, "term": term, "extra_monthly": extra_monthly,
            "expenses": expenses, "income_items": income_items,
            "price": price, "overbid": overbid,
        }

        wi_max_dep = min(max(50_000, int(max(0, r["mortgage_amount"] - r["est_borrow_45x"])) + 50_000), 500_000)
        self._wi_updating = True
        self._wi_dep_scale.config(to=wi_max_dep)
        self._wi_dep_var.set(0)
        self._wi_sal_var.set(0)
        self._wi_dep_lbl.config(text="£0")
        self._wi_sal_lbl.config(text="£0")
        self._wi_updating = False

        self._render_results(r, term, pension, income_items)

    # ── Auto-calculate (debounced) ─────────────────────────────────────────────

    def _schedule_calc(self, *_):
        if self._calc_after_id:
            self.after_cancel(self._calc_after_id)
        self._calc_after_id = self.after(350, self._calc)

    # ── Results skeleton (built once, updated in-place thereafter) ────────────

    def _build_results_skeleton(self):
        rf = self._results

        # 6 hero stat cards (2 rows × 3 cols)
        cards_f = tk.Frame(rf, bg=BG)
        cards_f.pack(fill="x", pady=(10, 6), padx=2)
        for col in range(3):
            cards_f.columnconfigure(col, weight=1, uniform="hero")

        self._cards = {}
        for key, title, row, col in [
            ("payment",     "Monthly Payment",       0, 0),
            ("ltv",         "LTV",                   0, 1),
            ("surplus",     "Surplus",               0, 2),
            ("net_monthly", "Net Monthly Income",    1, 0),
            ("deposit",     "Deposit (after costs)", 1, 1),
            ("est_borrow",  "Est. Max Borrow",       1, 2),
        ]:
            f = tk.Frame(cards_f, bg=BG3, padx=12, pady=8)
            tk.Frame(f, bg=BG3, width=140, height=1).pack()
            t_lbl = tk.Label(f, text=title, bg=BG3, fg=SUBTEXT,
                             font=STYLE["font"], anchor="w")
            t_lbl.pack(fill="x")
            v_lbl = tk.Label(f, text="—", bg=BG3, fg=FG,
                             font=("Segoe UI", 15, "bold"), anchor="w")
            v_lbl.pack(fill="x")
            s_lbl = tk.Label(f, text="", bg=BG3, fg=SUBTEXT,
                             font=STYLE["font"], anchor="w")
            s_lbl.pack(fill="x")
            f.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")
            self._cards[key] = (t_lbl, v_lbl, s_lbl)

        # Banners container — children rebuilt cheaply on each update
        self._banners_frame = tk.Frame(rf, bg=BG)
        self._banners_frame.pack(fill="x")

        tk.Frame(rf, bg=BG3, height=1).pack(fill="x", pady=(8, 0))
        section_label(rf, "Property  &  LTV").pack(anchor="w", pady=(8, 4))

        self._ltv_canvas = tk.Canvas(rf, bg=BG, height=70, highlightthickness=0)
        self._ltv_canvas.pack(fill="x", padx=2, pady=(0, 6))
        self._ltv_canvas.bind("<Configure>", self._draw_ltv)

        # Nudge — inserted before _ltv_div via pack(before=) when needed
        self._nudge_frame    = tk.Frame(rf, bg=BG2, padx=12, pady=6)
        self._nudge_lbl_band = tk.Label(self._nudge_frame, bg=BG2, fg=YELLOW, font=STYLE["font_bold"])
        self._nudge_lbl_mid  = tk.Label(self._nudge_frame, bg=BG2, fg=SUBTEXT, font=STYLE["font"])
        self._nudge_lbl_save = tk.Label(self._nudge_frame, bg=BG2, fg=GREEN,   font=STYLE["font_bold"])
        tk.Label(self._nudge_frame, text="Next LTV band:", bg=BG2, fg=SUBTEXT,
                 font=STYLE["font"]).pack(side="left")
        self._nudge_lbl_band.pack(side="left")
        self._nudge_lbl_mid.pack(side="left")
        self._nudge_lbl_save.pack(side="left")
        self._ltv_div = tk.Frame(rf, bg=BG3, height=1)
        self._ltv_div.pack(fill="x")

        # Budget section
        section_label(rf, "Monthly Budget").pack(anchor="w", pady=(8, 4))
        budget_outer = tk.Frame(rf, bg=BG)
        budget_outer.pack(fill="x", padx=2)

        # Persistent matplotlib figure — cleared and redrawn on every update
        self._budget_fig        = Figure(figsize=(3.4, 3.4), facecolor=BG)
        self._budget_fig_canvas = FigureCanvasTkAgg(self._budget_fig, master=budget_outer)
        self._budget_fig_canvas.get_tk_widget().pack(side="left", padx=(0, 12))

        # Budget table container — rows are cheap to rebuild (count varies with expenses)
        self._budget_tbl = tk.Frame(budget_outer, bg=BG)
        self._budget_tbl.pack(side="left", fill="both", expand=True, pady=4)

        # Income breakdown — static label pairs, dynamic income_items sub-frame
        tk.Frame(rf, bg=BG3, height=1).pack(fill="x", pady=(10, 0))
        section_label(rf, "Income Breakdown").pack(anchor="w", pady=(8, 4))

        def _static_row(lbl):
            row = tk.Frame(rf, bg=BG)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=lbl, bg=BG, fg=SUBTEXT, font=STYLE["font"],
                     width=24, anchor="w").pack(side="left")
            v = tk.Label(row, text="—", bg=BG, fg=FG, font=STYLE["font_mono"], anchor="e")
            v.pack(side="left", padx=4)
            return v

        self._bd_gross   = _static_row("Gross (salary + bonus)")
        self._bd_net_ann = _static_row("Net annual")
        self._bd_net_mo  = _static_row("Net monthly salary")
        self._bd_inc_dyn = tk.Frame(rf, bg=BG)
        self._bd_inc_dyn.pack(fill="x")
        self._bd_total   = _static_row("Total net monthly")
        self._bd_total.config(font=STYLE["font_bold"])

        tk.Frame(rf, bg=BG3, height=1).pack(fill="x", pady=(10, 4))
        tk.Label(rf, text="⚠  Estimates only. Lenders assess affordability individually.",
                 bg=BG, fg=SUBTEXT, font=STYLE["font"], wraplength=480,
                 justify="left").pack(anchor="w", pady=(0, 8))

        self._results_built = True

    # ── LTV canvas draw (method — reads self._ltv_r, called on Configure + update) ──

    _C_DEP  = "#2d7a4f"
    _C_BORR = "#7a6500"
    _C_SHRT = "#8a2020"
    _C_OVER = "#1e6b68"
    _C_FEES = "#5a2d8a"

    def _draw_ltv(self, _=None):
        r = self._ltv_r
        if r is None:
            return
        ltv_c = self._ltv_canvas
        ltv_c.delete("all")
        w = ltv_c.winfo_width()
        if w < 20:
            return
        price = r["property_price"]
        if price <= 0:
            ltv_c.create_text(w // 2, 35, fill=SUBTEXT, font=STYLE["font"],
                              text="Enter a property price to see the breakdown")
            return
        overbid    = r["overbid_amount"]
        fees_v     = r["fees"]
        total_cost = price + overbid + fees_v
        scale      = w / total_cost if total_cost > 0 else 1
        if r["deposit_shortfall"] > 0:
            savings        = max(0.0, r["deposit_raw"])
            cost_shortfall = r["deposit_shortfall"]
            can_borrow     = min(price, r["est_borrow_45x"])
            borrow_gap     = max(0.0, price - r["est_borrow_45x"])
            segs = [
                (savings,        self._C_DEP,  "Savings",        fmt_gbp(savings)),
                (cost_shortfall, self._C_SHRT, "Cost shortfall", fmt_gbp(cost_shortfall)),
                (can_borrow,     self._C_BORR, "Can borrow",     fmt_gbp(can_borrow)),
                (borrow_gap,     "#4a2020",    "Borrow gap",     fmt_gbp(borrow_gap)),
            ]
        else:
            dep        = max(0.0, r["deposit_after"])
            mort       = max(0.0, r["mortgage_amount"])
            can_borrow = min(mort, r["est_borrow_45x"])
            shortfall  = max(0.0, mort - r["est_borrow_45x"])
            segs = [
                (dep,        self._C_DEP,  "Deposit",    fmt_gbp(dep)),
                (can_borrow, self._C_BORR, "Can borrow", fmt_gbp(can_borrow)),
                (shortfall,  self._C_SHRT, "Shortfall",  fmt_gbp(shortfall)),
                (overbid,    self._C_OVER, "Over-bid",   fmt_gbp(overbid)),
                (fees_v,     self._C_FEES, "Fees",       fmt_gbp(fees_v)),
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
            cx    = (x0 + x1) // 2
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

    # ── In-place render ───────────────────────────────────────────────────────

    def _render_results(self, r, term, pension, income_items):
        if not self._results_built:
            self._build_results_skeleton()

        surplus     = r["monthly_surplus"]
        surplus_c   = GREEN if surplus >= 0 else RED
        surplus_lbl = "Surplus" if surplus >= 0 else "Shortfall"
        monthly_saving = r["monthly_mortgage"] - r["next_ltv_monthly"]

        def brow(parent, label, val, col, bold=False):
            row = tk.Frame(parent, bg=BG)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=label, bg=BG, fg=SUBTEXT, font=STYLE["font"],
                     width=24, anchor="w").pack(side="left")
            tk.Label(row, text=val, bg=BG, fg=col,
                     font=STYLE["font_bold"] if bold else STYLE["font_mono"],
                     anchor="e").pack(side="left", padx=4)

        # --- Cards (update text and colour in-place) ---
        dep_col = RED if r["deposit_after"] < 0 else ACCENT
        dep_sub = (f"⚠ save {fmt_gbp(r['deposit_shortfall'])} more"
                   if r["deposit_after"] < 0
                   else f"{fmt_gbp(r['deposit_raw'])} available")

        def _upd(key, title=None, value="—", col=FG, sub="", sub_col=None):
            t, v, s = self._cards[key]
            if title is not None:
                t.config(text=title)
            v.config(text=value, fg=col)
            s.config(text=sub, fg=sub_col or SUBTEXT)

        _upd("payment",     value=fmt_gbp(r["monthly_mortgage"]),   col=RED,
             sub=f"over {term} yrs  ·  {fmt_pct(r['interest_rate'])} rate")
        _upd("ltv",         value=fmt_pct(r["ltv"]),                col=YELLOW,
             sub=f"mortgage {fmt_gbp(r['mortgage_amount'])}")
        _upd("surplus",     title=surplus_lbl,
             value=fmt_gbp(abs(surplus)),                           col=surplus_c,
             sub="per month after all costs")
        _upd("net_monthly", value=fmt_gbp(r["total_net_monthly"]),  col=GREEN,
             sub=f"net annual {fmt_gbp(r['net_annual'])}")
        _upd("deposit",     value=fmt_gbp(r["deposit_after"]),      col=dep_col, sub=dep_sub)
        _upd("est_borrow",  value=fmt_gbp(r["est_borrow_45x"]),    col=ACCENT,
             sub="4.5× salary guideline")

        # --- Banners (destroy+recreate their container's children — tiny cost) ---
        for w in self._banners_frame.winfo_children():
            w.destroy()

        def _banner(bg, fg, *lines):
            f = tk.Frame(self._banners_frame, bg=bg, padx=14, pady=8)
            f.pack(fill="x", pady=(0, 4), padx=2)
            for i, line in enumerate(lines):
                tk.Label(f, text=line, bg=bg,
                         fg=fg if i == 0 else SUBTEXT,
                         font=STYLE["font_bold"] if i == 0 else STYLE["font"],
                         anchor="w").pack(anchor="w")

        if r["deposit_shortfall"] > 0:
            _banner("#2d1010", RED,
                    f"⚠  Deposit shortfall — save {fmt_gbp(r['deposit_shortfall'])} more "
                    f"before you can apply for a mortgage")

        if r["deposit_shortfall"] == 0 and r["mortgage_amount"] > r["est_borrow_45x"]:
            bg      = r["mortgage_amount"] - r["est_borrow_45x"]
            si      = bg / 4.5
            _banner("#1e1a08", "#e0b040",
                    f"⚠  Lender cap: mortgage needed {fmt_gbp(r['mortgage_amount'])} exceeds "
                    f"the 4.5× salary limit {fmt_gbp(r['est_borrow_45x'])}",
                    f"    To qualify, add {fmt_gbp(bg)} more to your deposit  —  or  —  "
                    f"earn {fmt_gbp(si)} more per year")

        if r["salary_required"] is not None:
            req = r["salary_required"] / (1 - pension) if pension < 1 else r["salary_required"]
            _banner("#2d2010", YELLOW,
                    f"⚠  Mortgage affordability: you'd need {fmt_gbp(req)} gross/yr to cover payments")

        # --- LTV canvas (redrawn via method, no closure needed) ---
        self._ltv_r = r
        self._ltv_canvas.after(10, self._draw_ltv)

        # --- Nudge (pack/forget relative to permanent _ltv_div) ---
        if r["deposit_shortfall"] == 0 and r["additional_deposit"] > 0:
            self._nudge_lbl_band.config(text=f"  {r['next_ltv_label']}  ")
            self._nudge_lbl_mid.config(
                text=f"add {fmt_gbp(r['additional_deposit'])} deposit  →  save ")
            self._nudge_lbl_save.config(text=f"{fmt_gbp(monthly_saving)}/mo")
            self._nudge_frame.pack(fill="x", padx=2, pady=(0, 4),
                                   before=self._ltv_div)
        else:
            self._nudge_frame.pack_forget()

        # --- Concentric two-ring budget donut ---
        self._budget_fig.clear()
        self._budget_fig.subplots_adjust(left=0.05, right=0.95, top=0.92, bottom=0.05)

        income_val  = r["total_net_monthly"]
        expense_val = r["total_expenses"]
        over_budget = expense_val > income_val

        ax = self._budget_fig.add_subplot(111, facecolor=BG)

        # Outer ring — expenses (segmented; mortgage in RED)
        slice_palette = ["#4a5568", "#5a6578", "#3a4558", "#6a7588",
                         "#2a3548", "#7a8598", "#525f72", "#404e62"]
        exp_slices, exp_colours = [], []
        for i, (k, v) in enumerate(r["expenses"].items()):
            if v > 0:
                exp_slices.append(v)
                exp_colours.append(slice_palette[i % len(slice_palette)])
        if r["monthly_mortgage"] > 0:
            exp_slices.append(r["monthly_mortgage"])
            exp_colours.append(RED)
        if sum(exp_slices) > 0:
            ax.pie(exp_slices, colors=exp_colours, radius=1.0, startangle=90,
                   wedgeprops=dict(width=0.32, edgecolor=BG, linewidth=1.5))

        # Inner ring — green fill proportional to coverage; gap shows shortfall
        if over_budget:
            covered = income_val / expense_val
            inc_slices  = [covered, 1.0 - covered]
            inc_colours = [GREEN, BG2]
        else:
            inc_slices  = [1]
            inc_colours = [GREEN]
        ax.pie(inc_slices, colors=inc_colours, radius=0.62, startangle=90,
               wedgeprops=dict(width=0.32, edgecolor=BG, linewidth=1.5))

        # Centre labels
        exp_col = RED if over_budget else FG
        ax.text(0,  0.12, fmt_gbp(income_val),
                ha="center", va="center", fontsize=8, color=GREEN,
                fontweight="bold", fontfamily="monospace")
        ax.text(0, -0.12, fmt_gbp(expense_val),
                ha="center", va="center", fontsize=8, color=exp_col,
                fontweight="bold", fontfamily="monospace")
        ax.text(0,  0.34, "income",   ha="center", fontsize=6.5, color=SUBTEXT)
        ax.text(0, -0.34, "expenses", ha="center", fontsize=6.5, color=SUBTEXT)

        title_col = RED if over_budget else SUBTEXT
        ax.set_title("Budget", color=title_col, fontsize=8, pad=4, fontfamily="monospace")
        ax.set_aspect("equal")

        self._budget_fig_canvas.draw_idle()

        # --- Budget table (small rebuild — varies with expense count) ---
        for w in self._budget_tbl.winfo_children():
            w.destroy()
        brow(self._budget_tbl, "Net income", fmt_gbp(r["total_net_monthly"]), GREEN, bold=True)
        for name, amt in income_items:
            if name and amt:
                brow(self._budget_tbl, f"  + {name}", fmt_gbp(amt), ACCENT)
        tk.Frame(self._budget_tbl, bg=BG3, height=1).pack(fill="x", pady=3)
        for k, v in r["expenses"].items():
            brow(self._budget_tbl, f"  − {k}", fmt_gbp(v), SUBTEXT)
        brow(self._budget_tbl, "  − Mortgage", fmt_gbp(r["monthly_mortgage"]), RED)
        tk.Frame(self._budget_tbl, bg=BG3, height=1).pack(fill="x", pady=3)
        brow(self._budget_tbl, surplus_lbl, fmt_gbp(abs(surplus)), surplus_c, bold=True)

        # --- Income breakdown (static labels updated; dynamic rows rebuilt) ---
        self._bd_gross.config(  text=fmt_gbp(r["gross_taxable"]), fg=FG)
        self._bd_net_ann.config(text=fmt_gbp(r["net_annual"]),    fg=GREEN)
        self._bd_net_mo.config( text=fmt_gbp(r["net_monthly"]),   fg=GREEN)
        for w in self._bd_inc_dyn.winfo_children():
            w.destroy()
        for name, amt in income_items:
            if name and amt:
                brow(self._bd_inc_dyn, f"  + {name}", fmt_gbp(amt) + "/mo", ACCENT)
        self._bd_total.config(text=fmt_gbp(r["total_net_monthly"]), fg=GREEN)
