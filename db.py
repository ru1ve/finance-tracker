"""
db.py — SQLite schema and all data-access functions.

Schema design notes:
  - account_rates and account_allocations are effective-dated so changing
    them now does NOT rewrite history. A lookup always finds the row WHERE
    effective_from <= snapshot_date ORDER BY effective_from DESC LIMIT 1.
  - balance_snapshots stores one row per (date, account). The app always
    writes all accounts on each snapshot date.
  - spending_categories is the master list of allocation buckets.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from contextlib import contextmanager
import datetime

DB_PATH = Path(__file__).parent / "finance.db"


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            account_name    TEXT NOT NULL UNIQUE,
            bank            TEXT,
            account_type    TEXT,
            category        TEXT,
            max_balance_for_rate REAL,
            is_active       INTEGER NOT NULL DEFAULT 1,
            created_at      TEXT NOT NULL DEFAULT (date('now'))
        );

        CREATE TABLE IF NOT EXISTS account_product_types (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS account_rates (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id      INTEGER NOT NULL REFERENCES accounts(id),
            interest_rate   REAL NOT NULL DEFAULT 0.0,
            effective_from  TEXT NOT NULL,
            note            TEXT
        );

        CREATE TABLE IF NOT EXISTS spending_categories (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            name    TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS account_allocations (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id      INTEGER NOT NULL REFERENCES accounts(id),
            category_id     INTEGER NOT NULL REFERENCES spending_categories(id),
            allocation      REAL NOT NULL DEFAULT 0.0,
            effective_from  TEXT NOT NULL,
            note            TEXT
        );

        CREATE TABLE IF NOT EXISTS balance_snapshots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id  INTEGER NOT NULL REFERENCES accounts(id),
            snapshot_date TEXT NOT NULL,
            balance     REAL NOT NULL,
            UNIQUE(account_id, snapshot_date)
        );

        CREATE INDEX IF NOT EXISTS idx_snapshots_date
            ON balance_snapshots(snapshot_date);
        CREATE INDEX IF NOT EXISTS idx_rates_account
            ON account_rates(account_id, effective_from);
        CREATE INDEX IF NOT EXISTS idx_allocs_account
            ON account_allocations(account_id, effective_from);
        """)

    # Migrations for columns added after initial release
    with get_conn() as conn:
        alloc_cols = [r[1] for r in conn.execute("PRAGMA table_info(account_allocations)").fetchall()]
        if "fixed_amount" not in alloc_cols:
            conn.execute("ALTER TABLE account_allocations ADD COLUMN fixed_amount REAL NOT NULL DEFAULT 0.0")

        acc_cols = [r[1] for r in conn.execute("PRAGMA table_info(accounts)").fetchall()]
        if "product_type" not in acc_cols:
            conn.execute("ALTER TABLE accounts ADD COLUMN product_type TEXT")

    # Migration: drop UNIQUE(account_id, snapshot_date) so multiple entries per day are allowed.
    # SQLite can't DROP UNIQUE constraints; we must recreate the table.
    with get_conn() as conn:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='balance_snapshots'"
        ).fetchone()
        schema = row["sql"] if row else ""
        if "UNIQUE" in schema.upper():
            conn.execute("""
                CREATE TABLE balance_snapshots_new (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id    INTEGER NOT NULL REFERENCES accounts(id),
                    snapshot_date TEXT NOT NULL,
                    balance       REAL NOT NULL
                )
            """)
            conn.execute("""
                INSERT INTO balance_snapshots_new (id, account_id, snapshot_date, balance)
                SELECT id, account_id, snapshot_date, balance FROM balance_snapshots
            """)
            conn.execute("DROP TABLE balance_snapshots")
            conn.execute("ALTER TABLE balance_snapshots_new RENAME TO balance_snapshots")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_snapshots_date ON balance_snapshots(snapshot_date)"
            )

    # Seed default spending categories if empty
    with get_conn() as conn:
        existing = conn.execute("SELECT COUNT(*) FROM spending_categories").fetchone()[0]
        if existing == 0:
            for cat in ["Spending", "Deposit", "Emergency Fund", "Long Term Savings", "Pension"]:
                conn.execute("INSERT INTO spending_categories (name) VALUES (?)", (cat,))

    # Seed default account product types if empty
    with get_conn() as conn:
        existing = conn.execute("SELECT COUNT(*) FROM account_product_types").fetchone()[0]
        if existing == 0:
            for pt in ["Cash", "Current", "LISA", "Stocks & Shares ISA", "Savings", "Pension"]:
                conn.execute("INSERT INTO account_product_types (name) VALUES (?)", (pt,))


# ---------------------------------------------------------------------------
# Account helpers
# ---------------------------------------------------------------------------

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
        # allocations may be {cat: fraction} (legacy) or {cat: {"fixed": x, "pct": y}}
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


