"""
db/income.py — Income records and interest-rate helpers.
"""
from __future__ import annotations

import datetime

from db.connection import get_conn
from db.snapshots import get_latest_balance_per_account
from db.accounts import get_all_accounts


def _get_rates_on_date(date_str: str) -> dict:
    """Returns {account_id: rate} for all accounts as of date_str in one query."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT ar.account_id, ar.interest_rate
            FROM account_rates ar
            WHERE ar.effective_from = (
                SELECT MAX(effective_from) FROM account_rates
                WHERE account_id = ar.account_id AND effective_from <= ?
            )
        """, (date_str,)).fetchall()
        return {r["account_id"]: r["interest_rate"] for r in rows}


def get_current_interest_summary():
    """Returns list of {account_name, balance, rate, yearly, daily} for active accounts."""
    date_str = datetime.date.today().isoformat()
    snapshot = get_latest_balance_per_account()
    accounts = get_all_accounts()
    rates = _get_rates_on_date(date_str)
    result = []
    for acc in accounts:
        acc_id = acc["id"]
        balance = snapshot.get(acc_id, 0.0)
        rate = rates.get(acc_id, 0.0)
        yearly = balance * rate if balance > 0 else 0.0
        result.append({
            "account_name": acc["account_name"],
            "bank": acc["bank"],
            "category": acc["category"],
            "balance": balance,
            "rate": rate,
            "yearly_interest": yearly,
            "daily_interest": yearly / 365,
        })
    return sorted(result, key=lambda x: x["yearly_interest"], reverse=True)


def save_account_rate(account_id: int, rate: float, effective_from: str, note: str = None):
    """Insert a new effective-dated rate entry for an account."""
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO account_rates (account_id, interest_rate, effective_from, note)
            VALUES (?,?,?,?)
        """, (account_id, rate, effective_from, note))


def get_income_sources() -> list:
    with get_conn() as conn:
        return [r["name"] for r in
                conn.execute("SELECT name FROM income_sources ORDER BY name").fetchall()]


def get_income_sub_sources(source: str | None = None) -> list:
    """Return distinct subcategory values used under the given source (or all if None)."""
    with get_conn() as conn:
        if source:
            rows = conn.execute(
                "SELECT DISTINCT subcategory FROM income"
                " WHERE source=? AND subcategory IS NOT NULL ORDER BY subcategory",
                (source,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT subcategory FROM income"
                " WHERE subcategory IS NOT NULL ORDER BY subcategory"
            ).fetchall()
    return [r["subcategory"] for r in rows]


def add_income_source(name: str) -> None:
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO income_sources (name) VALUES (?)", (name,))


def add_income(entry_date: str, amount: float, source: str | None,
               subcategory: str | None) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO income (entry_date, amount, source, subcategory) VALUES (?,?,?,?)",
            (entry_date, amount, source or None, subcategory or None),
        )
        if source:
            conn.execute("INSERT OR IGNORE INTO income_sources (name) VALUES (?)", (source,))
        return cur.lastrowid


def get_all_income() -> list:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT id, entry_date, amount, source, subcategory, created_at
            FROM income ORDER BY entry_date DESC, id DESC
        """).fetchall()
    return [dict(r) for r in rows]


def delete_income(income_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM income WHERE id=?", (income_id,))
