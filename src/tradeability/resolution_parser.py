"""Deterministic Resolution Parser — Tier D.

Checks every surviving candidate for resolution clarity, ambiguity,
source naming, deadline presence, and wording changes. Fully
deterministic — no LLM calls permitted.

From spec Section 9.3:
- Explicit named resolution source
- Explicit resolution deadline
- Ambiguous conditional wording
- Undefined key terms
- Multi-step dependencies
- Unclear jurisdiction
- Counter-intuitive resolution risk
- Contract wording version changes
"""

from __future__ import annotations

import re

import structlog

from tradeability.types import (
    AmbiguousPhrase,
    HardRejectionReason,
    ResolutionCheck,
    ResolutionClarity,
    ResolutionParseInput,
    ResolutionParseOutput,
)

_log = structlog.get_logger(component="resolution_parser")

# --- Ambiguous wording patterns ---

# Phrases that signal conditional/discretionary resolution
_AMBIGUOUS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bmay\b", re.IGNORECASE), "Conditional: 'may'"),
    (re.compile(r"\bcould\b", re.IGNORECASE), "Conditional: 'could'"),
    (re.compile(r"\bmight\b", re.IGNORECASE), "Conditional: 'might'"),
    (re.compile(r"\bat the discretion of\b", re.IGNORECASE), "Discretionary resolution"),
    (re.compile(r"\bsubject to\b", re.IGNORECASE), "Conditional dependency"),
    (re.compile(r"\bif deemed\b", re.IGNORECASE), "Subjective determination"),
    (re.compile(r"\breasonable\b", re.IGNORECASE), "Subjective standard"),
    (re.compile(r"\bmaterial(ly)?\b", re.IGNORECASE), "Undefined materiality threshold"),
    (re.compile(r"\bsubstantial(ly)?\b", re.IGNORECASE), "Undefined substantiality threshold"),
    (re.compile(r"\bsignificant(ly)?\b", re.IGNORECASE), "Undefined significance threshold"),
    (re.compile(r"\bsole judgment\b", re.IGNORECASE), "Unilateral discretion"),
    (re.compile(r"\binterpret(ed|ation)?\b", re.IGNORECASE), "Interpretation-dependent"),
]

# Phrases suggesting multi-step or conditional resolution
_MULTI_STEP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\band then\b", re.IGNORECASE),
    re.compile(r"\bfollowed by\b", re.IGNORECASE),
    re.compile(r"\bcontingent (on|upon)\b", re.IGNORECASE),
    re.compile(r"\bonly if\b", re.IGNORECASE),
    re.compile(r"\bprovided that\b", re.IGNORECASE),
    re.compile(r"\bunless\b", re.IGNORECASE),
    re.compile(r"\bexcept (if|when|where)\b", re.IGNORECASE),
]

# Jurisdiction-related patterns
_JURISDICTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bjurisdiction\b", re.IGNORECASE),
    re.compile(r"\bgoverning law\b", re.IGNORECASE),
    re.compile(r"\bapplicable law\b", re.IGNORECASE),
    re.compile(r"\bregulatory\b", re.IGNORECASE),
]

# Counter-intuitive resolution risk patterns
_COUNTER_INTUITIVE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\btechnically\b", re.IGNORECASE),
    re.compile(r"\blegal(ly)? (but|however)\b", re.IGNORECASE),
    re.compile(r"\bde facto\b", re.IGNORECASE),
    re.compile(r"\bde jure\b", re.IGNORECASE),
    re.compile(r"\bnarrowly\b", re.IGNORECASE),
    re.compile(r"\bstrictly speaking\b", re.IGNORECASE),
]

# Known resolution source indicators
_SOURCE_INDICATORS: list[re.Pattern[str]] = [
    re.compile(r"\bofficial\b", re.IGNORECASE),
    re.compile(r"\bgovernment\b", re.IGNORECASE),
    re.compile(r"\bfederal\b", re.IGNORECASE),
    re.compile(r"\bAP\b"),
    re.compile(r"\bReuters\b", re.IGNORECASE),
    re.compile(r"\bBloomberg\b", re.IGNORECASE),
    re.compile(r"\baccording to\b", re.IGNORECASE),
    re.compile(r"\breported by\b", re.IGNORECASE),
    re.compile(r"\bper\b", re.IGNORECASE),
    re.compile(r"\bcourt\b", re.IGNORECASE),
    re.compile(r"\bcommission\b", re.IGNORECASE),
    re.compile(r"\bbureau\b", re.IGNORECASE),
    re.compile(r"\bagency\b", re.IGNORECASE),
]