def update_account_product_type(account_id: int, product_type):
    with get_conn() as conn:
        conn.execute("UPDATE accounts SET product_type=? WHERE id=?",
                     (product_type, account_id))


# ---------------------------------------------------------------------------
# Rate / allocation lookup (effective-dated)
# ---------------------------------------------------------------------------

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
    Fixed amounts are assigned first; remainder is split by pct.
    Returns {cat_name: £amount}.
    """
    total_fixed = sum(v["fixed"] for v in allocs.values())
    remainder = max(0.0, balance - total_fixed)
    return {cat: v["fixed"] + remainder * v["pct"] for cat, v in allocs.items()}


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


# ---------------------------------------------------------------------------
# Balance snapshots
# ---------------------------------------------------------------------------

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
    """Returns {account_id: balance} using each account's own most recent snapshot entry.
    Unlike get_latest_snapshot() this works correctly when accounts are partially recorded."""
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


def get_balance_history(account_id):
    """Returns [(date, balance), ...] ordered chronologically."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT snapshot_date, balance FROM balance_snapshots
            WHERE account_id=? ORDER BY snapshot_date
        """, (account_id,)).fetchall()
        return [(r["snapshot_date"], r["balance"]) for r in rows]


def get_net_worth_history():
    """Returns [(date, total_balance), ...] ordered chronologically in one query."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT snapshot_date, SUM(balance) AS total
            FROM balance_snapshots
            GROUP BY snapshot_date
            ORDER BY snapshot_date
        """).fetchall()
        return [(r["snapshot_date"], r["total"]) for r in rows]


def get_all_balance_histories():
    """Returns {account_id: [(date, balance), ...]} for all accounts in one query."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT account_id, snapshot_date, balance FROM balance_snapshots
            ORDER BY account_id, snapshot_date
        """).fetchall()
    from collections import defaultdict
    result: dict = defaultdict(list)
    for r in rows:
        result[r["account_id"]].append((r["snapshot_date"], r["balance"]))
    return result


def save_account_rate(account_id: int, rate: float, effective_from: str, note: str = None):
    """Insert a new effective-dated rate entry for an account."""
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO account_rates (account_id, interest_rate, effective_from, note)
            VALUES (?,?,?,?)
        """, (account_id, rate, effective_from, note))


# ---------------------------------------------------------------------------
# Category history (effective-dated allocations applied to historical balances)
# ---------------------------------------------------------------------------

def get_category_history():
    """
    Returns a list of dicts, one per snapshot date:
    {date, totals: {category_name: value}, grand_total}
    Allocations are looked up as-of each snapshot date.
    All data is loaded in a single connection to avoid N+1 query overhead.
    """
    with get_conn() as conn:
        cats = [r["name"] for r in
                conn.execute("SELECT name FROM spending_categories ORDER BY id").fetchall()]
        dates = [r["snapshot_date"] for r in conn.execute("""
            SELECT DISTINCT snapshot_date FROM balance_snapshots ORDER BY snapshot_date
        """).fetchall()]

        # All balances: {date: {account_id: balance}}
        all_balances: dict = {}
        for row in conn.execute(
            "SELECT snapshot_date, account_id, balance FROM balance_snapshots"
        ).fetchall():
            all_balances.setdefault(row["snapshot_date"], {})[row["account_id"]] = row["balance"]

        # All allocations sorted by effective_from so we can do a forward scan
        alloc_rows = conn.execute("""
            SELECT aa.account_id, sc.name AS cat_name,
                   aa.allocation, aa.fixed_amount, aa.effective_from
            FROM account_allocations aa
            JOIN spending_categories sc ON sc.id = aa.category_id
            ORDER BY aa.account_id, sc.name, aa.effective_from
        """).fetchall()

        account_ids = [r["id"] for r in conn.execute("SELECT id FROM accounts").fetchall()]

    # Build {account_id: {cat_name: [(effective_from, {fixed, pct}), ...]}} — already sorted
    from collections import defaultdict
    alloc_timeline: dict = defaultdict(lambda: defaultdict(list))
    for row in alloc_rows:
        alloc_timeline[row["account_id"]][row["cat_name"]].append(
            (row["effective_from"], {"fixed": row["fixed_amount"] or 0.0, "pct": row["allocation"]})
        )

    def _alloc(account_id, cat_name, date_str):
        entries = alloc_timeline[account_id][cat_name]
        val = {"fixed": 0.0, "pct": 0.0}
        for ef, a in entries:
            if ef <= date_str:
                val = a
            else:
                break
        return val

    result = []
    for date_str in dates:
        snap = all_balances.get(date_str, {})
        totals = {c: 0.0 for c in cats}
        for acc_id in account_ids:
            balance = snap.get(acc_id, 0.0)
            if balance == 0.0:
                continue
            allocs = {cat: _alloc(acc_id, cat, date_str) for cat in cats}
            amounts = calc_category_amounts(balance, allocs)
            for cat, amount in amounts.items():
                totals[cat] += amount
        grand_total = sum(totals.values())
        result.append({"date": date_str, "totals": totals, "grand_total": grand_total})
    return result


