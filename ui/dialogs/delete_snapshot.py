"""
ui/dialogs/delete_snapshot.py — DeleteSnapshotDialog for removing snapshot records.
"""
import tkinter as tk
from tkinter import messagebox

import db
from ui.constants import *
from ui.helpers import styled_button, fmt_gbp, make_tree


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
        hdr = tk.Frame(self, bg=BG)
        hdr.pack(fill="x", padx=16, pady=(12, 6))
        tk.Label(hdr, text="Delete Snapshot Records", bg=BG, fg=FG,
                 font=STYLE["font_h2"]).pack(side="left")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        # Left: date list
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

        # Right: entries for selected date
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
        date_sel  = self._date_tree.selection()
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
        self._on_date_select()
        self._load_dates()
        if self._on_done:
            self._on_done()
