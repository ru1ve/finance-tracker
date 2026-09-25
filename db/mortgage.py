"""
db/mortgage.py — Mortgage calculator and persistence helpers.
"""
from __future__ import annotations

import datetime

from db.connection import get_conn
from db.snapshots import get_latest_balance_per_account
from db.accounts import get_all_accounts
from db.allocations import get_allocations_on_date, calc_category_amounts
from db.income import _get_rates_on_date


def get_mortgage_fixed() -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM mortgage_fixed").fetchall()
    return {r["key"]: r["value"] for r in rows}


def save_mortgage_fixed(data: dict) -> None:
    with get_conn() as conn:
        for key, value in data.items():
            conn.execute(
                "INSERT INTO mortgage_fixed (key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )


def get_mortgage_income_items() -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT label, amount FROM mortgage_income_items ORDER BY sort_order, id"
        ).fetchall()
    return [{"label": r["label"], "amount": r["amount"]} for r in rows]


def save_mortgage_income_items(items: list) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM mortgage_income_items")
        for i, item in enumerate(items):
            conn.execute(
                "INSERT INTO mortgage_income_items (label, amount, sort_order) VALUES (?,?,?)",
                (item["label"], item["amount"], i),
            )


def get_mortgage_expense_items() -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT label, amount FROM mortgage_expense_items ORDER BY sort_order, id"
        ).fetchall()
    return [{"label": r["label"], "amount": r["amount"]} for r in rows]


def save_mortgage_expense_items(items: list) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM mortgage_expense_items")
        for i, item in enumerate(items):
            conn.execute(
                "INSERT INTO mortgage_expense_items (label, amount, sort_order) VALUES (?,?,?)",
                (item["label"], item["amount"], i),
            )


def calc_scottish_net_salary(gross: float) -> float:
    """Scottish income tax bands 2024/25 + NI."""
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
    """LTV-tiered spread on top of BoE base."""
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
    """How much gross salary is needed to break even."""
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
    bonus: float = 0.0,
    pension_pct: float = 0.0,
    extra_monthly_income: float = 0.0,
    property_price: float = 0.0,
    overbid_rate: float = 0.0,
    fees: float = 0.0,
    boe_rate: float = 0.0,
    term_years: int = 25,
    expenses: dict = None,
    deposit_raw: float | None = None,
    deposit_category: str = "Deposit",
):
    """Full mortgage affordability calculation."""
    if expenses is None:
        expenses = {}

    annual_income  = max(0.0, annual_income)
    bonus          = max(0.0, bonus)
    pension_pct    = max(0.0, min(0.99, pension_pct))
    property_price = max(0.0, property_price)
    overbid_rate   = max(0.0, min(1.0, overbid_rate))
    fees           = max(0.0, fees)
    term_years     = max(1, term_years)

    gross = (annual_income + bonus) * (1 - pension_pct)
    net_annual = calc_scottish_net_salary(gross)
    net_monthly = net_annual / 12

    if deposit_raw is None:
        snapshot = get_latest_balance_per_account()
        accounts = get_all_accounts()
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        deposit_raw = 0.0
        for acc in accounts:
            acc_id = acc["id"]
            balance = snapshot.get(acc_id, 0.0)
            allocs = get_allocations_on_date(acc_id, now_str)
            amounts = calc_category_amounts(balance, allocs)
            deposit_raw += amounts.get(deposit_category, 0.0)

    overbid_amount   = property_price * overbid_rate
    deposit_after    = deposit_raw - overbid_amount - fees

    mortgage_amount  = property_price - deposit_after
    ltv              = mortgage_amount / property_price if property_price > 0 else 0
    interest_rate    = calc_ltv_rate(boe_rate, ltv)
    monthly_mortgage = calc_monthly_payment(mortgage_amount, interest_rate, term_years)
    est_borrow       = annual_income * 4.5

    total_expenses        = sum(expenses.values()) + monthly_mortgage
    total_net_monthly     = net_monthly + extra_monthly_income
    gross_income_remaining = total_net_monthly - total_expenses

    # Mortgage affordability (salary only, no extra income/expenses)
    deposit_shortfall = max(0.0, -deposit_after)
    mortgage_surplus  = net_monthly - monthly_mortgage

    # Next LTV band (skip when deposit can't cover costs, or LTV already >= 100%)
    if deposit_shortfall > 0 or ltv >= 1.0:
        additional_deposit_needed = 0.0
        next_ltv_label   = "N/A"
        next_ltv_rate    = interest_rate
        next_ltv_monthly = monthly_mortgage
    else:
        next_band = calc_next_ltv_band(ltv)
        if isinstance(next_band, float):
            property_value_at_current_ltv = deposit_after / (1 - ltv)
            additional_deposit_needed = property_value_at_current_ltv * (ltv - next_band)
            next_ltv_label   = f"{next_band*100:.0f}%"
            next_ltv_rate    = calc_ltv_rate(boe_rate, next_band)
            next_ltv_monthly = calc_monthly_payment(
                property_price * next_band, next_ltv_rate, term_years)
        else:
            additional_deposit_needed = 0.0
            next_ltv_label   = next_band
            next_ltv_rate    = interest_rate
            next_ltv_monthly = monthly_mortgage

    # Salary required to cover mortgage payments (lender affordability view)
    current_gross_for_calc = (annual_income + bonus) * (1 - pension_pct)
    salary_required = calc_salary_required(
        -mortgage_surplus * 12, bonus, pension_pct, current_gross_for_calc
    ) if mortgage_surplus < 0 else None

    return {
        "gross_taxable":        gross,
        "net_annual":           net_annual,
        "net_monthly":          net_monthly,
        "extra_monthly_income": extra_monthly_income,
        "total_net_monthly":    total_net_monthly,
        "deposit_raw":          deposit_raw,
        "overbid_amount":       overbid_amount,
        "fees":                 fees,
        "deposit_after":        deposit_after,
        "property_price":       property_price,
        "mortgage_amount":      mortgage_amount,
        "ltv":                  ltv,
        "interest_rate":        interest_rate,
        "monthly_mortgage":     monthly_mortgage,
        "est_borrow_45x":       est_borrow,
        "remaining_vs_est":     mortgage_amount - est_borrow,
        "term_years":           term_years,
        "deposit_shortfall":    deposit_shortfall,
        "expenses":             expenses,
        "total_expenses":       total_expenses,
        "monthly_surplus":      gross_income_remaining,
        "mortgage_surplus":     mortgage_surplus,
        "salary_required":      salary_required,
        "next_ltv_label":       next_ltv_label,
        "next_ltv_rate":        next_ltv_rate,
        "next_ltv_monthly":     next_ltv_monthly,
        "additional_deposit":   additional_deposit_needed,
    }


def project_balances(months: int):
    """Simple projection: apply current interest rates monthly for N months."""
    date_str = datetime.date.today().isoformat()
    snapshot = get_latest_balance_per_account()
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
