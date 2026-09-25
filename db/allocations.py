"""
db/allocations.py — Effective-dated rate and allocation management.
"""
from __future__ import annotations

import datetime

from db.connection import get_conn
from db.snapshots import _last_known_balance


def get_all_allocations_on_date(date_str: str) -> dict:
    """Returns {account_id: {cat_name: {"fixed": x, "pct": y}}} for all accounts as of date_str."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT aa.account_id, sc.name AS cat_name, aa.allocation, aa.fixed_amount
            FROM account_allocations aa
            JOIN spending_categories sc ON sc.id = aa.category_id
            WHERE aa.effective_from = (
                SELECT MAX(effective_from) FROM account_allocations
                WHERE account_id = aa.account_id
                  AND category_id = aa.category_id
                  AND effective_from <= ?
            )
        """, (date_str,)).fetchall()
    from collections import defaultdict
    result: dict = defaultdict(dict)
    for r in rows:
        result[r["account_id"]][r["cat_name"]] = {
            "fixed": r["fixed_amount"] or 0.0,
            "pct": r["allocation"],
        }
    return dict(result)


def get_category_account_breakdown(category_name: str) -> list:
    """Drill-down: returns [{date, accounts: {acc_name: amount}}, ...]
    showing each account's contribution to category_name over time."""
    with get_conn() as conn:
        cats = [r["name"] for r in conn.execute(
            "SELECT name FROM spending_categories ORDER BY id").fetchall()]
        dates = [r["snapshot_date"] for r in conn.execute("""
            SELECT DISTINCT snapshot_date FROM balance_snapshots ORDER BY snapshot_date
        """).fetchall()]
        balance_rows = conn.execute("""
            SELECT account_id, snapshot_date, balance FROM balance_snapshots
            ORDER BY account_id, snapshot_date
        """).fetchall()
        alloc_rows = conn.execute("""
            SELECT aa.account_id, sc.name AS cat_name,
                   aa.allocation, aa.fixed_amount, aa.effective_from
            FROM account_allocations aa
            JOIN spending_categories sc ON sc.id = aa.category_id
            ORDER BY aa.account_id, sc.name, aa.effective_from
        """).fetchall()
        accounts = conn.execute(
            "SELECT id, account_name, is_active FROM accounts").fetchall()

    from collections import defaultdict
    active_ids = {r["id"] for r in accounts if r["is_active"]}
    acc_names  = {r["id"]: r["account_name"] for r in accounts}

    active_histories: dict = defaultdict(list)
    date_snap: dict = defaultdict(dict)
    for row in balance_rows:
        date_snap[row["snapshot_date"]][row["account_id"]] = row["balance"]
        if row["account_id"] in active_ids:
            active_histories[row["account_id"]].append(
                (row["snapshot_date"], row["balance"]))

    alloc_timeline: dict = defaultdict(lambda: defaultdict(list))
    for row in alloc_rows:
        alloc_timeline[row["account_id"]][row["cat_name"]].append(
            (row["effective_from"],
             {"fixed": row["fixed_amount"] or 0.0, "pct": row["allocation"]}))

    def _alloc(account_id, cat_name, date_str):
        val = {"fixed": 0.0, "pct": 0.0}
        for ef, a in alloc_timeline[account_id][cat_name]:
            if ef <= date_str:
                val = a
            else:
                break
        return val

    result = []
    for date_str in dates:
        snap = date_snap.get(date_str, {})
        account_amounts = {}
        for r in accounts:
            acc_id = r["id"]
            balance = (_last_known_balance(active_histories[acc_id], date_str)
                       if r["is_active"] else snap.get(acc_id))
            if not balance:
                continue
            allocs  = {cat: _alloc(acc_id, cat, date_str) for cat in cats}
            amount  = calc_category_amounts(balance, allocs).get(category_name, 0.0)
            if abs(amount) >= 0.01:
                account_amounts[acc_names[acc_id]] = amount
        if account_amounts:
            result.append({"date": date_str, "accounts": account_amounts})
    return result


