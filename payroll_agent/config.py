"""
config.py — Central configuration for the Payroll Automation Agent.
All path references, thresholds, and environment variables live here.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (one level above payroll_agent/)
load_dotenv(Path(__file__).parent.parent / ".env")

# ── Base directory (payroll_agent/) ──────────────────────────────────────────
BASE_DIR = Path(__file__).parent

# ── Clockify ──────────────────────────────────────────────────────────────────
CLOCKIFY_API_KEY = os.getenv(
    "CLOCKIFY_API_KEY",
    "YmI5ZDc0NGQtZjNiOC00ZmM1LThiYjUtMDY2ZTBkMjc0NWFl",
)
CLOCKIFY_BASE_URL    = "https://api.clockify.me/api/v1"
CLOCKIFY_REPORTS_URL = "https://reports.api.clockify.me/v1"

# ── Matching thresholds ───────────────────────────────────────────────────────
# Below this %  → ask user to confirm
FUZZY_MATCH_THRESHOLD = 85
# At or above this % → accept automatically without prompting
AUTO_ACCEPT_THRESHOLD = 95

# ── File paths ────────────────────────────────────────────────────────────────
ALIAS_FILE = BASE_DIR / "name_aliases.json"
RATES_FILE = BASE_DIR / "employee_rates.csv"
OUTPUT_DIR = BASE_DIR / "output"

# Ensure output directory exists at import time
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Email ─────────────────────────────────────────────────────────────────────
EMAIL_SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))
EMAIL_USERNAME  = os.getenv("EMAIL_USERNAME", "")
EMAIL_PASSWORD  = os.getenv("EMAIL_PASSWORD", "")   # Gmail app password
EMAIL_FROM      = os.getenv("EMAIL_FROM", "jperez@service-push.com")
EMAIL_RECIPIENTS = [
    "jperez@service-push.com",
    "chareze@service-push.com",
]

# ── Clockify users to exclude from payroll ────────────────────────────────────
# These names are matched case-insensitively against Clockify display names.
SKIP_CLOCKIFY_USERS: frozenset[str] = frozenset({
    "daria",
    "john perez",
})
