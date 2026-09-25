"""
ui/tabs/spending.py — SpendingTab: upload bank statements and view transactions.

Two views toggled by a menu button at the top:
  · Log  — pick an account, upload a file, review what will be added, confirm.
  · View — a plain table of stored transactions; edit a category inline and it
           is applied to every transaction of the same name.
"""
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import db
from ui.constants import *
from ui.helpers import (
    fmt_gbp, format_date,
    styled_frame, styled_label, styled_button, make_tree,
)


class SpendingTab(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._mode     = tk.StringVar(value="log")
        self._pending  = None    # (path, source, [preview rows]) awaiting confirm
        self._accounts = []
        self._build()

    # ── Layout ─────────────────────────────────────────────────────────────

    def _build(self):
        hdr = styled_frame(self)
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        styled_label(hdr, "Spending", font=STYLE["font_h1"]).pack(side="left")

        # Segmented Log | View toggle
        seg = tk.Frame(hdr, bg=BG3)
        seg.pack(side="right")
        self._seg_btns = {}
        for key, label in (("log", "Log"), ("view", "View")):
            b = tk.Button(seg, text=label, width=8, relief="flat",
                          font=STYLE["font_bold"], cursor="hand2",
                          command=lambda k=key: self._set_mode(k))
            b.pack(side="left", padx=1, pady=1)
            self._seg_btns[key] = b

        self._body = tk.Frame(self, bg=BG)
        self._body.pack(fill="both", expand=True)

        self._log_frame  = tk.Frame(self._body, bg=BG)
        self._view_frame = tk.Frame(self._body, bg=BG)
        self._build_log(self._log_frame)
        self._build_view(self._view_frame)

        self._set_mode("log")

    def _set_mode(self, key):
        self._mode.set(key)
        for k, b in self._seg_btns.items():
            active = (k == key)
            b.config(bg=ACCENT if active else BG3, fg=BG if active else FG)
        self._log_frame.pack_forget()
        self._view_frame.pack_forget()
        if key == "log":
            self._log_frame.pack(fill="both", expand=True)
            self._refresh_accounts()
            self._refresh_imports()
        else:
            self._view_frame.pack(fill="both", expand=True)
            self._refresh_view_accounts()
            self._populate_view()

    # ── Log view ───────────────────────────────────────────────────────────

    def _build_log(self, root):
        bar = styled_frame(root)
        bar.pack(fill="x", padx=20, pady=(6, 4))
        styled_label(bar, "Account:").pack(side="left")
        self._acc_var = tk.StringVar()
        self._acc_combo = ttk.Combobox(bar, textvariable=self._acc_var, width=28,
                                       font=STYLE["font"], state="readonly")
        self._acc_combo.pack(side="left", padx=(6, 12))
        styled_button(bar, "⇪ Upload statement…", self._choose_file,
                      color=ACCENT).pack(side="left")
        self._src_label = styled_label(bar, "", fg=SUBTEXT)
        self._src_label.pack(side="left", padx=12)

        # Preview table
        section = styled_label(root, "  Preview — rows that will be added",
                               font=STYLE["font_bold"])
        section.pack(fill="x", padx=20, pady=(8, 2))

        prev_frame = styled_frame(root)
        prev_frame.pack(fill="both", expand=True, padx=20, pady=(0, 4))
        cols = ("date", "name", "amount", "category", "subcategory", "status")
        self._prev_tree, sb = make_tree(prev_frame, cols, height=16)
        for c, txt, w, anc in [
            ("date", "Date", 100, "w"), ("name", "Name", 260, "w"),
            ("amount", "Amount", 110, "e"), ("category", "Category", 140, "w"),
            ("subcategory", "Sub-category", 140, "w"), ("status", "Status", 90, "w"),
        ]:
            self._prev_tree.heading(c, text=txt)
            self._prev_tree.column(c, width=w, anchor=anc)
        self._prev_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._prev_tree.tag_configure("dup", foreground=SUBTEXT)
        self._prev_tree.tag_configure("spend", foreground=FG)
        self._prev_tree.tag_configure("income", foreground=GREEN)

        # Confirm / cancel
        act = styled_frame(root)
        act.pack(fill="x", padx=20, pady=(0, 6))
        self._summary_lbl = styled_label(act, "No file loaded.", fg=SUBTEXT)
        self._summary_lbl.pack(side="left")
        self._cancel_btn  = styled_button(act, "Cancel", self._cancel_pending, color=BG3)
        self._confirm_btn = styled_button(act, "✓ Confirm import", self._confirm_pending,
                                          color=GREEN)

        # Past imports (compact, for undo)
        styled_label(root, "  Recent imports", font=STYLE["font_bold"]).pack(
            fill="x", padx=20, pady=(6, 2))
        imp_frame = styled_frame(root)
        imp_frame.pack(fill="x", padx=20, pady=(0, 12))
        icols = ("when", "account", "file", "count")
        self._imp_tree, isb = make_tree(imp_frame, icols, height=5)
        for c, txt, w, anc in [
            ("when", "Uploaded", 140, "w"), ("account", "Account", 180, "w"),
            ("file", "File", 320, "w"), ("count", "Rows", 70, "e"),
        ]:
            self._imp_tree.heading(c, text=txt)
            self._imp_tree.column(c, width=w, anchor=anc)
        self._imp_tree.pack(side="left", fill="x", expand=True)
        isb.pack(side="right", fill="y")
        styled_button(imp_frame, "🗑 Delete", self._delete_import, color=RED).pack(
            side="right", padx=6)

    def _refresh_accounts(self):
        self._accounts = db.get_all_accounts(include_inactive=True)
        names = [a["account_name"] for a in self._accounts]
        self._acc_combo["values"] = names
        if names and not self._acc_var.get():
            self._acc_var.set(names[0])

    def _selected_account_id(self):
        name = self._acc_var.get()
        for a in self._accounts:
            if a["account_name"] == name:
                return a["id"]
        return None

    def _choose_file(self):
        acc_id = self._selected_account_id()
        if acc_id is None:
            messagebox.showwarning("Select account",
                                   "Choose an account before uploading.")
            return
        path = filedialog.askopenfilename(
            title="Select statement",
            filetypes=[("Statements", "*.csv *.xlsx *.pdf"),
                       ("CSV", "*.csv"), ("Excel", "*.xlsx"),
                       ("PDF", "*.pdf"), ("All files", "*.*")])
        if not path:
            return
        try:
            source, parsed = db.detect_and_parse(path)
        except Exception as exc:
            messagebox.showerror("Could not read file", str(exc))
            return
        if not parsed:
            messagebox.showinfo("Nothing found",
                                "No transactions could be read from that file.")
            return
        preview = db.build_preview(acc_id, parsed)
        self._pending = (path, source, preview)
        self._src_label.config(text=f"{source}  ·  {os.path.basename(path)}")
        self._show_preview(preview)

    def _show_preview(self, preview):
        for r in self._prev_tree.get_children():
            self._prev_tree.delete(r)
        new_n = 0
        for i, t in enumerate(preview):
            is_dup = t["is_duplicate"]
            if not is_dup:
                new_n += 1
            tag = "dup" if is_dup else ("income" if t["amount"] >= 0 else "spend")
            self._prev_tree.insert("", "end", iid=str(i), values=(
                format_date(t["txn_date"]),
                t["name"],
                fmt_gbp(t["amount"]),
                t.get("category") or "—",
                t.get("subcategory") or "—",
                "Duplicate" if is_dup else "New",
            ), tags=(tag,))
        dup_n = len(preview) - new_n
        self._summary_lbl.config(
            text=f"{new_n} new · {dup_n} duplicate (skipped)  —  review, then confirm.",
            fg=FG)
        self._confirm_btn.pack(side="right", padx=(6, 0))
        self._cancel_btn.pack(side="right", padx=(6, 0))

    def _confirm_pending(self):
        if not self._pending:
            return
        acc_id = self._selected_account_id()
        path, source, preview = self._pending
        added = db.commit_import(acc_id, os.path.basename(path), source, preview)
        messagebox.showinfo("Imported", f"Added {added} transaction(s).")
        self._cancel_pending()
        self._refresh_imports()

    def _cancel_pending(self):
        self._pending = None
        for r in self._prev_tree.get_children():
            self._prev_tree.delete(r)
        self._summary_lbl.config(text="No file loaded.", fg=SUBTEXT)
        self._src_label.config(text="")
        self._confirm_btn.pack_forget()
        self._cancel_btn.pack_forget()

    def _refresh_imports(self):
        for r in self._imp_tree.get_children():
            self._imp_tree.delete(r)
        for imp in db.get_imports():
            self._imp_tree.insert("", "end", iid=str(imp["id"]), values=(
                (imp["uploaded_at"] or "")[:16],
                imp["account_name"],
                imp["filename"],
                imp["row_count"],
            ))

    def _delete_import(self):
        sel = self._imp_tree.selection()
        if not sel:
            messagebox.showwarning("No selection", "Select an import to delete.")
            return
        imp_id = int(sel[0])
        if not messagebox.askyesno(
                "Delete import",
                "Delete this import and all its transactions?"):
            return
        db.delete_import(imp_id)
        self._refresh_imports()

    # ── View ───────────────────────────────────────────────────────────────

    def _build_view(self, root):
        bar = styled_frame(root)
        bar.pack(fill="x", padx=20, pady=(6, 4))
        styled_label(bar, "Account:").pack(side="left")
        self._view_acc_var = tk.StringVar(value="All accounts")
        self._view_acc_combo = ttk.Combobox(bar, textvariable=self._view_acc_var,
                                            width=28, font=STYLE["font"], state="readonly")
        self._view_acc_combo.pack(side="left", padx=(6, 12))
        self._view_acc_combo.bind("<<ComboboxSelected>>", lambda _e: self._populate_view())
        styled_label(bar, "Double-click a Category or Sub-category cell to set it "
                          "(applies to all same-named transactions).",
                     fg=SUBTEXT).pack(side="left", padx=8)

        tree_frame = styled_frame(root)
        tree_frame.pack(fill="both", expand=True, padx=20, pady=(4, 16))
        cols = ("date", "account", "name", "amount", "category", "subcategory")
        self._view_tree, sb = make_tree(tree_frame, cols, height=26)
        for c, txt, w, anc in [
            ("date", "Date", 100, "w"), ("account", "Account", 150, "w"),
            ("name", "Name", 280, "w"), ("amount", "Amount", 105, "e"),
            ("category", "Category", 150, "w"), ("subcategory", "Sub-category", 150, "w"),
        ]:
            self._view_tree.heading(c, text=txt)
            self._view_tree.column(c, width=w, anchor=anc)
        self._view_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._view_tree.tag_configure("spend", foreground=FG)
        self._view_tree.tag_configure("income", foreground=GREEN)
        self._view_tree.bind("<Double-Button-1>", self._on_view_double_click)

        def _scroll(e):
            self._view_tree.yview_scroll(-1 * (e.delta // 120), "units")
        self._view_tree.bind("<Enter>", lambda e: self._view_tree.bind_all("<MouseWheel>", _scroll))
        self._view_tree.bind("<Leave>", lambda e: self._view_tree.unbind_all("<MouseWheel>"))

    def _refresh_view_accounts(self):
        self._accounts = db.get_all_accounts(include_inactive=True)
        self._view_acc_combo["values"] = ["All accounts"] + \
            [a["account_name"] for a in self._accounts]

    def _view_account_id(self):
        name = self._view_acc_var.get()
        if name == "All accounts":
            return None
        for a in self._accounts:
            if a["account_name"] == name:
                return a["id"]
        return None

    def _populate_view(self):
        for r in self._view_tree.get_children():
            self._view_tree.delete(r)
        for t in db.get_transactions(self._view_account_id()):
            tag = "income" if t["amount"] >= 0 else "spend"
            self._view_tree.insert("", "end", iid=str(t["id"]), values=(
                format_date(t["txn_date"]),
                t["account_name"],
                t["name"],
                fmt_gbp(t["amount"]),
                t.get("category") or "—",
                t.get("subcategory") or "—",
            ), tags=(tag,))

    _COL_FIELD = {"#5": "category", "#6": "subcategory"}

    def _on_view_double_click(self, event):
        if self._view_tree.identify_region(event.x, event.y) != "cell":
            return
        col = self._view_tree.identify_column(event.x)
        field = self._COL_FIELD.get(col)
        if not field:
            return
        row_iid = self._view_tree.identify_row(event.y)
        if not row_iid:
            return
        self._edit_class_cell(row_iid, col, field)

    def _edit_class_cell(self, row_iid, col, field):
        x, y, w, h = self._view_tree.bbox(row_iid, col)
        current = self._view_tree.set(row_iid, field)
        current = "" if current == "—" else current

        # Suggestions: categories, or sub-categories filtered by this row's category.
        if field == "category":
            values = db.get_categories()
        else:
            parent = self._view_tree.set(row_iid, "category")
            parent = "" if parent == "—" else parent
            values = db.get_subcategories(parent or None)

        var = tk.StringVar(value=current)
        combo = ttk.Combobox(self._view_tree, textvariable=var,
                             values=values, font=STYLE["font"])
        combo.place(x=x, y=y, width=w, height=h)
        combo.focus_set()

        def _commit(_e=None):
            db.set_transaction_classification(int(row_iid), field,
                                              var.get().strip(), apply_to_name=True)
            combo.destroy()
            self._populate_view()

        def _cancel(_e=None):
            combo.destroy()

        combo.bind("<Return>", _commit)
        combo.bind("<<ComboboxSelected>>", _commit)
        combo.bind("<Escape>", _cancel)
        combo.bind("<FocusOut>", _commit)

    # ── Tab focus hook ─────────────────────────────────────────────────────

    def refresh(self):
        if self._mode.get() == "log":
            self._refresh_accounts()
            self._refresh_imports()
        else:
            self._refresh_view_accounts()
            self._populate_view()
