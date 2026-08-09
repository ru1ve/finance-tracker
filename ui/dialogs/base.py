"""
ui/dialogs/base.py — BaseDialog: shared foundation for modal dialogs.
"""
import tkinter as tk

import db
from ui.constants import *
from ui.helpers import styled_frame, styled_label, styled_entry


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
