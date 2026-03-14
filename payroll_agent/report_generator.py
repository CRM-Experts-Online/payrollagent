"""
report_generator.py — Generates payroll output files and console tables.

Output files written to OUTPUT_DIR (payroll_agent/output/):
    payroll_report_YYYY_MM.csv
    payroll_report_YYYY_MM.json
    unmatched_users_YYYY_MM.csv   (only if there are unmatched users)
"""
from __future__ import annotations

import json
import logging
from calendar import monthrange
from datetime import datetime
from pathlib import Path
from typing import List

import pandas as pd
from tabulate import tabulate

from config import OUTPUT_DIR

log = logging.getLogger(__name__)


# ── payroll report ────────────────────────────────────────────────────────────

def generate_payroll_report(
    payroll_df: pd.DataFrame,
    year:       int,
    month:      int,
    output_dir: Path = OUTPUT_DIR,
) -> Path:
    """Write CSV and JSON payroll reports for the given period."""
    tag = f"{year:04d}_{month:02d}"
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── CSV ───────────────────────────────────────────────────────────────────
    csv_path = output_dir / f"payroll_report_{tag}.csv"
    export_df = payroll_df.copy()
    export_df.insert(0, "Period", datetime(year, month, 1).strftime("%B %Y"))
    export_df.insert(1, "Period Start", f"{year:04d}-{month:02d}-01")
    export_df.insert(2, "Period End",   f"{year:04d}-{month:02d}-{monthrange(year, month)[1]:02d}")
    export_df.to_csv(csv_path, index=False)
    log.info("CSV  → %s", csv_path)

    # ── JSON ──────────────────────────────────────────────────────────────────
    json_path = output_dir / f"payroll_report_{tag}.json"
    summary = {
        "period":           f"{year:04d}-{month:02d}",
        "period_label":     datetime(year, month, 1).strftime("%B %Y"),
        "generated_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_employees":  len(payroll_df),
        "total_hours":      round(float(payroll_df["Hours"].sum()), 2),
        "total_payroll_usd": round(float(payroll_df["Total Pay"].sum()), 2),
        "records":          payroll_df.to_dict(orient="records"),
    }
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
    log.info("JSON → %s", json_path)
    return csv_path


# ── unmatched report ──────────────────────────────────────────────────────────

def generate_unmatched_report(
    unmatched:  List[str],
    year:       int,
    month:      int,
    user_hours: dict | None = None,
    output_dir: Path = OUTPUT_DIR,
) -> None:
    """Write a CSV listing unmatched Clockify users."""
    if not unmatched:
        return
    tag  = f"{year:04d}_{month:02d}"
    path = output_dir / f"unmatched_users_{tag}.csv"
    rows = [
        {"Clockify User": u, "Hours": (user_hours or {}).get(u, "")}
        for u in unmatched
    ]
    pd.DataFrame(rows).to_csv(path, index=False)
    log.info("Unmatched → %s  (%d users)", path, len(unmatched))


# ── console pretty-print ──────────────────────────────────────────────────────

def print_payroll_table(
    payroll_df: pd.DataFrame,
    year:       int,
    month:      int,
) -> None:
    """Pretty-print the payroll summary to stdout using tabulate."""
    month_label = datetime(year, month, 1).strftime("%B %Y")

    print(f"\n{'═' * 82}")
    print(f"  PAYROLL REPORT — {month_label}")
    print(f"{'═' * 82}")

    if payroll_df.empty:
        print("  No payroll records to display.\n")
        return

    display = payroll_df[
        ["Employee Name", "Clockify User", "Hours", "Rate", "Total Pay",
         "Match Method", "Confidence"]
    ].copy()

    display["Rate"]      = display["Rate"].apply(lambda x: f"${x:,.2f}")
    display["Total Pay"] = display["Total Pay"].apply(lambda x: f"${x:,.2f}")

    print(
        tabulate(
            display,
            headers="keys",
            tablefmt="rounded_outline",
            showindex=False,
        )
    )

    total_hours = payroll_df["Hours"].sum()
    total_pay   = payroll_df["Total Pay"].sum()

    print(f"{'─' * 82}")
    print(
        f"  Employees : {len(payroll_df):>4}   "
        f"Total Hours : {total_hours:>8.2f}   "
        f"Total Payroll : ${total_pay:>10,.2f}"
    )
    print(f"{'═' * 82}\n")


def print_unmatched_summary(
    unmatched:  List[str],
    user_hours: dict,
) -> None:
    """Print a red-highlighted list of unmatched Clockify users."""
    if not unmatched:
        return
    print(f"  \033[91mUnmatched Clockify users ({len(unmatched)}):\033[0m")
    for u in unmatched:
        hrs = user_hours.get(u, 0)
        print(f"    • {u:<30}  {hrs:.2f} h")
    print()