# ---------------------------------------------------------------------------
# Interest calculations
# ---------------------------------------------------------------------------

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
    _, snapshot = get_latest_snapshot()
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


def project_balances(months: int):
    """Simple projection: apply current interest rates monthly for N months."""
    date_str = datetime.date.today().isoformat()
    _, snapshot = get_latest_snapshot()
    accounts = get_all_accounts()
    rates = _get_rates_on_date(date_str)
    result = []
    for acc in accounts:
        acc_id = acc["id"]
        balance = snapshot.get(acc_id, 0.0)
        rate = rates.get(acc_id, 0.0)
        monthly = rate / 12
        projected = balance * ((1 + monthly) ** months) if balance > 0 else balance
        result.append({
            "account_name": acc["account_name"],
            "category": acc["category"],
            "current": balance,
            "projected": projected,
            "gain": projected - balance,
        })
    return result


# ---------------------------------------------------------------------------
# Mortgage calculator — mirrors the Mortgage sheet logic exactly
# ---------------------------------------------------------------------------

def calc_scottish_net_salary(gross: float) -> float:
    """
    Scottish income tax bands 2024/25 + NI.
    Matches the LET formula in Mortgage!B4.
    """
    tax = (
        0.19 * max(0, min(gross, 15397)  - 12570) +
        0.20 * max(0, min(gross, 27491)  - 15397) +
        0.21 * max(0, min(gross, 43662)  - 27491) +
        0.42 * max(0, min(gross, 75000)  - 43662) +
        0.45 * max(0, min(gross, 125140) - 75000) +
        0.48 * max(0, gross - 125140)
    )
    if gross <= 12570:
        ni = 0.0
    elif gross <= 50270:
        ni = (gross - 12570) * 0.08
    else:
        ni = (50270 - 12570) * 0.08 + (gross - 50270) * 0.02

    return gross - tax - ni


def calc_ltv_rate(boe_base: float, ltv: float) -> float:
    """LTV-tiered spread on top of BoE base. Matches Mortgage!B16 / D11."""
    spread = (
        0.000 if ltv <= 0.60 else
        0.003 if ltv <= 0.75 else
        0.005 if ltv <= 0.85 else
        0.007 if ltv <= 0.90 else
        0.009
    )
    return boe_base + spread


def calc_monthly_payment(principal: float, annual_rate: float, years: int) -> float:
    """Standard PMT formula."""
    if principal <= 0:
        return 0.0
    r = annual_rate / 12
    n = years * 12
    if r == 0:
        return principal / n
    return principal * r / (1 - (1 + r) ** -n)


def calc_next_ltv_band(ltv: float) -> float | str:
    """Returns the next lower LTV band threshold, or a string if already at best."""
    if ltv <= 0.60:
        return "Already at best band"
    elif ltv <= 0.75:
        return 0.60
    elif ltv <= 0.85:
        return 0.75
    elif ltv <= 0.90:
        return 0.85
    else:
        return 0.90


def calc_salary_required(shortfall_annual: float, bonus: float,
                          pension: float, current_gross: float) -> float:
    """
    How much gross salary is needed to break even.
    Uses marginal keep rate at the current gross band.
    Mirrors Mortgage!D6 LET formula.
    """
    bands = [12570, 15397, 27491, 43662, 50270, 75000, 125140]
    keeps = [1.0,   0.73,  0.72,  0.71,  0.50,  0.56,  0.53,   0.50]
    marginal_keep = keeps[-1]
    for i, band in enumerate(bands):
        if current_gross <= band:
            marginal_keep = keeps[i]
            break

    extra_gross_needed = shortfall_annual / marginal_keep / (1 - pension)
    return current_gross / (1 - pension) + extra_gross_needed


