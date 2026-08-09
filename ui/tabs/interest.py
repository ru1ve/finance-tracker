"""
ui/tabs/interest.py — InterestTab: current interest summary + forward projection.
"""
import tkinter as tk

import db
from ui.constants import *
from ui.helpers import (
    fmt_gbp, fmt_pct,
    styled_frame, styled_label, styled_entry, styled_button, section_label,
    make_tree,
)


class InterestTab(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._build()

    def _build(self):
        hdr = styled_frame(self)
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        styled_label(hdr, "Interest & Projection", font=STYLE["font_h1"]).pack(side="left")

        ctrl = styled_frame(self)
        ctrl.pack(fill="x", padx=20, pady=4)
        styled_label(ctrl, "Project forward:").pack(side="left")
        self.months_var = tk.StringVar(value="12")
        e = styled_entry(ctrl, width=6, textvariable=self.months_var)
        e.pack(side="left", padx=8)
        styled_label(ctrl, "months").pack(side="left")
        styled_button(ctrl, "Calculate", self.refresh, color=ACCENT).pack(side="left", padx=16)

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

        summary    = db.get_current_interest_summary()
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