class ResolutionParser:
    """Deterministic resolution parser — Tier D.

    Runs all resolution checks on a candidate's contract wording
    and metadata. Produces a ResolutionParseOutput with clarity
    classification and any detected issues.

    Usage:
        parser = ResolutionParser()
        result = parser.parse(input_data)
        if result.is_rejected:
            # candidate auto-rejected
        elif result.has_residual_ambiguity:
            # needs Tier B synthesizer review
    """

    def __init__(
        self,
        *,
        min_depth_usd: float = 50.0,
        max_spread: float = 0.15,
    ) -> None:
        self._min_depth_usd = min_depth_usd
        self._max_spread = max_spread

    def parse(self, input_data: ResolutionParseInput) -> ResolutionParseOutput:
        """Run all deterministic resolution checks.

        Args:
            input_data: Resolution parse input with market data and wording.

        Returns:
            ResolutionParseOutput with clarity and detected issues.
        """
        checks: list[ResolutionCheck] = []
        ambiguous_phrases: list[AmbiguousPhrase] = []
        undefined_terms: list[str] = []
        flagged_items: list[str] = []

        # Combine title, description, and contract wording for analysis
        full_text = self._assemble_text(input_data)

        # Check 1: Explicit named resolution source
        has_named_source = self._check_named_source(input_data, full_text)
        checks.append(ResolutionCheck(
            check_name="named_resolution_source",
            passed=has_named_source,
            detail="Resolution source identified" if has_named_source else "No explicit resolution source found",
            severity="critical" if not has_named_source else "info",
        ))

        # Check 2: Explicit resolution deadline
        has_explicit_deadline = self._check_deadline(input_data)
        checks.append(ResolutionCheck(
            check_name="explicit_deadline",
            passed=has_explicit_deadline,
            detail="Deadline present" if has_explicit_deadline else "No explicit resolution deadline",
            severity="warning" if not has_explicit_deadline else "info",
        ))

        # Check 3: Ambiguous conditional wording
        found_ambiguous = self._check_ambiguous_wording(full_text)
        has_ambiguous = len(found_ambiguous) > 0
        ambiguous_phrases.extend(found_ambiguous)
        checks.append(ResolutionCheck(
            check_name="ambiguous_wording",
            passed=not has_ambiguous,
            detail=f"Found {len(found_ambiguous)} ambiguous phrase(s)" if has_ambiguous else "No ambiguous wording detected",
            severity="warning" if has_ambiguous else "info",
        ))

        # Check 4: Undefined key terms
        found_undefined = self._check_undefined_terms(full_text)
        has_undefined = len(found_undefined) > 0
        undefined_terms.extend(found_undefined)
        checks.append(ResolutionCheck(
            check_name="undefined_terms",
            passed=not has_undefined,
            detail=f"Found {len(found_undefined)} potentially undefined term(s)" if has_undefined else "No undefined terms detected",
            severity="warning" if has_undefined else "info",
        ))

        # Check 5: Multi-step dependencies
        has_multi_step = self._check_multi_step(full_text)
        checks.append(ResolutionCheck(
            check_name="multi_step_dependencies",
            passed=not has_multi_step,
            detail="Multi-step or conditional dependencies detected" if has_multi_step else "No multi-step dependencies",
            severity="warning" if has_multi_step else "info",
        ))

        # Check 6: Unclear jurisdiction
        has_unclear_jurisdiction = self._check_jurisdiction(full_text)
        checks.append(ResolutionCheck(
            check_name="jurisdiction_clarity",
            passed=not has_unclear_jurisdiction,
            detail="Jurisdiction references may be unclear" if has_unclear_jurisdiction else "No jurisdiction concerns",
            severity="warning" if has_unclear_jurisdiction else "info",
        ))

        # Check 7: Counter-intuitive resolution risk
        has_counter_intuitive = self._check_counter_intuitive(full_text)
        checks.append(ResolutionCheck(
            check_name="counter_intuitive_risk",
            passed=not has_counter_intuitive,
            detail="Counter-intuitive resolution risk detected" if has_counter_intuitive else "No counter-intuitive risk",
            severity="critical" if has_counter_intuitive else "info",
        ))

        # Check 8: Contract wording version changes
        wording_changed = self._check_wording_change(input_data)
        checks.append(ResolutionCheck(
            check_name="wording_version_change",
            passed=not wording_changed,
            detail="Contract wording has changed since last check" if wording_changed else "No wording changes detected",
            severity="critical" if wording_changed else "info",
        ))

        # Check 9: Spread/depth hard limits
        spread_depth_ok = self._check_spread_depth(input_data)
        checks.append(ResolutionCheck(
            check_name="spread_depth_limits",
            passed=spread_depth_ok,
            detail="Spread and depth within limits" if spread_depth_ok else "Spread or depth fails hard limits",
            severity="critical" if not spread_depth_ok else "info",
        ))

        # Compile flagged items
        for check in checks:
            if not check.passed:
                flagged_items.append(f"{check.check_name}: {check.detail}")

        # Determine overall clarity and hard rejection
        clarity, rejection_reason, rejection_detail = self._determine_clarity(
            has_named_source=has_named_source,
            has_explicit_deadline=has_explicit_deadline,
            has_ambiguous=has_ambiguous,
            has_undefined=has_undefined,
            has_multi_step=has_multi_step,
            has_counter_intuitive=has_counter_intuitive,
            wording_changed=wording_changed,
            spread_depth_ok=spread_depth_ok,
            ambiguous_count=len(found_ambiguous),
            input_data=input_data,
        )

        result = ResolutionParseOutput(
            market_id=input_data.market_id,
            clarity=clarity,
            checks=checks,
            has_named_source=has_named_source,
            has_explicit_deadline=has_explicit_deadline,
            has_ambiguous_wording=has_ambiguous,
            has_undefined_terms=has_undefined,
            has_multi_step_deps=has_multi_step,
            has_unclear_jurisdiction=has_unclear_jurisdiction,
            has_counter_intuitive_risk=has_counter_intuitive,
            wording_changed=wording_changed,
            ambiguous_phrases=ambiguous_phrases,
            undefined_terms=undefined_terms,
            flagged_items=flagged_items,
            rejection_reason=rejection_reason,
            rejection_detail=rejection_detail,
        )

        _log.info(
            "resolution_parsed",
            market_id=input_data.market_id,
            clarity=clarity.value,
            checks_passed=sum(1 for c in checks if c.passed),
            checks_failed=sum(1 for c in checks if not c.passed),
            is_rejected=result.is_rejected,
        )

        return result

    # --- Individual checks ---

    def _assemble_text(self, data: ResolutionParseInput) -> str:
        """Assemble all available text for analysis."""
        parts: list[str] = []
        if data.title:
            parts.append(data.title)
        if data.description:
            parts.append(data.description)
        if data.contract_wording:
            parts.append(data.contract_wording)
        return " ".join(parts)

    def _check_named_source(self, data: ResolutionParseInput, text: str) -> bool:
        """Check for an explicit named resolution source."""
        # If resolution_source field is provided and non-empty, it counts
        if data.resolution_source and len(data.resolution_source.strip()) > 3:
            return True

        # Check text for source indicators
        matches = sum(1 for pattern in _SOURCE_INDICATORS if pattern.search(text))
        return matches >= 2  # need at least 2 source indicators in text

    def _check_deadline(self, data: ResolutionParseInput) -> bool:
        """Check for an explicit resolution deadline."""
        if data.resolution_deadline is not None:
            return True
        if data.end_date_hours is not None and data.end_date_hours > 0:
            return True
        return False

    def _check_ambiguous_wording(self, text: str) -> list[AmbiguousPhrase]:
        """Detect ambiguous conditional wording patterns."""
        found: list[AmbiguousPhrase] = []
        for pattern, description in _AMBIGUOUS_PATTERNS:
            matches = list(pattern.finditer(text))
            for match in matches:
                start = max(0, match.start() - 30)
                end = min(len(text), match.end() + 30)
                context = text[start:end].strip()
                found.append(AmbiguousPhrase(
                    phrase=match.group(),
                    context=context,
                    severity="medium",
                ))
        return found

    def _check_undefined_terms(self, text: str) -> list[str]:
        """Detect potentially undefined key terms.

        Looks for quoted terms, capitalized multi-word phrases that
        might be special definitions, and common undefined markers.
        """
        undefined: list[str] = []

        # Quoted terms that might be undefined
        quoted = re.findall(r'"([^"]{2,50})"', text)
        for term in quoted:
            # Skip common non-definition quotes
            if term.lower() not in {"yes", "no", "true", "false"}:
                undefined.append(term)

        return undefined[:5]  # cap at 5 to avoid noise

    def _check_multi_step(self, text: str) -> bool:
        """Check for multi-step conditional dependencies."""
        return any(pattern.search(text) for pattern in _MULTI_STEP_PATTERNS)

    def _check_jurisdiction(self, text: str) -> bool:
        """Check for unclear jurisdiction references.

        Only flags if jurisdiction is mentioned but ambiguously.
        """
        has_jurisdiction_ref = any(p.search(text) for p in _JURISDICTION_PATTERNS)
        if not has_jurisdiction_ref:
            return False  # No jurisdiction mentioned — not a concern

        # If jurisdiction is mentioned alongside ambiguous wording, it's unclear
        has_ambiguity = any(
            p.search(text) for p, _ in _AMBIGUOUS_PATTERNS[:5]  # check top ambiguity patterns
        )
        return has_ambiguity

    def _check_counter_intuitive(self, text: str) -> bool:
        """Check for counter-intuitive resolution risk indicators."""
        return any(pattern.search(text) for pattern in _COUNTER_INTUITIVE_PATTERNS)

    def _check_wording_change(self, data: ResolutionParseInput) -> bool:
        """Compare current wording against stored previous version."""
        if data.contract_wording is None or data.previous_wording is None:
            return False

        # Normalize whitespace for comparison
        current = " ".join(data.contract_wording.split())
        previous = " ".join(data.previous_wording.split())
        return current != previous

    def _check_spread_depth(self, data: ResolutionParseInput) -> bool:
        """Check spread and depth against hard limits."""
        # Depth check: must be enough for minimum position size
        if data.depth_usd > 0 and data.depth_usd < data.min_position_size_usd:
            return False

        # Spread check
        if data.spread is not None and data.spread > self._max_spread:
            return False

        return True

    # --- Clarity determination ---

    def _determine_clarity(
        self,
        *,
        has_named_source: bool,
        has_explicit_deadline: bool,
        has_ambiguous: bool,
        has_undefined: bool,
        has_multi_step: bool,
        has_counter_intuitive: bool,
        wording_changed: bool,
        spread_depth_ok: bool,
        ambiguous_count: int,
        input_data: ResolutionParseInput,
    ) -> tuple[ResolutionClarity, HardRejectionReason | None, str | None]:
        """Determine overall clarity classification and hard rejection.

        Returns:
            (clarity, rejection_reason, rejection_detail)
        """
        # --- Hard rejection patterns (auto-reject) ---

        # Spread/depth fails hard limits
        if not spread_depth_ok:
            return (
                ResolutionClarity.REJECT,
                HardRejectionReason.SPREAD_DEPTH_HARD_LIMIT,
                "Spread or depth below hard limit",
            )

        # Counter-intuitive resolution possible
        if has_counter_intuitive and not has_named_source:
            return (
                ResolutionClarity.REJECT,
                HardRejectionReason.COUNTER_INTUITIVE_RESOLUTION,
                "Counter-intuitive resolution risk without clear resolution source",
            )

        # Unstable/unnamed/discretionary resolution source
        if not has_named_source and not has_explicit_deadline:
            return (
                ResolutionClarity.REJECT,
                HardRejectionReason.UNSTABLE_RESOLUTION_SOURCE,
                "No named resolution source and no explicit deadline",
            )

        # Meaningfully ambiguous wording (many ambiguous phrases)
        if ambiguous_count >= 4:
            return (
                ResolutionClarity.REJECT,
                HardRejectionReason.AMBIGUOUS_WORDING,
                f"Heavily ambiguous wording: {ambiguous_count} ambiguous phrases detected",
            )

        # Wording changed significantly
        if wording_changed:
            return (
                ResolutionClarity.REJECT,
                HardRejectionReason.WORDING_CHANGED,
                "Contract wording has changed — requires re-evaluation",
            )

        # Depth below minimum for minimum position size
        if input_data.depth_usd > 0 and input_data.depth_usd < input_data.min_position_size_usd:
            return (
                ResolutionClarity.REJECT,
                HardRejectionReason.DEPTH_BELOW_MINIMUM,
                "Depth below minimum for minimum position size",
            )

        # --- Marginal clarity (residual ambiguity) ---
        issues_count = sum([
            int(has_ambiguous),
            int(has_undefined),
            int(has_multi_step),
            int(not has_named_source),
        ])

        if issues_count >= 2:
            return ResolutionClarity.AMBIGUOUS, None, None

        if issues_count == 1:
            return ResolutionClarity.MARGINAL, None, None

        # --- Clear ---
        return ResolutionClarity.CLEAR, None, None
