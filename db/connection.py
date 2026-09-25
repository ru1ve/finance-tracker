"""
db/connection.py — SQLite connection management and schema initialisation.
"""
from __future__ import annotations

import sys
import sqlite3
from pathlib import Path
from contextlib import contextmanager
import datetime


def _db_dir() -> Path:
    # PyInstaller onefile: sys.executable is the .exe; use its directory
    # so the database lives next to the exe, not in the temp extraction folder.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


DB_DIR  = _db_dir()
DB_PATH = DB_DIR / "finance.db"


def list_db_files() -> list[Path]:
    """Return all *.db files in the same directory as the exe / script."""
    return sorted(DB_DIR.glob("*.db"))


def set_db_path(path: Path) -> None:
    """Override DB_PATH before init_db() is called."""
    global DB_PATH
    DB_PATH = Path(path)


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

    # Settings table
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        """)

    # Income tables
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS income_sources (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS income (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_date  TEXT NOT NULL,
                amount      REAL NOT NULL,
                source      TEXT,
                subcategory TEXT,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)

    # Mortgage persistence tables
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS mortgage_fixed (
                key   TEXT PRIMARY KEY,
                value REAL NOT NULL DEFAULT 0.0
            );

            CREATE TABLE IF NOT EXISTS mortgage_income_items (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                label      TEXT NOT NULL DEFAULT '',
                amount     REAL NOT NULL DEFAULT 0.0,
                sort_order INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS mortgage_expense_items (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                label      TEXT NOT NULL DEFAULT '',
                amount     REAL NOT NULL DEFAULT 0.0,
                sort_order INTEGER NOT NULL DEFAULT 0
            );
        """)

    # Spending / statement-import tables
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS spending_imports (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id  INTEGER NOT NULL REFERENCES accounts(id),
                filename    TEXT NOT NULL,
                source      TEXT,
                uploaded_at TEXT NOT NULL DEFAULT (datetime('now')),
                row_count   INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS spending_transactions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id  INTEGER NOT NULL REFERENCES accounts(id),
                import_id   INTEGER REFERENCES spending_imports(id),
                txn_date    TEXT NOT NULL,
                name        TEXT NOT NULL DEFAULT '',
                description TEXT,
                amount      REAL NOT NULL DEFAULT 0.0,
                category    TEXT,
                subcategory TEXT,
                ext_id      TEXT,
                dedupe_hash TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS spending_name_categories (
                name        TEXT PRIMARY KEY,
                category    TEXT,
                subcategory TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_sp_txn_account
                ON spending_transactions(account_id, txn_date);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_sp_txn_dedupe
                ON spending_transactions(account_id, dedupe_hash);
        """)

        # Migration: add sub-category columns to spending tables created earlier.
        txn_cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(spending_transactions)").fetchall()]
        if "subcategory" not in txn_cols:
            conn.execute("ALTER TABLE spending_transactions ADD COLUMN subcategory TEXT")
        nc_cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(spending_name_categories)").fetchall()]
        if "subcategory" not in nc_cols:
            conn.execute("ALTER TABLE spending_name_categories ADD COLUMN subcategory TEXT")
