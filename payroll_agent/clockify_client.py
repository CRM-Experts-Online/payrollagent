"""
clockify_client.py — Clockify REST + Reports API wrapper.

Strategy:
  1. Try the Reports API summary endpoint (one call, pre-aggregated).
  2. If that fails (plan restriction, 4xx, etc.), fall back to the
     standard time-entries endpoint paginated per user.
"""
from __future__ import annotations

import re
import logging
from calendar import monthrange
from datetime import datetime
from typing import Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import CLOCKIFY_API_KEY, CLOCKIFY_BASE_URL, CLOCKIFY_REPORTS_URL

log = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _build_session(api_key: str) -> requests.Session:
    """Create a session with automatic retries and required headers."""
    session = requests.Session()
    session.headers.update({
        "X-Api-Key":    api_key,
        "Content-Type": "application/json",
        "Accept":       "application/json",
    })
    retry = Retry(
        total=4,
        backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def _parse_iso_duration(duration: str) -> int:
    """
    Convert ISO 8601 duration string → total seconds.
    Handles: PT8H30M15S, PT45M, PT3600S, PT0S, null/"".
    """
    if not duration:
        return 0
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", duration)
    if not m:
        return 0
    h    = int(m.group(1) or 0)
    mins = int(m.group(2) or 0)
    secs = float(m.group(3) or 0)
    return int(h * 3600 + mins * 60 + secs)


def _month_bounds(year: int, month: int) -> tuple[str, str]:
    """Return (start_iso, end_iso) covering the full calendar month."""
    _, last_day = monthrange(year, month)
    start = f"{year:04d}-{month:02d}-01T00:00:00.000Z"
    end   = f"{year:04d}-{month:02d}-{last_day:02d}T23:59:59.999Z"
    return start, end


# ── client ────────────────────────────────────────────────────────────────────

class ClockifyClient:
    """
    Thin Clockify API wrapper.

    Public interface:
        client.get_monthly_hours(year, month) → Dict[user_name, hours_float]
        client.get_users()                    → List[user_dict]
        client.workspace_id                   → str
    """

    def __init__(self, api_key: str = CLOCKIFY_API_KEY):
        self._api_key       = api_key
        self._session       = _build_session(api_key)
        self._workspace_id: Optional[str] = None

    # ── workspace ─────────────────────────────────────────────────────────────

    def _ensure_workspace(self) -> str:
        if self._workspace_id:
            return self._workspace_id
        resp = self._session.get(f"{CLOCKIFY_BASE_URL}/workspaces", timeout=15)
        resp.raise_for_status()
        workspaces = resp.json()
        if not workspaces:
            raise RuntimeError("No Clockify workspaces found for this API key.")
        ws = workspaces[0]
        self._workspace_id = ws["id"]
        log.info("Workspace: %s  (id=%s)", ws.get("name"), self._workspace_id)
        return self._workspace_id

    @property
    def workspace_id(self) -> str:
        return self._ensure_workspace()

    # ── users ─────────────────────────────────────────────────────────────────

    def get_users(self) -> List[Dict]:
        """Return all users visible in the workspace."""
        resp = self._session.get(
            f"{CLOCKIFY_BASE_URL}/workspaces/{self.workspace_id}/users",
            params={"page-size": 200},
            timeout=15,
        )
        resp.raise_for_status()
        users = resp.json()
        log.info("Fetched %d workspace users.", len(users))
        return users

    # ── time entries (standard API – paginated per user) ──────────────────────

    def _get_entries_for_user(
        self,
        user_id: str,
        start_iso: str,
        end_iso: str,
        page_size: int = 50,
    ) -> List[Dict]:
        """Paginate through all time entries for one user in a date range."""
        wid = self.workspace_id
        all_entries: List[Dict] = []
        page = 1
        while True:
            resp = self._session.get(
                f"{CLOCKIFY_BASE_URL}/workspaces/{wid}/user/{user_id}/time-entries",
                params={
                    "start":     start_iso,
                    "end":       end_iso,
                    "page":      page,
                    "page-size": page_size,
                },
                timeout=20,
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            all_entries.extend(batch)
            if len(batch) < page_size:
                break
            page += 1
        return all_entries

    def get_monthly_hours_standard(self, year: int, month: int) -> Dict[str, float]:
        """
        Aggregate hours per user via the standard time-entries endpoint.
        Slower (N users × paginated calls) but works on all plans.
        """
        start, end = _month_bounds(year, month)
        users = self.get_users()
        user_hours: Dict[str, float] = {}

        for i, user in enumerate(users, 1):
            uid  = user["id"]
            name = user.get("name", f"Unknown-{uid}")
            log.debug("  [%d/%d] Fetching entries for %s …", i, len(users), name)

            entries    = self._get_entries_for_user(uid, start, end)
            total_secs = sum(
                _parse_iso_duration(e.get("timeInterval", {}).get("duration", ""))
                for e in entries
            )
            hours = round(total_secs / 3600, 2)
            if hours > 0:
                user_hours[name] = hours
                log.debug("    → %.2f h", hours)

        log.info("Standard API: %d users with tracked time.", len(user_hours))
        return user_hours

    # ── time entries (Reports API – single aggregated call) ───────────────────

    def get_monthly_hours_reports(self, year: int, month: int) -> Dict[str, float]:
        """
        Aggregate hours per user via the Clockify Reports summary endpoint.
        One POST call; much faster than the standard API.
        Falls back to standard API on any error.
        """
        start, end = _month_bounds(year, month)
        wid        = self.workspace_id

        payload = {
            "dateRangeStart": start,
            "dateRangeEnd":   end,
            "summaryFilter":  {"groups": ["USER"]},
            "exportType":     "JSON",
        }

        try:
            resp = self._session.post(
                f"{CLOCKIFY_REPORTS_URL}/workspaces/{wid}/reports/summary",
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            user_hours: Dict[str, float] = {}
            for group in data.get("groupOne", []):
                name = group.get("name", "Unknown")
                # Reports API returns duration already in seconds
                secs  = group.get("duration", 0) or group.get("totalTime", 0)
                hours = round(int(secs) / 3600, 2)
                if hours > 0:
                    user_hours[name] = hours

            log.info("Reports API: %d users with tracked time.", len(user_hours))
            return user_hours

        except Exception as exc:
            log.warning(
                "Reports API failed (%s). Falling back to standard time-entries API.",
                exc,
            )
            return self.get_monthly_hours_standard(year, month)

    # ── primary public method ─────────────────────────────────────────────────

    def get_monthly_hours(self, year: int, month: int) -> Dict[str, float]:
        """
        Return {user_display_name: total_hours} for the given month.
        Tries Reports API first; falls back to standard API automatically.
        """
        log.info(
            "Fetching Clockify hours for %s %d …",
            datetime(year, month, 1).strftime("%B"),
            year,
        )
        return self.get_monthly_hours_reports(year, month)
