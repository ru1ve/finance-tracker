"""
db/history.py — Net-worth and category history queries.
"""
from __future__ import annotations

from db.connection import get_conn
from db.snapshots import _last_known_balance, get_latest_balance_per_account
from db.allocations import calc_category_amounts, get_allocations_on_date
from db.accounts import get_all_accounts
from db.income import _get_rates_on_date

import datetime


def get_net_worth_history():
    """Returns [(date, total_balance), ...].
    Active accounts: fill-forward with last known balance.
    Inactive accounts: only contribute on dates they have an actual entry."""
    with get_conn() as conn:
        dates = [r["snapshot_date"] for r in conn.execute("""
            SELECT DISTINCT snapshot_date FROM balance_snapshots ORDER BY snapshot_date
        """).fetchall()]
        accounts = conn.execute("SELECT id, is_active FROM accounts").fetchall()
        rows = conn.execute("""
            SELECT account_id, snapshot_date, balance FROM balance_snapshots
            ORDER BY account_id, snapshot_date
        """).fetchall()

    from collections import defaultdict
    active_ids = {r["id"] for r in accounts if r["is_active"]}
    active_histories: dict = defaultdict(list)
    date_snap: dict = defaultdict(dict)

    for r in rows:
        date_snap[r["snapshot_date"]][r["account_id"]] = r["balance"]
        if r["account_id"] in active_ids:
            active_histories[r["account_id"]].append((r["snapshot_date"], r["balance"]))

    result = []
    for date_str in dates:
        snap = date_snap.get(date_str, {})
        total = 0.0
        for r in accounts:
            acc_id = r["id"]
            if r["is_active"]:
                bal = _last_known_balance(active_histories[acc_id], date_str)
            else:
                bal = snap.get(acc_id)
            if bal is not None:
                total += bal
        result.append((date_str, total))
    return result


def _net_worth_history_filtered(positive_only: bool):
    """Shared implementation for positive/debt-only history with fill-forward."""
    with get_conn() as conn:
        dates = [r["snapshot_date"] for r in conn.execute(
            "SELECT DISTINCT snapshot_date FROM balance_snapshots ORDER BY snapshot_date"
        ).fetchall()]
        accounts = conn.execute("SELECT id, is_active FROM accounts").fetchall()
        rows = conn.execute(
            "SELECT account_id, snapshot_date, balance FROM balance_snapshots"
            " ORDER BY account_id, snapshot_date"
        ).fetchall()

    from collections import defaultdict
    active_ids = {r["id"] for r in accounts if r["is_active"]}
    active_histories: dict = defaultdict(list)
    date_snap: dict = defaultdict(dict)

    for r in rows:
        date_snap[r["snapshot_date"]][r["account_id"]] = r["balance"]
        if r["account_id"] in active_ids:
            active_histories[r["account_id"]].append((r["snapshot_date"], r["balance"]))

    result = []
    for date_str in dates:
        snap = date_snap.get(date_str, {})
        total = 0.0
        for r in accounts:
            acc_id = r["id"]
            bal = (_last_known_balance(active_histories[acc_id], date_str)
                   if r["is_active"] else snap.get(acc_id))
            if bal is None:
                continue
            if positive_only and bal > 0:
                total += bal
            elif not positive_only and bal < 0:
                total += bal
        result.append((date_str, total))
    return result


def get_assets_history():
    """Dates × sum of positive balances only (true assets), fill-forward for active."""
    return _net_worth_history_filtered(positive_only=True)


def get_debt_history():
    """Dates × sum of negative balances (debt), fill-forward for active. Values are negative."""
    return _net_worth_history_filtered(positive_only=False)


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


def get_category_history():
    """
    Returns a list of dicts, one per snapshot date:
    {date, totals: {category_name: value}, grand_total}
    """
    with get_conn() as conn:
        cats = [r["name"] for r in
                conn.execute("SELECT name FROM spending_categories ORDER BY id").fetchall()]
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
        accounts = conn.execute("SELECT id, is_active FROM accounts").fetchall()

    from collections import defaultdict

    active_ids = {r["id"] for r in accounts if r["is_active"]}
    active_histories: dict = defaultdict(list)
    date_snap: dict = defaultdict(dict)

    for row in balance_rows:
        date_snap[row["snapshot_date"]][row["account_id"]] = row["balance"]
        if row["account_id"] in active_ids:
            active_histories[row["account_id"]].append((row["snapshot_date"], row["balance"]))

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
        snap = date_snap.get(date_str, {})
        totals = {c: 0.0 for c in cats}
        for r in accounts:
            acc_id = r["id"]
            if r["is_active"]:
                balance = _last_known_balance(active_histories[acc_id], date_str)
            else:
                balance = snap.get(acc_id)
            if balance is None or balance == 0.0:
                continue
            allocs = {cat: _alloc(acc_id, cat, date_str) for cat in cats}
            amounts = calc_category_amounts(balance, allocs)
            for cat, amount in amounts.items():
                totals[cat] += amount
        grand_total = sum(totals.values())
        result.append({"date": date_str, "totals": totals, "grand_total": grand_total})
    return result


def get_category_current_total(category_name: str) -> float:
    """Sum the current allocated amount for one category across all active accounts."""
    snapshot = get_latest_balance_per_account()
    accounts = get_all_accounts()
    today    = datetime.date.today().isoformat()
    total    = 0.0
    for acc in accounts:
        acc_id  = acc["id"]
        balance = snapshot.get(acc_id, 0.0)
        allocs  = get_allocations_on_date(acc_id, today)
        amounts = calc_category_amounts(balance, allocs)
        total  += amounts.get(category_name, 0.0)
    return total


