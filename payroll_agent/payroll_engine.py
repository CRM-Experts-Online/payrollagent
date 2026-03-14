"""
payroll_engine.py — Matches Clockify users to employees and computes pay.

Public API:
    rates_df = load_rates()
    payroll_df, unmatched, matcher = calculate_payroll(
        user_hours, alias_map, rates_df, threshold
    )
"""
from __future__ import annotations

import logging
from typing import Dict, List, Tuple

import pandas as pd

from config import RATES_FILE, FUZZY_MATCH_THRESHOLD
from name_matcher import NameMatcher

log = logging.getLogger(__name__)


# ── rate table ────────────────────────────────────────────────────────────────

def load_rates(path=RATES_FILE) -> pd.DataFrame:
    """
    Load employee_rates.csv → DataFrame with columns:
        Employee Name  (str)
        Rate           (float, hourly USD)
    """
    df = pd.read_csv(path)
    df.columns   = df.columns.str.strip()
    df["Employee Name"] = df["Employee Name"].str.strip()
    df["Rate"]          = pd.to_numeric(df["Rate"], errors="coerce")

    missing_rate = df[df["Rate"].isna()]["Employee Name"].tolist()
    if missing_rate:
        log.warning("Employees with no rate defined: %s", missing_rate)

    log.info("Loaded rate table: %d employees.", len(df))
    return df


# ── payroll calculation ───────────────────────────────────────────────────────

def calculate_payroll(
    user_hours: Dict[str, float],
    alias_map:  Dict[str, str],
    rates_df:   pd.DataFrame,
    threshold:  int = FUZZY_MATCH_THRESHOLD,
) -> Tuple[pd.DataFrame, List[str], NameMatcher]:
    """
    Core calculation.

    For each Clockify user:
        1. Run NameMatcher pipeline to find the canonical employee name.
        2. Look up their hourly rate.
        3. Compute total_pay = hours × rate.

    Returns:
        payroll_df  : DataFrame (Employee Name, Clockify User, Hours,
                                 Rate, Total Pay, Match Method, Confidence)
        unmatched   : list of Clockify names that could not be matched
        matcher     : the NameMatcher instance (reused during interactive step)
    """
    employee_list = rates_df["Employee Name"].tolist()
    matcher       = NameMatcher(employee_list, alias_map, threshold)
    rate_lookup   = dict(zip(rates_df["Employee Name"], rates_df["Rate"]))

    records:   List[Dict]  = []
    unmatched: List[str]   = []
    dup_check: Dict[str, str] = {}   # employee → first clockify user that matched

    log.info("─" * 72)
    log.info("%-36s ← %-22s | %6s × %6s = %9s", "Employee", "Clockify User",
             "Hours", "Rate", "Total Pay")
    log.info("─" * 72)

    for cname, hours in sorted(user_hours.items()):
        emp_name, confidence, method = matcher.match(cname)

        if emp_name is None:
            log.warning("UNMATCHED  '%s'  (%.2f h tracked)", cname, hours)
            unmatched.append(cname)
            continue

        rate = rate_lookup.get(emp_name)
        if rate is None or pd.isna(rate):
            log.warning("No rate for '%s' — defaulting to $0.00", emp_name)
            rate = 0.0

        total_pay = round(hours * float(rate), 2)

        # Warn if same employee matched by two different Clockify users
        if emp_name in dup_check:
            log.warning(
                "DUPLICATE MATCH: '%s' AND '%s' both matched to '%s'",
                cname, dup_check[emp_name], emp_name,
            )
        else:
            dup_check[emp_name] = cname

        log.info(
            "%-36s ← %-22s | %6.2f × $%5.2f = $%8.2f  [%s %.0f%%]",
            emp_name, cname, hours, rate, total_pay, method, confidence,
        )
        records.append({
            "Employee Name": emp_name,
            "Clockify User": cname,
            "Hours":         round(hours, 2),
            "Rate":          float(rate),
            "Total Pay":     total_pay,
            "Match Method":  method,
            "Confidence":    f"{confidence:.0f}%",
        })

    log.info("─" * 72)

    payroll_df = pd.DataFrame(records)
    if not payroll_df.empty:
        payroll_df = (
            payroll_df
            .sort_values("Employee Name")
            .reset_index(drop=True)
        )

    log.info(
        "Payroll: %d matched | %d unmatched",
        len(payroll_df), len(unmatched),
    )
    return payroll_df, unmatched, matcher
