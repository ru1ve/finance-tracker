"""
ui/tabs/calced_balances.py — CalcedBalancesTab: pivot-table of recorded balances.
"""
import tkinter as tk
from tkinter import ttk

import db
from ui.constants import *
from ui.helpers import fmt_gbp, format_date, styled_frame, styled_label, styled_button
from ui.dialogs.edit_balance import EditBalanceDialog


class CalcedBalancesTab(tk.Frame):
    DATE_W = 110
    COL_W  = 110

    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._accounts       = []
        self._raw_dates      = []
        self._sel_acc_id     = None
        self._sel_acc_name   = None
        self._sel_date       = None
        self._sel_balance    = None
        self._tree           = None
        self._bank_canvas    = None
        self._h_sb           = None
        self._v_sb           = None
        self._built_acc_ids  = []   # account ids in current tree structure
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
        self._tree_frame.grid_rowconfigure(1, weight=1)
        self._tree_frame.grid_columnconfigure(0, weight=1)

        # Apply treeview style once here rather than via dummy make_tree
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Finance.Treeview",
                        background=BG2, foreground=FG, fieldbackground=BG2,
                        rowheight=24, font=STYLE["font"])
        style.configure("Finance.Treeview.Heading",
                        background=BG3, foreground=ACCENT,
                        font=STYLE["font_bold"], relief="flat")
        style.map("Finance.Treeview", background=[("selected", BG3)],
                  foreground=[("selected", ACCENT)])

        self.refresh()

    # ---- Structure builders (called once per unique account set) ----

    def _build_tree_structure(self, accounts):
        """Destroy and recreate the Treeview, scrollbars, and bank header canvas."""
        for w in self._tree_frame.winfo_children():
            w.destroy()

        self._accounts      = accounts
        self._built_acc_ids = [a["id"] for a in accounts]

        dw, cw  = self.DATE_W, self.COL_W
        total_w = dw + cw * len(accounts)

        date_col = "date"
        acc_cols = [f"a{a['id']}" for a in accounts]
        cols     = [date_col] + acc_cols

        self._tree = ttk.Treeview(self._tree_frame, columns=cols, show="headings",
                                  style="Finance.Treeview", height=30)

        self._tree.heading(date_col, text="Date")
        self._tree.column(date_col, width=dw, anchor="w", stretch=False, minwidth=dw)
        for acc in accounts:
            cid    = f"a{acc['id']}"
            bank   = acc.get("bank") or ""
            name   = acc["account_name"]
            prefix = f"{bank} - "
            label  = name[len(prefix):] if bank and name.startswith(prefix) else name
            self._tree.heading(cid, text=label)
            self._tree.column(cid, width=cw, anchor="e", stretch=False, minwidth=cw)

        self._tree.tag_configure("even", background=BG2)
        self._tree.tag_configure("odd",  background=BG)
        self._tree.tag_configure("selected_cell", background=BG3, foreground=ACCENT)

        # Bank header canvas
        bank_h = 22
        self._bank_canvas = tk.Canvas(self._tree_frame, bg=BG3, height=bank_h,
                                      highlightthickness=0,
                                      scrollregion=(0, 0, total_w, bank_h))
        x = dw
        self._bank_canvas.create_rectangle(0, 0, dw, bank_h, fill=BG3, outline=BG2, width=1)
        i = 0
        while i < len(accounts):
            bank = accounts[i].get("bank") or ""
            j = i
            while j < len(accounts) and (accounts[j].get("bank") or "") == bank:
                j += 1
            span = cw * (j - i)
            self._bank_canvas.create_rectangle(x, 0, x + span, bank_h,
                                               fill=BG3, outline=BG2, width=1)
            if bank:
                self._bank_canvas.create_text(x + span // 2, bank_h // 2, text=bank,
                                              fill=ACCENT, font=STYLE["font_bold"],
                                              anchor="center")
            x    += span
            i     = j

        # Scrollbars
        self._v_sb = ttk.Scrollbar(self._tree_frame, orient="vertical",
                                   command=self._tree.yview)
        self._h_sb = ttk.Scrollbar(self._tree_frame, orient="horizontal")

        def _xscroll(first, last):
            self._h_sb.set(first, last)
            self._bank_canvas.xview_moveto(first)

        self._tree.configure(yscrollcommand=self._v_sb.set, xscrollcommand=_xscroll)
        self._h_sb.configure(
            command=lambda *a: (self._tree.xview(*a), self._bank_canvas.xview(*a)))

        self._bank_canvas.grid(row=0, column=0, sticky="ew")
        self._tree.grid(row=1, column=0, sticky="nsew")
        self._v_sb.grid(row=1, column=1, sticky="ns")
        self._h_sb.grid(row=2, column=0, sticky="ew")

        # Bindings
        self._tree.bind("<ButtonRelease-1>", self._on_click)
        self._tree.bind("<Double-Button-1>", lambda e: (self._on_click(e), self._open_edit()))

        def _scroll(e):
            self._tree.yview_scroll(-1 * (e.delta // 120), "units")
        self._tree.bind("<Enter>", lambda e: self._tree.bind_all("<MouseWheel>", _scroll))
        self._tree.bind("<Leave>", lambda e: self._tree.unbind_all("<MouseWheel>"))

    # ---- Row population (cheap — no widget creation) ----

    def _populate_rows(self, accounts, raw_dates, lookup):
        tree = self._tree
        children = tree.get_children()
        if children:
            tree.delete(*children)

        tags = ("even", "odd")
        # Pre-format dates once
        fmt_dates = [format_date(d) for d in raw_dates]
        acc_ids   = [a["id"] for a in accounts]

        for i, (date_str, fmt_d) in enumerate(zip(raw_dates, fmt_dates)):
            values = [fmt_d]
            for acc_id in acc_ids:
                bal = lookup.get(acc_id, {}).get(date_str)
                values.append(fmt_gbp(bal) if bal is not None else "")
            tree.insert("", "end", iid=date_str, values=values, tags=(tags[i % 2],))

    # ---- Public refresh ----

    def refresh(self):
        self._clear_selection()

        accounts      = db.get_all_accounts(include_inactive=True)
        all_histories = db.get_all_balance_histories()

        if not accounts:
            for w in self._tree_frame.winfo_children():
                w.destroy()
            self._tree = None
            self._built_acc_ids = []
            styled_label(self._tree_frame, "No accounts found.", fg=SUBTEXT).pack(pady=20)
            return

        sorted_accs = sorted(accounts, key=lambda a: (a["bank"] or "", a["account_name"]))
        raw_dates   = sorted(
            {d for hist in all_histories.values() for d, _ in hist},
            reverse=True,
        )

        if not raw_dates:
            for w in self._tree_frame.winfo_children():
                w.destroy()
            self._tree = None
            self._built_acc_ids = []
            styled_label(self._tree_frame, "No snapshot data yet.", fg=SUBTEXT).pack(pady=20)
            return

        lookup = {
            acc_id: {d: b for d, b in hist}
            for acc_id, hist in all_histories.items()
        }

        # Only rebuild widget structure when accounts change
        new_acc_ids = [a["id"] for a in sorted_accs]
        if new_acc_ids != self._built_acc_ids or self._tree is None:
            self._build_tree_structure(sorted_accs)

        self._accounts  = sorted_accs
        self._raw_dates = raw_dates
        self._populate_rows(sorted_accs, raw_dates, lookup)

    # ---- Selection / editing ----

    def _clear_selection(self):
        self._sel_acc_id   = None
        self._sel_acc_name = None
        self._sel_date     = None
        self._sel_balance  = None
        self._sel_label.config(text="Click a balance cell to select it", fg=SUBTEXT)
        self._edit_btn.config(state="disabled")

    def _on_click(self, event):
        tree = self._tree
        if tree is None:
            return
        region = tree.identify_region(event.x, event.y)
        if region != "cell":
            self._clear_selection()
            return
        row_iid = tree.identify_row(event.y)
        col_id  = tree.identify_column(event.x)
        if not row_iid:
            return
        col_idx = int(col_id.replace("#", "")) - 1
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
        neg  = bal_str.startswith("-")
        val  = float(bal_str.replace("-", "").replace("\xa3", "").replace(",", ""))
        self._sel_acc_id   = acc["id"]
        self._sel_acc_name = acc["account_name"]
        self._sel_date     = row_iid
        self._sel_balance  = -val if neg else val
        self._sel_label.config(
            text=f"Selected:  {acc['account_name']}  \xb7  {format_date(row_iid)}  \xb7  {bal_str}",
            fg=FG)
        self._edit_btn.config(state="normal")

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
