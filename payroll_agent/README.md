# Payroll Automation Agent

Pulls time data from Clockify, matches employees, calculates pay, generates a CSV report, and emails it automatically.

---

## How It Works

1. Fetches tracked hours from Clockify for the target month
2. Matches Clockify display names to employees in `employee_rates.csv` using fuzzy matching + learned aliases
3. Calculates `Hours × Rate = Total Pay` per employee
4. Saves a CSV and JSON report to `payroll_agent/output/`
5. Emails the CSV to `jperez@service-push.com` and `chareze@service-push.com`

---

## Setup

### Requirements
- Python 3.10+
- Install dependencies:
  ```
  pip install pandas requests rapidfuzz tabulate python-dotenv
  ```

### Configuration Files

| File | Purpose |
|---|---|
| `employee_rates.csv` | Employee names and hourly rates |
| `name_aliases.json` | Learned Clockify name → employee name mappings |
| `../.env` | Credentials (Clockify API key, email password) |
| `config.py` | Skip list, thresholds, SMTP settings |

### `.env` file (located at `Downloads/.env`)
```
EMAIL_USERNAME=jperez@service-push.com
EMAIL_PASSWORD=your-gmail-app-password
EMAIL_FROM=jperez@service-push.com
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
```

> **Gmail App Password:** Google Account → Security → 2-Step Verification → App Passwords

---

## Commands

All commands are run from the `Downloads/` folder:

```bash
cd "C:\Users\John Perez\Downloads"
```

### Run for current month (generates report + sends email)
```bash
python payroll_agent/main.py
```

### Run for a specific month
```bash
python payroll_agent/main.py --year 2026 --month 2
```

### Dry run (calculate and print — no files written, no email sent)
```bash
python payroll_agent/main.py --dry-run
```

### Batch mode (no interactive prompts for unmatched names)
```bash
python payroll_agent/main.py --no-interactive
```

### Dry run + batch (safe preview)
```bash
python payroll_agent/main.py --dry-run --no-interactive
```

### List all Clockify workspace users
```bash
python payroll_agent/main.py --list-users
```

### Lower the fuzzy match threshold (default: 85)
```bash
python payroll_agent/main.py --threshold 75
```

---

## Output Files

Saved to `payroll_agent/output/`:

| File | Contents |
|---|---|
| `payroll_report_YYYY_MM.csv` | Full payroll table with period, hours, rate, total pay |
| `payroll_report_YYYY_MM.json` | Same data as JSON with summary totals |
| `unmatched_users_YYYY_MM.csv` | Clockify users that could not be matched (if any) |

### CSV columns
`Period`, `Period Start`, `Period End`, `Employee Name`, `Clockify User`, `Hours`, `Rate`, `Total Pay`, `Match Method`, `Confidence`

---

## Managing Employees

### Add a new employee
Edit `employee_rates.csv` and add a line:
```
Full Name,hourly_rate
```

### Add a name alias (e.g. Clockify shows "Bob" but employee is "Robert Smith")
Edit `name_aliases.json`:
```json
"bob": "Robert Smith"
```

### Skip a Clockify user from payroll (e.g. owners, contractors)
Edit `config.py` → `SKIP_CLOCKIFY_USERS`:
```python
SKIP_CLOCKIFY_USERS: frozenset[str] = frozenset({
    "daria",
    "john perez",
})
```
Names are matched case-insensitively.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Unmatched employees | Add them to `employee_rates.csv` or `name_aliases.json` |
| Email not sending | Check `.env` credentials; ensure Gmail App Password is set |
| Unicode errors on Windows | Run with `PYTHONUTF8=1 python payroll_agent/main.py` |
| Wrong Clockify workspace | API key in `config.py` (`CLOCKIFY_API_KEY`) picks the first workspace |
