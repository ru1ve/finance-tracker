"""
db/spending.py — persistence for imported spending transactions.

Categories are never guessed: they are learned per transaction *name* via
spending_name_categories, and applied to every matching transaction.
"""
from __future__ import annotations

from db.connection import get_conn
from db.statement_parsers import dedupe_hash


def get_name_category_map() -> dict:
    """name → {'category': .., 'subcategory': ..} learned from past labelling."""
    with get_conn() as conn:
        return {r["name"]: {"category": r["category"], "subcategory": r["subcategory"]}
                for r in conn.execute(
                    "SELECT name, category, subcategory "
                    "FROM spending_name_categories").fetchall()}


def existing_hashes(account_id: int) -> set:
    with get_conn() as conn:
        return {r["dedupe_hash"] for r in conn.execute(
            "SELECT dedupe_hash FROM spending_transactions WHERE account_id=?",
            (account_id,)).fetchall()}


def build_preview(account_id: int, parsed: list) -> list:
    """Annotate parsed transactions with dedupe hash, duplicate flag and any
    already-learned category. Does not write anything."""
    existing  = existing_hashes(account_id)
    name_cats = get_name_category_map()
    occ_counter = {}          # base identity → how many seen so far in this file
    seen_in_file = set()
    preview = []
    for t in parsed:
        ext = t.get("ext_id")
        if ext:
            occ = 0
        else:
            base = (t["txn_date"], round(t["amount"], 2), t["name"].strip().lower())
            occ = occ_counter.get(base, 0)
            occ_counter[base] = occ + 1
        h = dedupe_hash(account_id, t["txn_date"], t["amount"],
                        t["name"], ext, occ)
        is_dup = h in existing or h in seen_in_file
        seen_in_file.add(h)
        learned = name_cats.get(t["name"], {})
        preview.append({
            **t,
            "dedupe_hash": h,
            "is_duplicate": is_dup,
            "category": learned.get("category"),
            "subcategory": learned.get("subcategory"),
        })
    return preview


def commit_import(account_id: int, filename: str, source: str, rows: list) -> int:
    """Insert an import batch and its (new) transactions. `rows` are preview
    dicts; duplicates are skipped. Returns the number of transactions added."""
    new_rows = [r for r in rows if not r.get("is_duplicate")]
    if not new_rows:
        return 0
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO spending_imports (account_id, filename, source, row_count)"
            " VALUES (?,?,?,?)",
            (account_id, filename, source, len(new_rows)))
        import_id = cur.lastrowid
        conn.executemany(
            "INSERT OR IGNORE INTO spending_transactions"
            " (account_id, import_id, txn_date, name, description, amount,"
            "  category, subcategory, ext_id, dedupe_hash)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(account_id, import_id, r["txn_date"], r["name"],
              r.get("description"), r["amount"], r.get("category"),
              r.get("subcategory"), r.get("ext_id"), r["dedupe_hash"])
             for r in new_rows])
    return len(new_rows)


def get_transactions(account_id: int | None = None) -> list:
    with get_conn() as conn:
        sql = ("SELECT t.*, a.account_name FROM spending_transactions t"
               " JOIN accounts a ON a.id = t.account_id")
        params = ()
        if account_id is not None:
            sql += " WHERE t.account_id=?"
            params = (account_id,)
        sql += " ORDER BY t.txn_date DESC, t.id DESC"
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def set_transaction_classification(txn_id: int, field: str, value: str | None,
                                   apply_to_name: bool = True) -> None:
    """Set a transaction's 'category' or 'subcategory'. When apply_to_name is
    True, learn the name→value rule and apply it to every same-named row."""
    if field not in ("category", "subcategory"):
        raise ValueError(f"invalid field: {field}")
    value = (value or "").strip() or None
    with get_conn() as conn:
        row = conn.execute(
            "SELECT name FROM spending_transactions WHERE id=?", (txn_id,)).fetchone()
        if row is None:
            return
        name = row["name"]
        if apply_to_name:
            conn.execute(
                f"INSERT INTO spending_name_categories (name, {field}) VALUES (?,?)"
                f" ON CONFLICT(name) DO UPDATE SET {field}=excluded.{field}",
                (name, value))
            conn.execute(
                f"UPDATE spending_transactions SET {field}=? WHERE name=?",
                (value, name))
        else:
            conn.execute(
                f"UPDATE spending_transactions SET {field}=? WHERE id=?",
                (value, txn_id))


def get_categories() -> list:
    """Distinct categories already in use (for a picker)."""
    with get_conn() as conn:
        return [r["category"] for r in conn.execute(
            "SELECT DISTINCT category FROM spending_transactions"
            " WHERE category IS NOT NULL AND category<>'' ORDER BY category").fetchall()]


def get_subcategories(category: str | None = None) -> list:
    """Distinct sub-categories, optionally filtered to a parent category."""
    with get_conn() as conn:
        if category:
            rows = conn.execute(
                "SELECT DISTINCT subcategory FROM spending_transactions"
                " WHERE subcategory IS NOT NULL AND subcategory<>'' AND category=?"
                " ORDER BY subcategory", (category,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT subcategory FROM spending_transactions"
                " WHERE subcategory IS NOT NULL AND subcategory<>''"
                " ORDER BY subcategory").fetchall()
        return [r["subcategory"] for r in rows]


def get_imports(account_id: int | None = None) -> list:
    with get_conn() as conn:
        sql = ("SELECT i.*, a.account_name FROM spending_imports i"
               " JOIN accounts a ON a.id = i.account_id")
        params = ()
        if account_id is not None:
            sql += " WHERE i.account_id=?"
            params = (account_id,)
        sql += " ORDER BY i.uploaded_at DESC, i.id DESC"
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def delete_import(import_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM spending_transactions WHERE import_id=?", (import_id,))
        conn.execute("DELETE FROM spending_imports WHERE id=?", (import_id,))
