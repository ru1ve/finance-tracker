"""
db/__init__.py — Re-exports every public function so that `import db; db.get_all_accounts()`
continues to work.  Tabs still do `import db` and call `db.xxx()`.
"""
from db.connection import _db_dir, get_conn, init_db, DB_PATH, DB_DIR, list_db_files, set_db_path
from db.settings import get_setting, set_setting
from db.accounts import (
    get_product_types, add_product_type,
    get_all_accounts, get_account_by_id, upsert_account, deactivate_account,
    update_account_details, update_account_product_type, update_account_category,
    reactivate_account, get_account_categories,
    get_spending_categories, add_spending_category,
    delete_spending_category, get_spending_category_names,
    import_from_json,
)
from db.snapshots import (
    save_snapshot, get_snapshot_dates, get_snapshot, get_latest_snapshot,
    get_latest_balance_per_account, get_snapshot_with_names,
    delete_snapshot_date, delete_snapshot_entry, update_balance_entry,
    get_balance_history,
    _last_known_balance,
)
from db.allocations import (
    get_all_allocations_on_date, get_category_account_breakdown,
    get_last_recorded_dates, get_rate_on_date, get_allocations_on_date,
    calc_category_amounts, save_account_allocation,
    get_current_rate, get_rate_history, get_allocation_history,
)
from db.history import (
    get_net_worth_history, _net_worth_history_filtered,
    get_assets_history, get_debt_history,
    get_all_balance_histories, get_category_history,
    get_category_current_total, project_net_worth,
    estimate_trend_contribution,
)
from db.mortgage import (
    get_mortgage_fixed, save_mortgage_fixed,
    get_mortgage_income_items, save_mortgage_income_items,
    get_mortgage_expense_items, save_mortgage_expense_items,
    calc_scottish_net_salary, calc_ltv_rate, calc_monthly_payment,
    calc_next_ltv_band, calc_salary_required,
    mortgage_estimate, project_balances,
)
from db.income import (
    get_income_sources, get_income_sub_sources, add_income_source,
    add_income, get_all_income, delete_income,
    save_account_rate, get_current_interest_summary,
    _get_rates_on_date,
)
from db.statement_parsers import detect_and_parse
from db.spending import (
    build_preview, commit_import, get_transactions,
    set_transaction_classification, get_categories, get_subcategories,
    get_imports, delete_import, get_name_category_map,
)

__all__ = [
    # connection
    "_db_dir", "get_conn", "init_db", "DB_PATH", "DB_DIR", "list_db_files", "set_db_path",
    # settings
    "get_setting", "set_setting",
    # accounts
    "get_product_types", "add_product_type",
    "get_all_accounts", "get_account_by_id", "upsert_account", "deactivate_account",
    "update_account_details", "update_account_product_type", "update_account_category",
    "reactivate_account", "get_account_categories",
    "get_spending_categories", "add_spending_category",
    "delete_spending_category", "get_spending_category_names",
    "import_from_json",
    # snapshots
    "save_snapshot", "get_snapshot_dates", "get_snapshot", "get_latest_snapshot",
    "get_latest_balance_per_account", "get_snapshot_with_names",
    "delete_snapshot_date", "delete_snapshot_entry", "update_balance_entry",
    "get_balance_history", "_last_known_balance",
    # allocations
    "get_all_allocations_on_date", "get_category_account_breakdown",
    "get_last_recorded_dates", "get_rate_on_date", "get_allocations_on_date",
    "calc_category_amounts", "save_account_allocation",
    "get_current_rate", "get_rate_history", "get_allocation_history",
    # history
    "get_net_worth_history", "_net_worth_history_filtered",
    "get_assets_history", "get_debt_history",
    "get_all_balance_histories", "get_category_history",
    "get_category_current_total", "project_net_worth",
    "estimate_trend_contribution",
    # mortgage
    "get_mortgage_fixed", "save_mortgage_fixed",
    "get_mortgage_income_items", "save_mortgage_income_items",
    "get_mortgage_expense_items", "save_mortgage_expense_items",
    "calc_scottish_net_salary", "calc_ltv_rate", "calc_monthly_payment",
    "calc_next_ltv_band", "calc_salary_required",
    "mortgage_estimate", "project_balances",
    # income
    "get_income_sources", "get_income_sub_sources", "add_income_source",
    "add_income", "get_all_income", "delete_income",
    "save_account_rate", "get_current_interest_summary",
    "_get_rates_on_date",
    # spending / statement import
    "detect_and_parse", "build_preview", "commit_import", "get_transactions",
    "set_transaction_classification", "get_categories", "get_subcategories",
    "get_imports", "delete_import", "get_name_category_map",
]