def get_last_recorded_dates() -> dict:
    """Returns {account_id: last_snapshot_date} for all accounts."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT account_id, MAX(snapshot_date) AS last_date
            FROM balance_snapshots GROUP BY account_id
        """).fetchall()
        return {r["account_id"]: r["last_date"] for r in rows}


def get_rate_on_date(account_id, on_date: str):
    with get_conn() as conn:
        row = conn.execute("""
            SELECT interest_rate FROM account_rates
            WHERE account_id=? AND effective_from <= ?
            ORDER BY effective_from DESC LIMIT 1
        """, (account_id, on_date)).fetchone()
        return row["interest_rate"] if row else 0.0


def get_allocations_on_date(account_id, on_date: str) -> dict:
    """Returns {category_name: {"fixed": £amount, "pct": fraction_of_remainder}} as of on_date."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT sc.name, aa.allocation, aa.fixed_amount
            FROM account_allocations aa
            JOIN spending_categories sc ON sc.id = aa.category_id
            WHERE aa.account_id = ?
              AND aa.effective_from = (
                  SELECT MAX(effective_from) FROM account_allocations
                  WHERE account_id = aa.account_id
                    AND category_id = aa.category_id
                    AND effective_from <= ?
              )
        """, (account_id, on_date)).fetchall()
        return {r["name"]: {"fixed": r["fixed_amount"] or 0.0, "pct": r["allocation"]}
                for r in rows}


def calc_category_amounts(balance: float, allocs: dict) -> dict:
    """
    allocs: {cat_name: {"fixed": £amount, "pct": fraction_of_remainder}}
    Positive balance: fixed amounts assigned first, remainder split by pct.
    Negative balance (debt): distributed proportionally by pct.
    Returns {cat_name: £amount}.
    """
    if not allocs:
        return {}
    if balance >= 0:
        total_fixed = sum(v["fixed"] for v in allocs.values())
        remainder = max(0.0, balance - total_fixed)
        return {cat: v["fixed"] + remainder * v["pct"] for cat, v in allocs.items()}
    total_pct = sum(v["pct"] for v in allocs.values())
    if total_pct > 0:
        return {cat: balance * v["pct"] / total_pct for cat, v in allocs.items()}
    n = len(allocs)
    return {cat: balance / n for cat in allocs}


def save_account_allocation(account_id: int, alloc_data: dict,
                             effective_from: str, note: str = None):
    """
    alloc_data: {cat_name: {"fixed": £amount, "pct": fraction_of_remainder}}
    Inserts a new effective-dated allocation entry for the account.
    """
    with get_conn() as conn:
        cats = {r["name"]: r["id"] for r in
                conn.execute("SELECT id, name FROM spending_categories").fetchall()}
        for cat_name, vals in alloc_data.items():
            cat_id = cats.get(cat_name)
            if cat_id is None:
                continue
            conn.execute("""
                INSERT INTO account_allocations
                    (account_id, category_id, allocation, fixed_amount, effective_from, note)
                VALUES (?,?,?,?,?,?)
            """, (account_id, cat_id, vals["pct"], vals["fixed"], effective_from, note))


def get_current_rate(account_id):
    return get_rate_on_date(account_id, datetime.date.today().isoformat())


def get_rate_history(account_id):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT interest_rate, effective_from, note
            FROM account_rates WHERE account_id=?
            ORDER BY effective_from
        """, (account_id,)).fetchall()]


def get_allocation_history(account_id):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT sc.name as category, aa.allocation, aa.fixed_amount,
                   aa.effective_from, aa.note
            FROM account_allocations aa
            JOIN spending_categories sc ON sc.id = aa.category_id
            WHERE aa.account_id=?
            ORDER BY aa.effective_from, sc.name
        """, (account_id,)).fetchall()]
