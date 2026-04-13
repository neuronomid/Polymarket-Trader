"""Context compression utilities.

Hard requirement before any Tier A (Opus) call:
- Deduplicate evidence items
- Compress logs to decision-critical fields only
- Remove boilerplate and low-signal text
- Preserve only state that materially affects the decision

These are deterministic text transformations, not LLM-based summarization.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

import structlog

_log = structlog.get_logger(component="compression")


# --- Evidence Deduplication ---


def deduplicate_evidence(
    evidence_items: list[dict[str, Any]],
    *,
    key_fields: tuple[str, ...] = ("source", "content", "url"),
) -> list[dict[str, Any]]:
    """Remove duplicate evidence items based on content hash.

    Args:
        evidence_items: List of evidence dictionaries.
        key_fields: Fields to use for deduplication fingerprinting.

    Returns:
        Deduplicated evidence list (preserves first occurrence order).
    """
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []

    for item in evidence_items:
        # Build fingerprint from key fields
        fingerprint_parts = []
        for field in key_fields:
            value = str(item.get(field, "")).strip().lower()
            fingerprint_parts.append(value)

        fingerprint = hashlib.md5(
            "|".join(fingerprint_parts).encode(), usedforsecurity=False
        ).hexdigest()

        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append(item)

    removed = len(evidence_items) - len(unique)
    if removed > 0:
        _log.debug("evidence_deduplicated", removed=removed, remaining=len(unique))

    return unique


# --- Log Compression ---

# Fields that are decision-critical and should be preserved
_DECISION_CRITICAL_FIELDS = frozenset({
    "decision",
    "outcome",
    "reason",
    "reason_code",
    "rule_name",
    "threshold",
    "value",
    "severity",
    "trigger_class",
    "trigger_level",
    "approval",
    "score",
    "edge",
    "net_edge",
    "probability",
    "confidence",
    "cost_usd",
    "drawdown_level",
    "risk_approval",
    "position_id",
    "market_id",
    "timestamp",
    "error",
    "warning",
})

# Fields to always strip (boilerplate / low-signal)
_STRIP_FIELDS = frozenset({
    "stack_info",
    "stack_trace",
    "hostname",
    "pid",
    "thread_id",
    "thread_name",
    "process_name",
    "logger",
    "module",
    "funcName",
    "lineno",
    "pathname",
    "filename",
})


def compress_log_entries(
    log_entries: list[dict[str, Any]],
    *,
    max_entries: int = 50,
    preserve_fields: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """Compress log entries to decision-critical fields only.

    Args:
        log_entries: Raw log entries.
        max_entries: Maximum number of entries to keep (keeps most recent).
        preserve_fields: Additional fields to preserve beyond defaults.

    Returns:
        Compressed log entries with only decision-relevant fields.
    """
    critical_fields = _DECISION_CRITICAL_FIELDS
    if preserve_fields:
        critical_fields = critical_fields | preserve_fields

    # Keep most recent entries
    entries = log_entries[-max_entries:] if len(log_entries) > max_entries else log_entries

    compressed: list[dict[str, Any]] = []
    for entry in entries:
        compressed_entry: dict[str, Any] = {}
        for key, value in entry.items():
            if key in _STRIP_FIELDS:
                continue
            if key in critical_fields or key == "event" or key == "level":
                compressed_entry[key] = value
        if compressed_entry:
            compressed.append(compressed_entry)

    original = len(log_entries)
    final = len(compressed)
    if original != final:
        _log.debug("logs_compressed", original=original, final=final)

    return compressed


# --- Text Compression ---

# Boilerplate patterns
_BOILERPLATE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^\s*$"),  # blank lines
    re.compile(r"^-{3,}$"),  # horizontal rules
    re.compile(r"^={3,}$"),  # horizontal rules
    re.compile(r"^\s*#\s*$"),  # empty headings
    re.compile(r"^Note:\s*This\s+is\s+", re.IGNORECASE),
    re.compile(r"^Disclaimer:\s*", re.IGNORECASE),
    re.compile(r"^Please\s+note\s+that\s+", re.IGNORECASE),
    re.compile(r"^As\s+(?:an?\s+)?(?:AI|language\s+model)", re.IGNORECASE),
]


def compress_text(
    text: str,
    *,
    max_chars: int = 8000,
    remove_boilerplate: bool = True,
) -> str:
    """Compress text by removing boilerplate and truncating.

    Args:
        text: Input text.
        max_chars: Maximum character count for output.
        remove_boilerplate: Whether to strip boilerplate patterns.

    Returns:
        Compressed text.
    """
    if not text:
        return ""

    lines = text.splitlines()

    if remove_boilerplate:
        kept: list[str] = []
        consecutive_blank = 0
        for line in lines:
            # Check boilerplate patterns
            is_boilerplate = any(pattern.match(line) for pattern in _BOILERPLATE_PATTERNS)
            if is_boilerplate:
                consecutive_blank += 1
                if consecutive_blank <= 1:
                    kept.append("")  # Keep max one blank line
                continue
            consecutive_blank = 0
            kept.append(line)
        lines = kept

    result = "\n".join(lines).strip()

    # Truncate to max_chars
    if len(result) > max_chars:
        result = result[:max_chars].rsplit("\n", 1)[0]
        result += "\n[... truncated for compression]"

    return result


# --- Full Context Compression Pipeline ---


def compress_context_for_tier_a(
    context: dict[str, Any],
    *,
    max_evidence_items: int = 10,
    max_log_entries: int = 30,
    max_text_chars: int = 6000,
) -> dict[str, Any]:
    """Full compression pipeline before a Tier A (Opus) call.

    Applies all compression strategies:
    1. Deduplicate evidence items
    2. Compress logs to decision-critical fields
    3. Remove boilerplate from text fields
    4. Truncate oversized fields

    Args:
        context: Agent context dictionary.
        max_evidence_items: Max evidence items to keep.
        max_log_entries: Max log entries to keep.
        max_text_chars: Max characters for text fields.

    Returns:
        Compressed context dictionary.
    """
    compressed = dict(context)

    # 1. Deduplicate and limit evidence
    for key in ("evidence", "supporting_evidence", "opposing_evidence", "evidence_items"):
        if key in compressed and isinstance(compressed[key], list):
            deduped = deduplicate_evidence(compressed[key])
            compressed[key] = deduped[:max_evidence_items]

    # 2. Compress logs
    for key in ("logs", "log_entries", "workflow_logs", "review_logs"):
        if key in compressed and isinstance(compressed[key], list):
            compressed[key] = compress_log_entries(
                compressed[key], max_entries=max_log_entries
            )

    # 3. Compress text fields
    for key in ("thesis", "analysis", "summary", "notes", "description"):
        if key in compressed and isinstance(compressed[key], str):
            compressed[key] = compress_text(
                compressed[key], max_chars=max_text_chars
            )

    # 4. Remove empty/None values
    compressed = {k: v for k, v in compressed.items() if v is not None and v != "" and v != []}

    _log.debug(
        "context_compressed_for_tier_a",
        original_keys=len(context),
        compressed_keys=len(compressed),
    )

    return compressed
