"""
ui/tabs/settings.py — SettingsTab: application preferences.
"""
import datetime
import tkinter as tk
from tkinter import ttk

import db
from ui.constants import *
from ui.helpers import (
    _DATE_FORMATS,
    styled_frame, styled_label, styled_button, styled_entry, section_label,
)


class SettingsTab(tk.Frame):
    _SETTINGS = [
        {
            "section": "Display",
            "items": [
                {
                    "key":     "date_format",
                    "label":   "Date display format",
                    "type":    "select",
                    "options": ["YYYY-MM-DD", "DD/MM/YYYY", "DD Mon YYYY", "MM/DD/YYYY"],
                    "default": "YYYY-MM-DD",
                },
            ],
        },
        {
            "section": "History chart defaults",
            "items": [
                {
                    "key":     "history_default_view",
                    "label":   "Default view",
                    "type":    "select",
                    "options": ["By Category", "By Account"],
                    "default": "By Category",
                },
                {
                    "key":     "history_default_range",
                    "label":   "Default time range",
                    "type":    "select",
                    "options": ["ALL", "2Y", "1Y", "6M", "3M", "YTD"],
                    "default": "ALL",
                },
            ],
        },
    ]

    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._vars    = {}
        self._preview = {}
        self._build()

    def _build(self):
        hdr = styled_frame(self)
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        styled_label(hdr, "Settings", font=STYLE["font_h1"]).pack(side="left")
        styled_button(hdr, "Save", self._save, color=GREEN).pack(side="right")

        content = styled_frame(self)
        content.pack(fill="x", padx=20, pady=8)

        for group in self._SETTINGS:
            section_label(content, f"  {group['section']}").pack(fill="x", pady=(16, 4))

            for item in group["items"]:
                key     = item["key"]
                current = db.get_setting(key, item["default"])
                var     = tk.StringVar(value=current)
                self._vars[key] = var

                row = styled_frame(content)
                row.pack(fill="x", pady=5)

                tk.Label(row, text=item["label"], bg=BG, fg=FG,
                         font=STYLE["font"], width=26, anchor="w").pack(side="left")

                cb = ttk.Combobox(row, textvariable=var, values=item["options"],
                                  state="readonly", width=22, font=STYLE["font"])
                cb.pack(side="left", padx=(0, 16))

                if key == "date_format":
                    lbl = tk.Label(row, text="", bg=BG, fg=SUBTEXT,
                                   font=STYLE.get("font_mono", STYLE["font"]))
                    lbl.pack(side="left")
                    self._preview[key] = lbl
                    var.trace_add("write", lambda *_, k=key: self._update_preview(k))
                    self._update_preview(key)

        self._status = tk.Label(content, text="", bg=BG, fg=GREEN, font=STYLE["font"])
        self._status.pack(anchor="w", pady=(24, 0))

    def _update_preview(self, key):
        if key == "date_format":
            fmt    = _DATE_FORMATS.get(self._vars[key].get(), "%Y-%m-%d")
            sample = datetime.date.today().strftime(fmt)
            self._preview[key].config(text=f"e.g. {sample}")

    def _save(self):
        for key, var in self._vars.items():
            db.set_setting(key, var.get())
        self._status.config(text="✓ Saved")
        self.after(2000, lambda: self._status.config(text=""))