def _parse_max_cap(raw):
    """Parse an account's max_balance_for_rate into a float, or None."""
    try:
        return float(raw) if raw not in (None, "", "None") else None
    except (TypeError, ValueError):
        return None


def project_net_worth(months: int, monthly_contribution: float = 0.0) -> dict:
    """Aggregate net-worth forecast (Pass 1).

    Models current net worth compounding forward at a single blended annual
    rate, plus a flat monthly contribution that also compounds. The blended
    rate is derived from each active account's effective-dated rate applied to
    its interest-bearing base (positive balance, capped at max_balance_for_rate).

    Returns:
        {
          "series":  [nw_now, nw_month1, ..., nw_monthN],   # len == months + 1
          "blended_annual":       float,   # annual rate used
          "monthly_contribution": float,
          "earning_base":         float,   # £ that actually earns interest today
          "nw_now":               float,
        }

    Limitations (documented for the UI footnote): contributions are assumed to
    earn the blended rate and interest caps are applied only to the starting
    base, not re-checked as balances grow. Per-account modelling is Pass 2.
    """
    months = max(0, int(months))
    today  = datetime.date.today().isoformat()

    snapshot = get_latest_balance_per_account()
    accounts = get_all_accounts()                 # active only
    rates    = _get_rates_on_date(today)

    nw_now        = 0.0
    earning_base  = 0.0     # positive, cap-limited principal that earns
    yearly_int    = 0.0     # cap-aware annual interest at today's balances
    for acc in accounts:
        acc_id  = acc["id"]
        balance = snapshot.get(acc_id, 0.0)
        nw_now += balance
        if balance > 0:
            rate = rates.get(acc_id, 0.0) or 0.0
            cap  = _parse_max_cap(acc.get("max_balance_for_rate"))
            base = balance if cap is None else min(balance, cap)
            earning_base += base
            yearly_int   += base * rate

    blended_annual = (yearly_int / earning_base) if earning_base > 0 else 0.0
    r_month        = (1.0 + blended_annual) ** (1.0 / 12.0) - 1.0

    # Split net worth into an earning pool and a constant non-earning remainder
    # (debt, cash above caps). Contributions join the earning pool.
    non_earning = nw_now - earning_base
    pool        = earning_base

    series = [nw_now]
    for _ in range(months):
        pool = pool + pool * r_month + monthly_contribution
        series.append(pool + non_earning)

    return {
        "series":               series,
        "blended_annual":       blended_annual,
        "monthly_contribution": monthly_contribution,
        "earning_base":         earning_base,
        "nw_now":               nw_now,
    }


def _nw_date(s):
    """Parse a net-worth-history date string into a datetime.date."""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _nw_value_at(history, target_date):
    """Linearly-interpolated net worth at target_date from a [(date_str, val)] series."""
    pts = [(_nw_date(d), v) for d, v in history]
    pts = [(d, v) for d, v in pts if d is not None]
    if not pts:
        return None
    if target_date <= pts[0][0]:
        return pts[0][1]
    if target_date >= pts[-1][0]:
        return pts[-1][1]
    for (d0, v0), (d1, v1) in zip(pts, pts[1:]):
        if d0 <= target_date <= d1:
            span = (d1 - d0).days
            if span == 0:
                return v1
            frac = (target_date - d0).days / span
            return v0 + frac * (v1 - v0)
    return pts[-1][1]


def estimate_trend_contribution(lookback_months: int = 6) -> dict | None:
    """Estimate the recent monthly contribution (savings beyond interest).

    Decomposes the change in net worth over the lookback window into an
    interest component (removed, so it isn't double-counted when the forecast
    re-applies interest) and a contribution component:

        ΔNW           = nw_now − nw_(lookback ago)
        interest_win  ≈ earning_base × blended_annual × (lookback / 12)
        contribution  = (ΔNW − interest_win) / lookback   [£ / month]

    Returns None when there is too little history to estimate.
    """
    history = get_net_worth_history()
    if len(history) < 2:
        return None

    last_date = _nw_date(history[-1][0])
    if last_date is None:
        return None
    nw_now = history[-1][1]

    # Target date ~lookback months back (whole-month arithmetic)
    m = last_date.month - 1 - lookback_months
    y = last_date.year + (m // 12)
    m = m % 12 + 1
    import calendar as _cal
    target = datetime.date(y, m, min(last_date.day, _cal.monthrange(y, m)[1]))

    # Don't extrapolate before the first snapshot — shorten the window instead.
    first_date  = _nw_date(history[0][0])
    eff_lookback = lookback_months
    if first_date is not None and target < first_date:
        target = first_date
        eff_lookback = max(1.0, (last_date - first_date).days / 30.44)

    nw_past = _nw_value_at(history, target)
    if nw_past is None:
        return None

    p = project_net_worth(0)
    interest_win = p["earning_base"] * p["blended_annual"] * (eff_lookback / 12.0)
    contribution = (nw_now - nw_past - interest_win) / eff_lookback

    return {
        "contribution":   contribution,
        "lookback_months": lookback_months,
        "eff_lookback":   eff_lookback,
        "nw_past":        nw_past,
        "nw_now":         nw_now,
    }
