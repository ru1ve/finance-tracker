"""
ui/dialogs/edit_balance.py — EditBalanceDialog for editing/deleting a single balance entry.
"""
import tkinter as tk
from tkinter import ttk, messagebox

import db
from ui.constants import *
from ui.helpers import styled_button, format_date


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
        self._date_str = date_str
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
