"""
main.py — Self-Learning Payroll Automation Agent

Usage examples:
    python main.py                            # current month, interactive
    python main.py --year 2026 --month 3      # specific month, interactive
    python main.py --no-interactive           # batch mode (no prompts)
    python main.py --dry-run                  # calculate but don't write files
    python main.py --list-users               # list Clockify users and exit
    python main.py --threshold 80             # lower fuzzy match threshold
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

from config import ALIAS_FILE, FUZZY_MATCH_THRESHOLD, SKIP_CLOCKIFY_USERS
from clockify_client import ClockifyClient
from payroll_engine import load_rates, calculate_payroll
from report_generator import (
    generate_payroll_report,
    generate_unmatched_report,
    print_payroll_table,
    print_unmatched_summary,
)
from learning_engine import (
    load_alias_memory,
    save_alias_memory,
    resolve_unmatched,
)
from email_sender import send_payroll_report

# ── logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("payroll_agent")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    now = datetime.now()
    p   = argparse.ArgumentParser(
        description="Self-Learning Payroll Automation Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--year",           type=int, default=now.year,
                   help="Year for payroll period (default: current year)")
    p.add_argument("--month",          type=int, default=now.month,
                   help="Month for payroll period (default: current month)")
    p.add_argument("--threshold",      type=int, default=FUZZY_MATCH_THRESHOLD,
                   help=f"Fuzzy match threshold 0-100 (default: {FUZZY_MATCH_THRESHOLD})")
    p.add_argument("--no-interactive", action="store_true",
                   help="Run in batch mode — skip interactive prompts")
    p.add_argument("--dry-run",        action="store_true",
                   help="Print results but do not write any output files")
    p.add_argument("--list-users",     action="store_true",
                   help="List all Clockify workspace users and exit")
    return p.parse_args()


# ── helpers ───────────────────────────────────────────────────────────────────

def _merge_resolved_into_payroll(
    payroll_df: pd.DataFrame,
    resolved:   dict,
    user_hours: dict,
    rates_df:   pd.DataFrame,
) -> pd.DataFrame:
    """Append interactively-confirmed rows into the payroll DataFrame."""
    if not resolved:
        return payroll_df

    rate_lookup = dict(zip(rates_df["Employee Name"], rates_df["Rate"]))
    new_rows = []
    for cname, emp_name in resolved.items():
        hours     = user_hours.get(cname, 0.0)
        rate      = float(rate_lookup.get(emp_name, 0.0) or 0.0)
        total_pay = round(hours * rate, 2)
        new_rows.append({
            "Employee Name": emp_name,
            "Clockify User": cname,
            "Hours":         round(hours, 2),
            "Rate":          rate,
            "Total Pay":     total_pay,
            "Match Method":  "interactive",
            "Confidence":    "100%",
        })

    combined = pd.concat(
        [payroll_df, pd.DataFrame(new_rows)],
        ignore_index=True,
    )
    return combined.sort_values("Employee Name").reset_index(drop=True)


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    args        = _parse_args()
    year, month = args.year, args.month
    interactive = not args.no_interactive

    period_label = datetime(year, month, 1).strftime("%B %Y")
    log.info("═" * 72)
    log.info("Payroll Automation Agent  —  %s", period_label)
    log.info("═" * 72)

    # ── 1. Connect to Clockify ────────────────────────────────────────────────
    client = ClockifyClient()

    if args.list_users:
        users = client.get_users()
        print(f"\nWorkspace users ({len(users)}):")
        for u in users:
            print(f"  • {u.get('name'):<30}  id={u['id']}")
        print()
        sys.exit(0)

    # ── 2. Load alias memory & rate table ────────────────────────────────────
    log.info("Loading alias memory …")
    alias_map = load_alias_memory()

    log.info("Loading employee rate table …")
    rates_df  = load_rates()

    # ── 3. Fetch Clockify hours for the target month ──────────────────────────
    user_hours = client.get_monthly_hours(year, month)

    if not user_hours:
        log.warning("No tracked time found for %s. Nothing to calculate.", period_label)
        sys.exit(0)

    # ── 3b. Remove skipped users ──────────────────────────────────────────────
    skipped = [u for u in user_hours if u.lower() in SKIP_CLOCKIFY_USERS]
    for u in skipped:
        log.info("Skipping excluded user: %s", u)
        del user_hours[u]

    log.info("")
    log.info("Clockify users with tracked time (%d):", len(user_hours))
    for name, hrs in sorted(user_hours.items(), key=lambda x: x[1], reverse=True):
        log.info("  %-35s  %.2f h", name, hrs)
    log.info("")

    # ── 4. Match & calculate payroll ─────────────────────────────────────────
    log.info("Running payroll calculation …")
    payroll_df, unmatched, matcher = calculate_payroll(
        user_hours, alias_map, rates_df, threshold=args.threshold
    )

    # ── 5. Resolve unmatched users ────────────────────────────────────────────
    still_unmatched: list[str] = []

    if unmatched:
        log.info("")
        log.info("%d unmatched Clockify user(s): %s", len(unmatched), unmatched)
        resolved, still_unmatched, alias_map = resolve_unmatched(
            unmatched,
            matcher,
            alias_map,
            interactive=interactive,
        )
        if resolved:
            payroll_df = _merge_resolved_into_payroll(
                payroll_df, resolved, user_hours, rates_df
            )

    # ── 6. Persist updated aliases ────────────────────────────────────────────
    if not args.dry_run:
        save_alias_memory(alias_map)

    # ── 7. Print console report ───────────────────────────────────────────────
    print_payroll_table(payroll_df, year, month)
    print_unmatched_summary(still_unmatched, user_hours)

    # ── 8. Write output files ─────────────────────────────────────────────────
    if args.dry_run:
        log.info("Dry-run mode — no files written.")
        return

    csv_path = None
    if not payroll_df.empty:
        csv_path = generate_payroll_report(payroll_df, year, month)

    if still_unmatched:
        generate_unmatched_report(still_unmatched, year, month, user_hours)

    # ── 9. Email report ───────────────────────────────────────────────────────
    if csv_path:
        try:
            send_payroll_report(
                csv_path        = csv_path,
                year            = year,
                month           = month,
                total_employees = len(payroll_df),
                total_hours     = float(payroll_df["Hours"].sum()),
                total_pay       = float(payroll_df["Total Pay"].sum()),
            )
        except RuntimeError as exc:
            log.warning("Email not sent: %s", exc)
        except Exception as exc:
            log.error("Email failed: %s", exc)

    log.info("Done.  Reports saved to payroll_agent/output/")


if __name__ == "__main__":
    main()
