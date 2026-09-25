"""
db/accounts.py — Account CRUD and spending-category management.
"""
from __future__ import annotations

import datetime

from db.connection import get_conn


def get_product_types() -> list:
    """Returns all account product type names, sorted."""
    with get_conn() as conn:
        return [r["name"] for r in conn.execute(
            "SELECT name FROM account_product_types ORDER BY name"
        ).fetchall()]


def add_product_type(name: str):
    """Add a new product type (ignored if it already exists)."""
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO account_product_types (name) VALUES (?)", (name,))


def get_all_accounts(include_inactive=False):
    with get_conn() as conn:
        sql = "SELECT * FROM accounts"
        if not include_inactive:
            sql += " WHERE is_active = 1"
        sql += " ORDER BY bank, account_name"
        return [dict(r) for r in conn.execute(sql).fetchall()]


def get_account_by_id(account_id):
    with get_conn() as conn:
        return dict(conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone())


def upsert_account(account_name, bank, account_type, category,
                   max_balance_for_rate, interest_rate, allocations: dict,
                   effective_from=None, note=None, product_type=None):
    """Insert or update account. allocations is {category_name: fraction}."""
    if effective_from is None:
        effective_from = datetime.date.today().isoformat()

    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM accounts WHERE account_name=?", (account_name,)
        ).fetchone()

        if existing:
            account_id = existing["id"]
            conn.execute("""
                UPDATE accounts SET bank=?, account_type=?, category=?,
                max_balance_for_rate=?, product_type=? WHERE id=?
            """, (bank, account_type, category, max_balance_for_rate, product_type, account_id))
        else:
            cur = conn.execute("""
                INSERT INTO accounts (account_name, bank, account_type, category, max_balance_for_rate, product_type)
                VALUES (?,?,?,?,?,?)
            """, (account_name, bank, account_type, category, max_balance_for_rate, product_type))
            account_id = cur.lastrowid

        # Append new rate entry
        conn.execute("""
            INSERT INTO account_rates (account_id, interest_rate, effective_from, note)
            VALUES (?,?,?,?)
        """, (account_id, interest_rate or 0.0, effective_from, note))

        # Append new allocation entries
        cats = {r["name"]: r["id"] for r in
                conn.execute("SELECT id, name FROM spending_categories").fetchall()}
        for cat_name, val in allocations.items():
            cat_id = cats.get(cat_name)
            if cat_id is None:
                continue
            if isinstance(val, dict):
                pct, fixed = val.get("pct", 0.0), val.get("fixed", 0.0)
            else:
                pct, fixed = float(val), 0.0
            conn.execute("""
                INSERT INTO account_allocations
                    (account_id, category_id, allocation, fixed_amount, effective_from, note)
                VALUES (?,?,?,?,?,?)
            """, (account_id, cat_id, pct, fixed, effective_from, note))

    return account_id


def deactivate_account(account_id):
    with get_conn() as conn:
        conn.execute("UPDATE accounts SET is_active=0 WHERE id=?", (account_id,))


def update_account_details(account_id: int, bank: str | None, account_type: str | None,
                           account_name: str, product_type: str | None,
                           max_balance_for_rate: float | None,
                           category: str | None = None):
    """Update the core editable fields on an account row."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE accounts SET bank=?, account_type=?, account_name=?,"
            " product_type=?, max_balance_for_rate=?, category=? WHERE id=?",
            (bank or None, account_type or None, account_name,
             product_type or None, max_balance_for_rate, category, account_id),
        )


def update_account_product_type(account_id: int, product_type):
    with get_conn() as conn:
        conn.execute("UPDATE accounts SET product_type=? WHERE id=?",
                     (product_type, account_id))


def update_account_category(account_id: int, category):
    with get_conn() as conn:
        conn.execute("UPDATE accounts SET category=? WHERE id=?",
                     (category, account_id))


def reactivate_account(account_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE accounts SET is_active=1 WHERE id=?", (account_id,))


def get_account_categories() -> list:
    """Returns all distinct category values used by accounts."""
    with get_conn() as conn:
        return [r["category"] for r in conn.execute(
            "SELECT DISTINCT category FROM accounts WHERE category IS NOT NULL ORDER BY category"
        ).fetchall()]


def get_spending_categories() -> list:
    """Returns [{'id': ..., 'name': ...}] in display order."""
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, name FROM spending_categories ORDER BY id"
        ).fetchall()]


def add_spending_category(name: str) -> None:
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO spending_categories (name) VALUES (?)", (name,))


def delete_spending_category(category_id: int) -> None:
    """Delete a category and all account allocations that reference it."""
    with get_conn() as conn:
        conn.execute("DELETE FROM account_allocations WHERE category_id=?", (category_id,))
        conn.execute("DELETE FROM spending_categories WHERE id=?", (category_id,))


def get_spending_category_names() -> list:
    """Returns the list of spending category names in display order."""
    with get_conn() as conn:
        return [r["name"] for r in conn.execute(
            "SELECT name FROM spending_categories ORDER BY id"
        ).fetchall()]


def import_from_json(json_path: str):
    import json
    from db.snapshots import save_snapshot

    with open(json_path) as f:
        data = json.load(f)

    name_to_id = {}
    for acc in data["accounts"]:
        allocations = {
            "Spending":          acc.get("alloc_spending", 0.0) or 0.0,
            "Deposit":           acc.get("alloc_deposit", 0.0) or 0.0,
            "Emergency Fund":    acc.get("alloc_emergency", 0.0) or 0.0,
            "Long Term Savings": acc.get("alloc_longterm", 0.0) or 0.0,
            "Pension":           acc.get("alloc_pension", 0.0) or 0.0,
        }
        acc_id = upsert_account(
            account_name=acc["account_name"],
            bank=acc["bank"],
            account_type=acc["account_type"],
            category=acc["category"],
            max_balance_for_rate=acc.get("max_balance_for_rate"),
            interest_rate=acc.get("interest_rate") or 0.0,
            allocations=allocations,
            effective_from="2023-01-01",
            note="Imported from spreadsheet",
        )
        name_to_id[acc["account_name"]] = acc_id

    with get_conn() as conn:
        all_accs = {r["account_name"]: r["id"] for r in
                    conn.execute("SELECT id, account_name FROM accounts").fetchall()}

    for snap in data["snapshots"]:
        date_str = snap["date"]
        balances = {}
        for acc_name, balance in snap["balances"].items():
            acc_id = all_accs.get(acc_name)
            if acc_id:
                balances[acc_id] = balance
        if balances:
            save_snapshot(date_str, balances)

    return len(data["accounts"]), len(data["snapshots"])
