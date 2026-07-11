"""
import_data.py — One-time migration from the exported spreadsheet JSON.
Run this once before launching app.py.

Usage:
    python import_data.py [path/to/Finance.xlsx]

If no path is given, looks for Finance__4_.xlsx in the same directory.
"""

import sys
import re
import json
import datetime
from pathlib import Path

def extract_from_xlsx(xlsx_path: str):
    from openpyxl import load_workbook
    wb = load_workbook(xlsx_path, read_only=True)

    # --- Accounts ---
    ws_acc = wb['Accounts']
    accounts = []
    rows = list(ws_acc.iter_rows(max_row=40, values_only=True))
    for row in rows[1:]:
        name = row[5]
        if not name or not isinstance(name, str):
            continue
        accounts.append({
            "bank":            row[0],
            "account_type":    row[1],
            "category":        row[2],
            "interest_rate":   row[3],
            "max_balance_for_rate": row[4],
            "account_name":    name,
            "balance":         row[6] if isinstance(row[6], (int, float)) else 0.0,
            "alloc_spending":  row[9]  if isinstance(row[9],  (int, float)) else 0.0,
            "alloc_deposit":   row[10] if isinstance(row[10], (int, float)) else 0.0,
            "alloc_emergency": row[11] if isinstance(row[11], (int, float)) else 0.0,
            "alloc_longterm":  row[12] if isinstance(row[12], (int, float)) else 0.0,
            "alloc_pension":   row[13] if isinstance(row[13], (int, float)) else 0.0,
        })

    # --- Balances header ---
    ws_bal = wb['Balances']
    bal_rows = list(ws_bal.iter_rows(values_only=True))
    header_row = bal_rows[0]

    account_headers = []
    for cell in header_row[2:]:
        if cell is None:
            break
        if isinstance(cell, str):
            m = re.search(r',\s*"([^"]+)"\s*\)\s*$', cell)
            account_headers.append(m.group(1) if m else cell)
        else:
            account_headers.append(str(cell))

    # --- Snapshot rows ---
    snapshots = []
    for row in bal_rows[1:]:
        date_val = row[1]
        if not isinstance(date_val, datetime.datetime):
            continue
        balances = {}
        for i, acc_name in enumerate(account_headers):
            val = row[i + 2]
            if isinstance(val, (int, float)):
                balances[acc_name] = val
        if balances:
            snapshots.append({
                "date":     date_val.strftime("%Y-%m-%d"),
                "balances": balances,
            })

    return {"accounts": accounts, "snapshots": snapshots}


def main():
    script_dir = Path(__file__).parent

    if len(sys.argv) > 1:
        xlsx_path = sys.argv[1]
    else:
        # Look for any xlsx in the same directory
        candidates = list(script_dir.glob("*.xlsx"))
        if not candidates:
            print("ERROR: No .xlsx file found. Pass the path as an argument.")
            sys.exit(1)
        xlsx_path = str(candidates[0])

    print(f"Reading: {xlsx_path}")
    data = extract_from_xlsx(xlsx_path)
    print(f"  Found {len(data['accounts'])} accounts, {len(data['snapshots'])} snapshots")

    # Write temp JSON (import_from_json is simpler)
    tmp = script_dir / "_import_tmp.json"
    with open(tmp, "w") as f:
        json.dump(data, f, default=str)

    # Import into DB
    import db
    db.init_db()
    n_acc, n_snap = db.import_from_json(str(tmp))
    tmp.unlink()

    print(f"Imported: {n_acc} accounts, {n_snap} snapshots → finance.db")
    print("Done. You can now run:  python app.py")


if __name__ == "__main__":
    main()
