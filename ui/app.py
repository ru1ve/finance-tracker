"""
ui/app_old.py — FinanceApp: main application window with navigation sidebar.
"""
import tkinter as tk
from tkinter import simpledialog, messagebox

import db
from db.connection import DB_DIR, DB_PATH
from ui.constants import *
from ui.tabs.dashboard      import DashboardTab
from ui.tabs.snapshot       import SnapshotTab
from ui.tabs.history        import HistoryTab
from ui.tabs.interest       import InterestTab
from ui.tabs.mortgage       import MortgageTab
from ui.tabs.calced_balances import CalcedBalancesTab
from ui.tabs.settings       import SettingsTab


class _DBPickerDialog(tk.Toplevel):
    """Startup database picker: select an existing .db file or create a new one."""

    def __init__(self, parent, existing: list):
        super().__init__(parent)
        self.title("Open Finance Database")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self.result   = None
        self._cancel_flag = False
        self._existing = existing
        self._build(existing)

        self.update_idletasks()
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    def _build(self, existing):
        tk.Label(self, text="Finance Tracker", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 15, "bold")).pack(padx=24, pady=(20, 2))
        tk.Label(self, text="Select a database to open, or create a new one.",
                 bg=BG, fg=SUBTEXT, font=STYLE["font"]).pack(padx=24, pady=(0, 12))

        tk.Frame(self, bg=BG3, height=1).pack(fill="x")

        content = tk.Frame(self, bg=BG, padx=24, pady=16)
        content.pack(fill="both", expand=True)

        if existing:
            tk.Label(content, text="Existing databases:", bg=BG, fg=FG,
                     font=STYLE["font_bold"]).pack(anchor="w")

            box_frame = tk.Frame(content, bg=BG3, bd=1, relief="flat")
            box_frame.pack(fill="x", pady=(4, 10))
            self._listbox = tk.Listbox(
                box_frame, bg=BG2, fg=FG,
                selectbackground=BG3, selectforeground=ACCENT,
                relief="flat", font=STYLE["font"],
                height=min(6, len(existing)), activestyle="none",
                highlightthickness=0,
            )
            for p in existing:
                self._listbox.insert("end", p.name)
            self._listbox.pack(fill="x", padx=1, pady=1)
            self._listbox.selection_set(0)
            self._listbox.bind("<Double-Button-1>", lambda _: self._open())

            tk.Button(
                content, text="Open Selected", command=self._open,
                bg=ACCENT, fg=BG, relief="flat", font=STYLE["font_bold"],
                padx=10, pady=7, cursor="hand2",
                activebackground=GREEN, activeforeground=BG,
            ).pack(fill="x", pady=(0, 8))

            tk.Frame(content, bg=BG3, height=1).pack(fill="x", pady=(0, 8))

        tk.Button(
            content, text="+ Create New Database", command=self._create,
            bg=BG3, fg=GREEN, relief="flat", font=STYLE["font_bold"],
            padx=10, pady=7, cursor="hand2",
            activebackground=BG2, activeforeground=GREEN,
        ).pack(fill="x")

        if not existing:
            tk.Label(content, text="No databases found — create one to get started.",
                     bg=BG, fg=SUBTEXT, font=STYLE["font"]).pack(pady=(8, 0))

    def _open(self):
        if not self._existing:
            return
        sel = self._listbox.curselection()
        if not sel:
            messagebox.showwarning("Select a database", "Please select a database from the list.",
                                   parent=self)
            return
        self.result = self._existing[sel[0]]
        self.destroy()

    def _create(self):
        name = simpledialog.askstring(
            "New Database", "Enter a name for the new database:", parent=self)
        if not name or not name.strip():
            return
        name = name.strip().replace(" ", "_")
        if not name.endswith(".db"):
            name += ".db"
        self.result = DB_DIR / name
        self.destroy()

    def _cancel(self):
        self._cancel_flag = True
        self.destroy()


class FinanceApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()   # hide main window until DB is confirmed
        self.title("Personal Finance Tracker")
        self.configure(bg=BG)

        chosen = self._pick_database()
        if chosen is None:
            # User closed the picker without making a choice
            self.destroy()
            return

        db.set_db_path(chosen)
        db.init_db()

        self.geometry("1200x780")
        self.minsize(900, 600)
        self._build_nav()
        self._build_tabs()
        self._show_tab("dashboard")
        self.deiconify()

    def _pick_database(self):
        """Show DB picker. Returns a Path, or None if user cancelled."""
        existing = db.list_db_files()
        if not existing:
            # No databases yet — use the default path silently
            return DB_PATH

        dlg = _DBPickerDialog(self, existing)
        self.wait_window(dlg)

        if dlg._cancel_flag:
            return None
        if dlg.result is not None:
            return dlg.result
        # Dialog closed unexpectedly — fall back to first existing
        return existing[0]

    def _build_nav(self):
        nav = tk.Frame(self, bg=BG2, width=160)
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)

        tk.Label(nav, text="\xa3 Finance", bg=BG2, fg=ACCENT,
                 font=("Segoe UI", 13, "bold"), pady=20).pack(fill="x")

        self._nav_buttons = {}
        tabs = [
            ("dashboard",  "\U0001f4ca  Dashboard"),
            ("snapshot",   "\U0001f4dd  Log Snapshot"),
            ("history",    "\U0001f4c8  History"),
            ("mortgage",   "\U0001f3e0  Mortgage"),
            ("calced",     "\U0001f5c3   Rec. Balances"),
            ("settings",   "⚙   Settings"),
        ]
        for key, label in tabs:
            btn = tk.Button(nav, text=label, bg=BG2, fg=FG, activebackground=BG3,
                            activeforeground=ACCENT, relief="flat", anchor="w",
                            font=STYLE["font"], padx=16, pady=10, cursor="hand2",
                            command=lambda k=key: self._show_tab(k))
            btn.pack(fill="x")
            self._nav_buttons[key] = btn

        tk.Frame(nav, bg=BG2).pack(fill="both", expand=True)

        # Switch DB button at the bottom of the nav
        tk.Button(
            nav, text="⇄ Switch DB", bg=BG2, fg=SUBTEXT,
            relief="flat", font=("Segoe UI", 9), padx=10, pady=6,
            cursor="hand2", activebackground=BG3, activeforeground=FG,
            command=self._switch_db,
        ).pack(fill="x")

        tk.Label(nav, text="v1.0", bg=BG2, fg=SUBTEXT, font=STYLE["font"]).pack(pady=8)

    def _switch_db(self):
        """Let the user switch to a different database (restarts the UI)."""
        existing = db.list_db_files()
        dlg = _DBPickerDialog(self, existing)
        self.wait_window(dlg)
        if dlg._cancel_flag or dlg.result is None:
            return

        db.set_db_path(dlg.result)
        db.init_db()

        # Rebuild all tabs against the new DB
        for tab in self._tabs.values():
            tab.destroy()
        self.container.destroy()
        self._build_tabs()

        # Rebuild nav button state
        for k, btn in self._nav_buttons.items():
            btn.config(bg=BG2, fg=FG)
        self._show_tab("dashboard")

    def _build_tabs(self):
        # Close any open Interest popup (stale after a DB switch)
        prev_win = getattr(self, "_interest_win", None)
        if prev_win is not None and prev_win.winfo_exists():
            prev_win.destroy()

        self.container = tk.Frame(self, bg=BG)
        self.container.pack(side="right", fill="both", expand=True)
        self._tabs = {
            "dashboard":  DashboardTab(self.container,
                                       on_cat_change=self._on_categories_changed,
                                       on_show_category=self._show_category_history,
                                       on_open_interest=self._open_interest),
            "snapshot":   SnapshotTab(self.container),
            "history":    HistoryTab(self.container),
            "mortgage":   MortgageTab(self.container),
            "calced":     CalcedBalancesTab(self.container),
            "settings":   SettingsTab(self.container),
        }
        self._interest_win = None

    def _on_categories_changed(self):
        self._tabs["snapshot"].rebuild()
        self._tabs["mortgage"].refresh_categories()

    def _show_category_history(self, cat_name):
        """Open the History tab drilled into a specific spending category."""
        self._show_tab("history")
        self._tabs["history"].show_category(cat_name)

    def _open_interest(self):
        """Show the Interest & Projection view in a popup window."""
        if self._interest_win is not None and self._interest_win.winfo_exists():
            self._interest_win.deiconify()
            self._interest_win.lift()
            self._interest_win.focus_set()
            return
        win = tk.Toplevel(self)
        win.title("Interest & Projection")
        win.configure(bg=BG)
        win.geometry("1040x660")
        win.minsize(800, 500)
        self._interest_win = win
        tab = InterestTab(win)
        tab.pack(fill="both", expand=True)

    def _show_tab(self, key):
        for k, tab in self._tabs.items():
            tab.pack_forget()
            self._nav_buttons[k].config(bg=BG2, fg=FG)

        self._tabs[key].pack(fill="both", expand=True)
        self._nav_buttons[key].config(bg=BG3, fg=ACCENT)

        # Auto-refresh on focus; snapshot is excluded — it has no refresh() so
        # that in-progress balance entries survive while the user checks another tab.
        refresh_fn = getattr(self._tabs[key], "refresh", None)
        if refresh_fn:
            refresh_fn()
