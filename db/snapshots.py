"""
db/snapshots.py — Balance snapshot storage and retrieval.
"""
from __future__ import annotations

from db.connection import get_conn


def _last_known_balance(sorted_history: list, date_str: str):
    """Return the most recent balance on or before date_str from a sorted [(date, balance)] list.
    Returns None if there is no recorded entry on or before that date."""
    result = None
    for d, b in sorted_history:
        if d <= date_str:
            result = b
        else:
            break
    return result


def save_snapshot(date_str: str, balances: dict):
    """balances is {account_id: balance_value}. Inserts new rows — multiple per day allowed."""
    with get_conn() as conn:
        for account_id, balance in balances.items():
            conn.execute("""
                INSERT INTO balance_snapshots (account_id, snapshot_date, balance)
                VALUES (?,?,?)
            """, (account_id, date_str, balance))


def get_snapshot_dates():
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT DISTINCT snapshot_date FROM balance_snapshots
            ORDER BY snapshot_date DESC
        """).fetchall()
        return [r["snapshot_date"] for r in rows]


def get_snapshot(date_str: str):
    """Returns {account_id: balance} for the given date."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT account_id, balance FROM balance_snapshots WHERE snapshot_date=?
        """, (date_str,)).fetchall()
        return {r["account_id"]: r["balance"] for r in rows}


def get_latest_snapshot():
    dates = get_snapshot_dates()
    if not dates:
        return None, {}
    return dates[0], get_snapshot(dates[0])


def get_latest_balance_per_account() -> dict:
    """Returns {account_id: balance} using each account's own most recent snapshot entry."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT bs.account_id, bs.balance
            FROM balance_snapshots bs
            WHERE bs.snapshot_date = (
                SELECT MAX(snapshot_date) FROM balance_snapshots
                WHERE account_id = bs.account_id
            )
        """).fetchall()
        return {r["account_id"]: r["balance"] for r in rows}


def get_snapshot_with_names(date_str: str) -> list:
    """Returns [{account_id, account_name, balance}] for a specific date, ordered by name."""
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT bs.account_id, a.account_name, bs.balance
            FROM balance_snapshots bs
            JOIN accounts a ON a.id = bs.account_id
            WHERE bs.snapshot_date = ?
            ORDER BY a.bank, a.account_name
        """, (date_str,)).fetchall()]


def delete_snapshot_date(date_str: str):
    """Delete all balance entries for a snapshot date."""
    with get_conn() as conn:
        conn.execute("DELETE FROM balance_snapshots WHERE snapshot_date=?", (date_str,))


def delete_snapshot_entry(account_id: int, date_str: str):
    """Delete one account's entry for a snapshot date."""
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM balance_snapshots WHERE account_id=? AND snapshot_date=?",
            (account_id, date_str)
        )


def update_balance_entry(account_id: int, date_str: str, new_balance: float):
    """Update the balance for a specific account / date entry."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE balance_snapshots SET balance=? WHERE account_id=? AND snapshot_date=?",
            (new_balance, account_id, date_str)
        )


def get_balance_history(account_id):
    """Returns [(date, balance), ...] ordered chronologically."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT snapshot_date, balance FROM balance_snapshots
            WHERE account_id=? ORDER BY snapshot_date
        """, (account_id,)).fetchall()
        return [(r["snapshot_date"], r["balance"]) for r in rows]
