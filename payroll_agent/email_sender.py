"""
email_sender.py — Sends the payroll CSV report via SMTP.

Requires in .env (one level above payroll_agent/):
    EMAIL_USERNAME=you@example.com
    EMAIL_PASSWORD=your-app-password
    EMAIL_SMTP_HOST=smtp.gmail.com   (optional, default)
    EMAIL_SMTP_PORT=587              (optional, default)
    EMAIL_FROM=you@example.com       (optional, defaults to USERNAME)
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import List

from config import (
    EMAIL_FROM,
    EMAIL_PASSWORD,
    EMAIL_RECIPIENTS,
    EMAIL_SMTP_HOST,
    EMAIL_SMTP_PORT,
    EMAIL_USERNAME,
)

log = logging.getLogger(__name__)


def send_payroll_report(
    csv_path:  Path,
    year:      int,
    month:     int,
    total_employees: int,
    total_hours:     float,
    total_pay:       float,
    recipients: List[str] = EMAIL_RECIPIENTS,
) -> None:
    """
    Email the payroll CSV as an attachment to all recipients.
    Raises RuntimeError if EMAIL_USERNAME or EMAIL_PASSWORD are not set.
    """
    if not EMAIL_USERNAME or not EMAIL_PASSWORD:
        raise RuntimeError(
            "EMAIL_USERNAME and EMAIL_PASSWORD must be set in .env to send email."
        )

    period_label = datetime(year, month, 1).strftime("%B %Y")
    subject      = f"Payroll Report — {period_label}"

    body = (
        f"Hi,\n\n"
        f"Please find attached the payroll report for {period_label}.\n\n"
        f"Summary:\n"
        f"  Period      : {period_label}\n"
        f"  Employees   : {total_employees}\n"
        f"  Total Hours : {total_hours:,.2f} h\n"
        f"  Total Pay   : ${total_pay:,.2f}\n\n"
        f"The detailed breakdown is in the attached CSV file.\n\n"
        f"— Payroll Automation Agent"
    )

    msg = MIMEMultipart()
    msg["From"]    = EMAIL_FROM or EMAIL_USERNAME
    msg["To"]      = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with open(csv_path, "rb") as fh:
        attachment = MIMEApplication(fh.read(), Name=csv_path.name)
    attachment["Content-Disposition"] = f'attachment; filename="{csv_path.name}"'
    msg.attach(attachment)

    context = ssl.create_default_context()
    log.info("Connecting to %s:%d …", EMAIL_SMTP_HOST, EMAIL_SMTP_PORT)
    with smtplib.SMTP(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, timeout=30) as server:
        server.ehlo()
        server.starttls(context=context)
        server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
        server.sendmail(EMAIL_FROM or EMAIL_USERNAME, recipients, msg.as_string())

    log.info("Email sent to: %s", ", ".join(recipients))
