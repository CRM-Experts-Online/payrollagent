"""
learning_engine.py — Self-learning alias store.

Maintains a persistent JSON map of:
    { normalised_clockify_name → canonical_employee_name }

On each run the engine:
  1. Loads the map.
  2. Passes it to NameMatcher so known mappings are applied instantly.
  3. For any user still unmatched after the matching pipeline:
       a. If the best fuzzy candidate ≥ AUTO_ACCEPT_THRESHOLD → accept silently.
       b. If interactive mode is on → prompt the operator to confirm.
       c. Otherwise → leave as unmatched (written to unmatched_users CSV).
  4. Saves the updated map so future runs skip the interaction.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config import ALIAS_FILE, AUTO_ACCEPT_THRESHOLD
from name_matcher import NameMatcher, normalize_name

log = logging.getLogger(__name__)


# ── persistence ───────────────────────────────────────────────────────────────

def load_alias_memory(path: Path = ALIAS_FILE) -> Dict[str, str]:
    """
    Load alias map from JSON.
    Returns an empty dict if the file does not exist yet.
    """
    if path.exists():
        with open(path, "r", encoding="utf-8") as fh:
            data: Dict[str, str] = json.load(fh)
        log.info("Loaded %d aliases from %s", len(data), path.name)
        return data
    log.info("No alias file found at %s — starting with empty map.", path.name)
    return {}


def save_alias_memory(
    alias_map: Dict[str, str],
    path:      Path = ALIAS_FILE,
) -> None:
    """Persist alias map to JSON, sorted for readability."""
    sorted_map = dict(sorted(alias_map.items()))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(sorted_map, fh, indent=2, ensure_ascii=False)
    log.info("Saved %d aliases → %s", len(sorted_map), path.name)


def learn_match(
    alias_map:     Dict[str, str],
    clockify_name: str,
    employee_name: str,
) -> Dict[str, str]:
    """
    Add (or update) a confirmed clockify_name → employee_name mapping.
    The key is the normalised form of the Clockify display name.
    """
    key = normalize_name(clockify_name)
    if alias_map.get(key) != employee_name:
        alias_map[key] = employee_name
        log.info("Learned: '%s' → '%s'", clockify_name, employee_name)
    return alias_map


# ── interactive CLI prompt ────────────────────────────────────────────────────

def _prompt_selection(
    clockify_name: str,
    candidates:    List[Tuple[str, float]],
) -> Optional[str]:
    """
    Display a numbered menu and return the chosen employee name,
    or None if the operator skips (0) or interrupts (Ctrl-C).
    """
    print(f"\n  {'─' * 60}")
    print(f"  Clockify user detected: \033[93m{clockify_name}\033[0m")
    print(f"  Possible matches:")
    for i, (name, score) in enumerate(candidates, 1):
        bar = "█" * int(score / 10)
        print(f"    {i}. {name:<40}  ({score:.0f}%)  {bar}")
    print(f"    0. Skip / mark as unmatched")
    print(f"  {'─' * 60}")

    while True:
        try:
            raw = input(f"  Select [0–{len(candidates)}]: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n  Interrupted — skipping remaining unmatched users.")
            return None

        if not raw:
            continue
        try:
            idx = int(raw)
        except ValueError:
            print(f"  Enter a number between 0 and {len(candidates)}.")
            continue

        if idx == 0:
            return None
        if 1 <= idx <= len(candidates):
            return candidates[idx - 1][0]
        print(f"  Enter a number between 0 and {len(candidates)}.")


# ── batch resolution ──────────────────────────────────────────────────────────

def resolve_unmatched(
    unmatched_names:      List[str],
    matcher:              NameMatcher,
    alias_map:            Dict[str, str],
    interactive:          bool  = True,
    auto_accept_threshold: float = AUTO_ACCEPT_THRESHOLD,
) -> Tuple[Dict[str, str], List[str], Dict[str, str]]:
    """
    Attempt to resolve a list of unmatched Clockify display names.

    Resolution strategy per user:
        - Pull top-5 fuzzy candidates.
        - If best candidate ≥ auto_accept_threshold → accept automatically.
        - Else if interactive → prompt operator.
        - Else → leave unmatched.

    Returns:
        resolved         : {clockify_name → employee_name}  (newly confirmed)
        still_unmatched  : names that remain unresolved
        alias_map        : updated alias map (not yet persisted here)
    """
    if not unmatched_names:
        return {}, [], alias_map

    resolved:         Dict[str, str] = {}
    still_unmatched:  List[str]      = []

    for cname in unmatched_names:
        candidates = matcher.get_top_candidates(cname, n=5)

        if not candidates:
            log.warning("Zero candidates for '%s' — marking unmatched.", cname)
            still_unmatched.append(cname)
            continue

        top_name, top_score = candidates[0]

        # Auto-accept when confidence is very high
        if top_score >= auto_accept_threshold:
            print(
                f"\n  \033[92m[AUTO]\033[0m  '{cname}' → '{top_name}'"
                f"  ({top_score:.0f}%)"
            )
            alias_map = learn_match(alias_map, cname, top_name)
            resolved[cname] = top_name
            continue

        # Interactive confirmation
        if interactive:
            chosen = _prompt_selection(cname, candidates)
            if chosen:
                alias_map = learn_match(alias_map, cname, chosen)
                resolved[cname] = chosen
            else:
                still_unmatched.append(cname)
        else:
            log.warning(
                "No auto-match for '%s' (best: '%s' %.0f%%) — skipping.",
                cname, top_name, top_score,
            )
            still_unmatched.append(cname)

    return resolved, still_unmatched, alias_map
