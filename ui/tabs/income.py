"""
ui/tabs/income.py — IncomeTab: income entry and monthly chart.
"""
import datetime
import tkinter as tk
from tkinter import ttk, messagebox

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.figure import Figure

import db
from ui.constants import *
from ui.helpers import (
    fmt_gbp, format_date, _DATE_FORMATS,
    styled_frame, styled_label, styled_entry, styled_button,
    make_tree, embed_figure,
)


class IncomeTab(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._build()

    def _build(self):
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

        self._sel_month  = None
        self._month_list = []

        self.fig = Figure(figsize=(10, 3), facecolor=BG)
        self.ax  = self.fig.add_subplot(111, facecolor=BG)
        self.fig.subplots_adjust(left=0.07, right=0.98, top=0.88, bottom=0.15)
        self.canvas_widget = embed_figure(self, self.fig)
        self.canvas_widget.pack(fill="x", padx=20, pady=(0, 6))
        self.fig.canvas.mpl_connect("button_press_event", self._on_bar_click)

        self._drill_bar = tk.Frame(self, bg=BG2)
        self._drill_bar.pack(fill="x", padx=20, pady=(0, 4))
        self._drill_label = tk.Label(self._drill_bar, text="", bg=BG2, fg=ACCENT,
                                      font=STYLE["font_bold"])
        self._drill_label.pack(side="left", padx=(10, 12), pady=4)
        styled_button(self._drill_bar, "← All months", self._clear_drill,
                      color=SUBTEXT).pack(side="left")
        self._drill_bar.pack_forget()

        form = tk.Frame(self, bg=BG2)
        form.pack(fill="x", padx=20, pady=(4, 8))

        def _lbl(text):
            return tk.Label(form, text=text, bg=BG2, fg=SUBTEXT, font=STYLE["font"])

        def _ent(var, w=14):
            return tk.Entry(form, textvariable=var, bg=BG3, fg=FG,
                            insertbackground=FG, relief="flat",
                            font=STYLE["font"], width=w)

        _lbl("Date:").pack(side="left", padx=(10, 3), pady=8)
        self._date_var = tk.StringVar()
        _dfmt = _DATE_FORMATS.get(db.get_setting("date_format", "YYYY-MM-DD"), "%Y-%m-%d")
        self._date_var.set(datetime.datetime.now().strftime(f"{_dfmt} %H:%M"))
        _ent(self._date_var, 16).pack(side="left", padx=(0, 10))

        _lbl("Amount £:").pack(side="left", padx=(0, 3))
        self._amount_var = tk.StringVar()
        _ent(self._amount_var, 10).pack(side="left", padx=(0, 10))

        _lbl("Source:").pack(side="left", padx=(0, 3))
        self._source_var = tk.StringVar()
        self._source_combo = ttk.Combobox(form, textvariable=self._source_var,
                                           width=16, font=STYLE["font"], state="normal")
        self._source_combo["values"] = db.get_income_sources()
        self._source_combo.pack(side="left", padx=(0, 10))

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
        styled_button(form, "🗑 Delete selected", self._delete_selected,
                      color=RED).pack(side="right", padx=10)

        tree_frame = styled_frame(self)
        tree_frame.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        cols = ("date", "amount", "source", "subcategory")
        self.tree, sb = make_tree(tree_frame, cols, height=28)
        for col, hdr_text, w, anch in [
            ("date",        "Date",       140, "w"),
            ("amount",      "Amount",     110, "e"),
            ("source",      "Source",     160, "w"),
            ("subcategory", "Sub-source", 160, "w"),
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

        from collections import defaultdict
        monthly: dict = defaultdict(lambda: defaultdict(float))
        for e in entries:
            month = e["entry_date"][:7]
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
