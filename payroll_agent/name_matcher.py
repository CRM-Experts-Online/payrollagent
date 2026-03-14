"""
name_matcher.py — Multi-layer name matching engine.

Pipeline (highest → lowest confidence):
  1. alias_map      learned/confirmed mappings from name_aliases.json   (100%)
  2. exact_alias    static expanded-alias index built from rate table   (100%)
  3. exact_norm     full normalised employee name                       (100%)
  4. token_subset   all clockify tokens appear in employee token set    (92%)
  5. first_name     unambiguous single-first-name hit                   (90%)
  6. fuzzy          rapidfuzz token_sort_ratio ≥ threshold              (dynamic)
"""
from __future__ import annotations

import re
import logging
from typing import Dict, List, Optional, Tuple

from rapidfuzz import fuzz, process

log = logging.getLogger(__name__)

# Tokens that should not be used as "first names" for matching purposes
_TITLE_TOKENS: frozenset[str] = frozenset({"mr", "ms", "mrs", "dr", "prof", "jr", "sr"})


# ── name normalisation helpers ────────────────────────────────────────────────

def normalize_name(name: str) -> str:
    """
    Lowercase, strip leading/trailing whitespace, collapse inner whitespace,
    remove all punctuation *except* the '/' separator used in dual names.

    Examples:
        'Agustin Ostapovich'          → 'agustin ostapovich'
        'Nowshin / MD Hossin'         → 'nowshin / md hossin'
        'Mr. YT Raghu'                → 'mr yt raghu'
        'Muddasar Hussain / Waleed'   → 'muddasar hussain / waleed'
    """
    name = name.lower()
    name = re.sub(r"[^\w\s/]", " ", name)   # keep alphanumeric, whitespace, /
    name = re.sub(r"\s+", " ", name).strip()
    return name


def expand_aliases(employee_name: str) -> List[str]:
    """
    Split a dual-name employee entry into individual aliases.

    'Nowshin / MD Hossin'
        → ['nowshin / md hossin', 'nowshin', 'md hossin']

    'Muddasar Hussain / Muhammad Waleed Raza'
        → ['muddasar hussain / muhammad waleed raza',
           'muddasar hussain',
           'muhammad waleed raza']
    """
    norm = normalize_name(employee_name)
    aliases: set[str] = {norm}
    if "/" in norm:
        for part in norm.split("/"):
            part = part.strip()
            if part:
                aliases.add(part)
    return list(aliases)


def _first_meaningful_token(norm_name: str) -> Optional[str]:
    """Return the first non-title word from a normalised name."""
    for tok in norm_name.replace("/", " ").split():
        if tok not in _TITLE_TOKENS:
            return tok
    return None


# ── matcher class ─────────────────────────────────────────────────────────────

class NameMatcher:
    """
    Stateful matcher built from an employee list + a learned alias map.

    Construct once per run; reuse for all Clockify user names.

    Args:
        employees   : list of canonical employee names from rate table
        alias_map   : {normalised_clockify_name → canonical_employee_name}
                      loaded from name_aliases.json
        threshold   : minimum rapidfuzz score (0-100) to accept a fuzzy match
    """

    def __init__(
        self,
        employees: List[str],
        alias_map: Dict[str, str],
        threshold: int = 85,
    ):
        self.employees  = employees
        self.alias_map  = alias_map
        self.threshold  = threshold

        # normalised_employee_name → original
        self._norm_to_orig: Dict[str, str] = {}
        # any expanded alias (incl. sub-parts of "/" names) → original
        self._alias_to_orig: Dict[str, str] = {}

        for emp in employees:
            norm = normalize_name(emp)
            self._norm_to_orig[norm] = emp
            for alias in expand_aliases(emp):
                self._alias_to_orig[alias] = emp

        # flat list used as the candidate pool for rapidfuzz
        self._searchable: List[str] = list(self._alias_to_orig.keys())

    # ── public: single match ─────────────────────────────────────────────────

    def match(
        self, clockify_name: str
    ) -> Tuple[Optional[str], float, str]:
        """
        Attempt to match *clockify_name* to a canonical employee name.

        Returns:
            (employee_name | None, confidence_0_to_100, method_label)
        """
        if not clockify_name or not clockify_name.strip():
            return None, 0.0, "empty"

        norm = normalize_name(clockify_name)

        # ── 1. Learned alias map (highest priority) ───────────────────────────
        if norm in self.alias_map:
            log.debug("alias_map  '%s' → '%s'", clockify_name, self.alias_map[norm])
            return self.alias_map[norm], 100.0, "alias_map"

        # ── 2. Exact expanded alias (static index) ────────────────────────────
        if norm in self._alias_to_orig:
            orig = self._alias_to_orig[norm]
            log.debug("exact_alias '%s' → '%s'", clockify_name, orig)
            return orig, 100.0, "exact_alias"

        # ── 3. Exact normalised employee name ─────────────────────────────────
        if norm in self._norm_to_orig:
            orig = self._norm_to_orig[norm]
            log.debug("exact_norm '%s' → '%s'", clockify_name, orig)
            return orig, 100.0, "exact_norm"

        # ── 4. Token-subset match ─────────────────────────────────────────────
        ck_tokens = set(norm.replace("/", " ").split()) - _TITLE_TOKENS
        if ck_tokens:
            for alias, orig in self._alias_to_orig.items():
                emp_tokens = set(alias.replace("/", " ").split()) - _TITLE_TOKENS
                if ck_tokens.issubset(emp_tokens):
                    log.debug("token_subset '%s' → '%s'", clockify_name, orig)
                    return orig, 92.0, "token_subset"

        # ── 5. Unambiguous first-name match ───────────────────────────────────
        first_ck = _first_meaningful_token(norm)
        if first_ck:
            hits: List[str] = []
            for alias, orig in self._alias_to_orig.items():
                first_emp = _first_meaningful_token(alias)
                if first_emp and (
                    first_ck == first_emp or norm.startswith(first_emp)
                ):
                    hits.append(orig)
            unique_hits = list(dict.fromkeys(hits))   # preserve order, dedupe
            if len(unique_hits) == 1:
                log.debug("first_name '%s' → '%s'", clockify_name, unique_hits[0])
                return unique_hits[0], 90.0, "first_name"

        # ── 6. Fuzzy match ────────────────────────────────────────────────────
        if self._searchable:
            result = process.extractOne(
                norm,
                self._searchable,
                scorer=fuzz.token_sort_ratio,
            )
            if result and result[1] >= self.threshold:
                matched_alias = result[0]
                orig = self._alias_to_orig.get(matched_alias)
                if orig:
                    log.debug(
                        "fuzzy(%.0f%%) '%s' → '%s'",
                        result[1], clockify_name, orig,
                    )
                    return orig, float(result[1]), "fuzzy"

        return None, 0.0, "no_match"

    # ── public: candidate list for interactive selection ──────────────────────

    def get_top_candidates(
        self, clockify_name: str, n: int = 5
    ) -> List[Tuple[str, float]]:
        """
        Return up to *n* (employee_name, score) pairs, deduped by employee,
        sorted by descending score.  Used by the interactive resolution prompt.
        """
        norm = normalize_name(clockify_name)
        raw  = process.extract(
            norm,
            self._searchable,
            scorer=fuzz.token_sort_ratio,
            limit=n * 3,
        )
        seen: Dict[str, float] = {}
        for alias, score, _ in raw:
            orig = self._alias_to_orig.get(alias, alias)
            if orig not in seen or seen[orig] < score:
                seen[orig] = score
        return sorted(seen.items(), key=lambda x: x[1], reverse=True)[:n]
