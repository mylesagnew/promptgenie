"""redactor.py — PII and secret redaction for prompt text.

Scans prompt text using scanner rules tagged with redactable categories
(secret, data-leakage) and replaces matches with labelled placeholders.

Public API
----------
  ``redact(text, categories=None)``  → RedactResult
  ``RedactResult``                   — dataclass with redacted_text and replacements
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from promptgenie.core.scanner import SCAN_RULES

_REDACTABLE_CATEGORIES = {"secret", "data-leakage"}

# Map from rule ID to a short placeholder label
_RULE_LABELS: dict[str, str] = {
    "SEC_SECRET_APIKEY": "API_KEY",
    "SEC_SECRET_TOKEN": "SECRET_TOKEN",
    "SEC_SECRET_OPENAI": "OPENAI_KEY",
    "SEC_SECRET_GOOGLE": "GOOGLE_KEY",
    "SEC_SECRET_SLACK": "SLACK_TOKEN",
    "SEC_SECRET_PRIVKEY": "PRIVATE_KEY",
    "SEC_SECRET_GITHUB": "GITHUB_TOKEN",
    "SEC_SECRET_AWS_KEY": "AWS_ACCESS_KEY",
    "SEC_SECRET_AWS_SECRET": "AWS_SECRET",
    "LEAK_JWT": "JWT_TOKEN",
    "LEAK_DB_URL": "DB_CONNECTION_STRING",
    "LEAK_INTERNAL_HOST": "INTERNAL_HOST",
    "LEAK_EMAIL": "EMAIL_ADDRESS",
    "LEAK_PHONE": "PHONE_NUMBER",
    "LEAK_CC": "CREDIT_CARD",
    "LEAK_SSN": "SSN",
    "LEAK_IPADDR": "INTERNAL_IP",
    "LEAK_BEARER": "BEARER_TOKEN",
    "LEAK_CUSTOMER_ID": "CUSTOMER_ID",
    "LEAK_SALESFORCE_ID": "SALESFORCE_ID",
    "LEAK_UUID_CUSTOMER": "CUSTOMER_ID",
}


@dataclass
class Redaction:
    rule_id: str
    original: str
    placeholder: str
    start: int
    end: int


@dataclass
class RedactResult:
    redacted_text: str
    replacements: list[Redaction] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.replacements)


def redact(
    text: str,
    categories: set[str] | None = None,
    extra_patterns: list[tuple[str, str]] | None = None,
) -> RedactResult:
    """Return *text* with secrets and PII replaced by labelled placeholders.

    Parameters
    ----------
    text:
        Input prompt text to redact.
    categories:
        Subset of rule categories to redact. Defaults to all redactable
        categories (``secret`` and ``data-leakage``).
    extra_patterns:
        Additional ``(pattern, label)`` pairs to redact beyond built-in rules.
    """
    effective_cats = categories if categories is not None else _REDACTABLE_CATEGORIES

    # Build list of (start, end, placeholder) spans — sorted later
    spans: list[tuple[int, int, str, str, str]] = []  # start, end, placeholder, original, rule_id

    active_rules = [r for r in SCAN_RULES if r.category in effective_cats]

    for rule in active_rules:
        flags = re.IGNORECASE if rule.use_original_text else 0
        flags |= rule.flags
        search_text = text if rule.use_original_text else text.lower()
        label = _RULE_LABELS.get(rule.id, rule.id)
        for m in re.finditer(rule.pattern, search_text, flags):
            spans.append((m.start(), m.end(), f"[REDACTED:{label}]", m.group(0), rule.id))

    # Extra patterns
    for pattern, label in extra_patterns or []:
        for m in re.finditer(pattern, text):
            spans.append((m.start(), m.end(), f"[REDACTED:{label}]", m.group(0), "custom"))

    if not spans:
        return RedactResult(redacted_text=text, replacements=[])

    # Sort by start, then resolve overlaps (keep longest / first)
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    merged: list[tuple[int, int, str, str, str]] = []
    for span in spans:
        if merged and span[0] < merged[-1][1]:
            continue  # overlaps previous — skip
        merged.append(span)

    # Build redacted text
    result_parts: list[str] = []
    redactions: list[Redaction] = []
    prev = 0
    for start, end, placeholder, original, rule_id in merged:
        result_parts.append(text[prev:start])
        result_parts.append(placeholder)
        redactions.append(
            Redaction(
                rule_id=rule_id,
                original=original,
                placeholder=placeholder,
                start=start,
                end=end,
            )
        )
        prev = end
    result_parts.append(text[prev:])

    return RedactResult(
        redacted_text="".join(result_parts),
        replacements=redactions,
    )
