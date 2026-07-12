# Personal Finance Tracker

A Python desktop app for tracking personal finances.  
**SQLite backend · tkinter UI · matplotlib charts**

---

## Requirements

- Python 3.9+
- `matplotlib` — the only third-party dependency

tkinter and sqlite3 ship with Python.

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Run the app

```bash
python app.py
```

`finance.db` is created automatically on first run in the same folder as `app.py`.

---

## Tabs

| Tab | What it does |
|-----|-------------|
| **Dashboard** | Net worth cards, current balances with spending allocations. Add accounts, update product type, deactivate/reactivate. |
| **Log Snapshot** | Enter all account balances for a date. Click an empty balance field to pre-fill from the last recorded value — start typing to override. |
| **History** | Stacked charts by account or spending category, with time-range filters (ALL / 2Y / 1Y / 6M / 3M / YTD). Click a legend entry to drill into that category's account breakdown. Hover for a balance tooltip. |
| **Categories** | Current allocation pie chart and breakdown table. |
| **Interest** | Yearly / daily interest per account and forward projection N months. |
| **Mortgage** | Affordability estimator using Deposit-allocated funds as deposit. |
| **Rec. Balances** | Pivot table — accounts across the top (grouped by bank), dates down the side (newest first), raw recorded balances in the cells. |

---

## Effective-dated rates & allocations

When you change an account's interest rate or spending allocation, a new entry is added with an **effective from** date. The app looks up the rate/allocation in effect *on the date of each snapshot*, so:

- Old history is never affected by today's changes
- You can backdate a correction if you forgot to record it on time

---

## Balance semantics

- **Blank / no entry** — nothing recorded; the app carries the last known balance forward for active accounts
- **£0.00** — explicitly recorded as zero (e.g. account emptied)
- Inactive accounts only contribute to history on dates they have actual entries

---

## Database

`finance.db` sits next to `app.py`. It's plain SQLite — back it up like any file, or browse it with [DB Browser for SQLite](https://sqlitebrowser.org/).

---

## Mortgage estimator notes

Uses:
- **Deposit**: sum of balances × `Deposit` allocation fraction from the latest snapshot
- **Max borrowing**: 4× and 4.5× combined income (standard UK lender multiples)
- **Stress test**: max affordable at 7% over 25 years (BoE stress test rate)

Rough guide only — not financial advice.
