"""
ui/tabs/categories.py — CategoriesTab: spending allocation breakdown.
"""
import tkinter as tk
from tkinter import messagebox

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure

import db
from ui.constants import *
from ui.helpers import (
    fmt_gbp, styled_frame, styled_label, styled_button, section_label,
    make_tree, embed_figure,
)


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