def mortgage_estimate(
    annual_income: float,
    bonus: float = 605.0,
    pension_pct: float = 0.06,
    lodger_monthly: float = 525.0,
    property_price: float = 200000.0,
    overbid_rate: float = 0.05,
    fees: float = 5000.0,
    boe_rate: float = 0.0375,
    term_years: int = 20,
    expenses: dict = None,
):
    """
    Full mortgage affordability calculation matching the Mortgage sheet.

    expenses: dict of {label: monthly_amount} for the monthly outgoings table.
              Defaults to the values from the spreadsheet.
    """
    if expenses is None:
        expenses = {
            "Food + Essentials": 350.0,
            "Fun":               500.0,
            "Utility":            80.0,
            "Wifi":               25.0,
            "Holidays":          250.0,
            "Savings":           250.0,
            "Home Insurance":     25.0,
            "Transport + Car":   150.0,
            "Council Tax Band C":200.0,
            "AI":                 20.0,
            "Monzo Max":          17.0,
            "Climbing Gym":       39.0,
            "Emergency Fund":    200.0,
        }

    # --- Income ---
    gross = (annual_income + bonus) * (1 - pension_pct)
    net_annual = calc_scottish_net_salary(gross)
    net_monthly = net_annual / 12

    # --- Deposit ---
    _, snapshot = get_latest_snapshot()
    accounts = get_all_accounts()
    today = datetime.date.today().isoformat()
    deposit_raw = 0.0
    for acc in accounts:
        acc_id = acc["id"]
        balance = snapshot.get(acc_id, 0.0)
        allocs = get_allocations_on_date(acc_id, today)
        amounts = calc_category_amounts(balance, allocs)
        deposit_raw += amounts.get("Deposit", 0.0)

    overbid_amount   = property_price * overbid_rate
    deposit_after    = deposit_raw - overbid_amount - fees

    # --- Mortgage ---
    mortgage_amount  = property_price - deposit_after
    ltv              = mortgage_amount / property_price if property_price > 0 else 0
    interest_rate    = calc_ltv_rate(boe_rate, ltv)
    monthly_mortgage = calc_monthly_payment(mortgage_amount, interest_rate, term_years)
    est_borrow       = annual_income * 4.5

    # --- Monthly budget ---
    total_expenses   = sum(expenses.values()) + monthly_mortgage
    # Net income includes lodger
    total_net_monthly = net_monthly + lodger_monthly
    gross_income_remaining = total_net_monthly - total_expenses  # positive = surplus

    # --- Next LTV band ---
    next_band = calc_next_ltv_band(ltv)
    if isinstance(next_band, float):
        property_value_at_current_ltv = deposit_after / (1 - ltv) if ltv < 1 else 0
        additional_deposit_needed = property_value_at_current_ltv * (ltv - next_band)
        next_ltv_label = f"{next_band*100:.0f}%"
        next_ltv_rate  = calc_ltv_rate(boe_rate, next_band)
        next_ltv_monthly = calc_monthly_payment(
            property_price * next_band, next_ltv_rate, term_years)
    else:
        additional_deposit_needed = 0.0
        next_ltv_label = next_band
        next_ltv_rate  = interest_rate
        next_ltv_monthly = monthly_mortgage

    # --- Salary required to break even ---
    shortfall_annual = gross_income_remaining * 12  # negative if in deficit
    current_gross_for_calc = (annual_income + bonus) * (1 - pension_pct)
    salary_required = calc_salary_required(
        -shortfall_annual, bonus, pension_pct, current_gross_for_calc
    ) if gross_income_remaining < 0 else None

    return {
        # Income
        "gross_taxable":       gross,
        "net_annual":          net_annual,
        "net_monthly":         net_monthly,
        "lodger_monthly":      lodger_monthly,
        "total_net_monthly":   total_net_monthly,
        # Deposit
        "deposit_raw":         deposit_raw,
        "overbid_amount":      overbid_amount,
        "fees":                fees,
        "deposit_after":       deposit_after,
        # Mortgage
        "property_price":      property_price,
        "mortgage_amount":     mortgage_amount,
        "ltv":                 ltv,
        "interest_rate":       interest_rate,
        "monthly_mortgage":    monthly_mortgage,
        "est_borrow_45x":      est_borrow,
        "remaining_vs_est":    mortgage_amount - est_borrow,
        "term_years":          term_years,
        # Budget
        "expenses":            expenses,
        "total_expenses":      total_expenses,
        "monthly_surplus":     gross_income_remaining,
        "salary_required":     salary_required,
        # Next LTV band
        "next_ltv_label":      next_ltv_label,
        "next_ltv_rate":       next_ltv_rate,
        "next_ltv_monthly":    next_ltv_monthly,
        "additional_deposit":  additional_deposit_needed,
    }


# ---------------------------------------------------------------------------
# Import from spreadsheet JSON
# ---------------------------------------------------------------------------

def import_from_json(json_path: str):
    import json
    with open(json_path) as f:
        data = json.load(f)

    cat_map = {"Spending": "Spending", "Deposit": "Deposit",
               "Emergency Fund": "Emergency Fund",
               "Long Term Savings": "Long Term Savings", "Pension": "Pension"}

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

    # Also ensure Historic - Total has an ID
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
