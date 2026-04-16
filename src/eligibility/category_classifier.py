"""Deterministic category classifier.

Maps market tags, slugs, and metadata to allowed/excluded categories.
Tier D: fully deterministic pattern matching. LLM escalation is flagged
but NOT implemented here (reserved for genuinely ambiguous cases, rare).

Spec: Phase 4 Step 1.
"""

from __future__ import annotations

import re

from core.constants import CATEGORY_QUALITY_TIERS
from core.enums import Category, CategoryQualityTier, ExcludedCategory
from eligibility.types import CategoryClassification

# --- Category keyword mappings ---
# These are the deterministic patterns applied to tags, slugs, titles, and
# the raw category string from the Gamma API.

# --- Title-first override patterns for Polymarket miscategorization ---
# Applied BEFORE the API category check (Step 0). These patterns are high-confidence
# signals that override a wrong raw_category from the Gamma API.

_TITLE_GEOPOLITICS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r'\b(?:missile|airstrike|air\s+strike|drone\s+strike|naval\s+strike|military\s+action|ground\s+invasion|ceasefire|blockade)\b',
        re.IGNORECASE,
    ),
    re.compile(
        r'\b(?:iran|ukraine|russia|israel|gaza|hamas|hezbollah|nato|houthis?)\b.*\b(?:strike|attack|bomb|invade|weapon|military)\b',
        re.IGNORECASE,
    ),
    re.compile(
        r'\b(?:strike|attack|bomb|invade|weapon|military)\b.*\b(?:iran|ukraine|russia|israel|gaza|hamas|hezbollah|houthis?)\b',
        re.IGNORECASE,
    ),
]

_TITLE_SPORTS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'\b(?:ipl|indian\s+premier\s+league)\b', re.IGNORECASE),
    re.compile(r'\b(?:nba|nfl|mlb|nhl|ufc|mma)\s+(?:playoffs?|finals?|championship)\b', re.IGNORECASE),
    re.compile(
        r'\b(?:vs\.?|versus)\b.*\b(?:win|beat|defeat|draw|match|game|series|innings|final)\b',
        re.IGNORECASE,
    ),
    re.compile(
        r'\b(?:match|game|series)\b.*\b(?:draw|win|winner)\b',
        re.IGNORECASE,
    ),
    re.compile(
        r'\b(?:end|ends)\s+in\s+a\s+draw\b',
        re.IGNORECASE,
    ),
]

_EXCLUDED_KEYWORDS: dict[str, ExcludedCategory] = {
    # News
    "news": ExcludedCategory.NEWS,
    "breaking": ExcludedCategory.NEWS,
    "headline": ExcludedCategory.NEWS,
    "media": ExcludedCategory.NEWS,
    # Culture
    "culture": ExcludedCategory.CULTURE,
    "entertainment": ExcludedCategory.CULTURE,
    "celebrity": ExcludedCategory.CULTURE,
    "movies": ExcludedCategory.CULTURE,
    "tv": ExcludedCategory.CULTURE,
    "music": ExcludedCategory.CULTURE,
    "pop culture": ExcludedCategory.CULTURE,
    "pop-culture": ExcludedCategory.CULTURE,
    "social media": ExcludedCategory.CULTURE,
    "viral": ExcludedCategory.CULTURE,
    "influencer": ExcludedCategory.CULTURE,
    # Crypto
    "crypto": ExcludedCategory.CRYPTO,
    "cryptocurrency": ExcludedCategory.CRYPTO,
    "bitcoin": ExcludedCategory.CRYPTO,
    "ethereum": ExcludedCategory.CRYPTO,
    "defi": ExcludedCategory.CRYPTO,
    "nft": ExcludedCategory.CRYPTO,
    "token": ExcludedCategory.CRYPTO,
    "blockchain": ExcludedCategory.CRYPTO,
    # Weather
    "weather": ExcludedCategory.WEATHER,
    "temperature": ExcludedCategory.WEATHER,
    "hurricane": ExcludedCategory.WEATHER,
    "storm": ExcludedCategory.WEATHER,
    "climate": ExcludedCategory.WEATHER,
}

_ALLOWED_KEYWORDS: dict[str, Category] = {
    # Politics
    "politics": Category.POLITICS,
    "election": Category.POLITICS,
    "congress": Category.POLITICS,
    "senate": Category.POLITICS,
    "president": Category.POLITICS,
    "presidential": Category.POLITICS,
    "governor": Category.POLITICS,
    "legislation": Category.POLITICS,
    "bill": Category.POLITICS,
    "vote": Category.POLITICS,
    "primary": Category.POLITICS,
    "ballot": Category.POLITICS,
    "impeachment": Category.POLITICS,
    "party": Category.POLITICS,
    "democrat": Category.POLITICS,
    "republican": Category.POLITICS,
    "political": Category.POLITICS,
    # Geopolitics
    "geopolitics": Category.GEOPOLITICS,
    "international": Category.GEOPOLITICS,
    "diplomacy": Category.GEOPOLITICS,
    "treaty": Category.GEOPOLITICS,
    "sanctions": Category.GEOPOLITICS,
    "war": Category.GEOPOLITICS,
    "conflict": Category.GEOPOLITICS,
    "nato": Category.GEOPOLITICS,
    "united nations": Category.GEOPOLITICS,
    "foreign policy": Category.GEOPOLITICS,
    "tariff": Category.GEOPOLITICS,
    "trade war": Category.GEOPOLITICS,
    "iran": Category.GEOPOLITICS,
    "ukraine": Category.GEOPOLITICS,
    "russia": Category.GEOPOLITICS,
    "missile": Category.GEOPOLITICS,
    "airstrike": Category.GEOPOLITICS,
    "air strike": Category.GEOPOLITICS,
    "military action": Category.GEOPOLITICS,
    "naval": Category.GEOPOLITICS,
    "ground forces": Category.GEOPOLITICS,
    "ceasefire": Category.GEOPOLITICS,
    "occupation": Category.GEOPOLITICS,
    "blockade": Category.GEOPOLITICS,
    # Technology
    "technology": Category.TECHNOLOGY,
    "tech": Category.TECHNOLOGY,
    "ai": Category.TECHNOLOGY,
    "artificial intelligence": Category.TECHNOLOGY,
    "saas": Category.TECHNOLOGY,
    "apple": Category.TECHNOLOGY,
    "google": Category.TECHNOLOGY,
    "microsoft": Category.TECHNOLOGY,
    "semiconductor": Category.TECHNOLOGY,
    "regulation tech": Category.TECHNOLOGY,
    "antitrust": Category.TECHNOLOGY,
    "startup": Category.TECHNOLOGY,
    # Science & Health
    "science": Category.SCIENCE_HEALTH,
    "health": Category.SCIENCE_HEALTH,
    "fda": Category.SCIENCE_HEALTH,
    "drug": Category.SCIENCE_HEALTH,
    "pharmaceutical": Category.SCIENCE_HEALTH,
    "clinical trial": Category.SCIENCE_HEALTH,
    "vaccine": Category.SCIENCE_HEALTH,
    "pandemic": Category.SCIENCE_HEALTH,
    "medical": Category.SCIENCE_HEALTH,
    "research": Category.SCIENCE_HEALTH,
    "nasa": Category.SCIENCE_HEALTH,
    "space": Category.SCIENCE_HEALTH,
    # Macro / Policy
    "macro": Category.MACRO_POLICY,
    "federal reserve": Category.MACRO_POLICY,
    "fed": Category.MACRO_POLICY,
    "interest rate": Category.MACRO_POLICY,
    "inflation": Category.MACRO_POLICY,
    "gdp": Category.MACRO_POLICY,
    "unemployment": Category.MACRO_POLICY,
    "fiscal": Category.MACRO_POLICY,
    "monetary": Category.MACRO_POLICY,
    "central bank": Category.MACRO_POLICY,
    "economic": Category.MACRO_POLICY,
    "economy": Category.MACRO_POLICY,
    "cpi": Category.MACRO_POLICY,
    # Sports
    "sports": Category.SPORTS,
    "nba": Category.SPORTS,
    "nfl": Category.SPORTS,
    "mlb": Category.SPORTS,
    "nhl": Category.SPORTS,
    "soccer": Category.SPORTS,
    "football": Category.SPORTS,
    "basketball": Category.SPORTS,
    "baseball": Category.SPORTS,
    "tennis": Category.SPORTS,
    "ufc": Category.SPORTS,
    "mma": Category.SPORTS,
    "boxing": Category.SPORTS,
    "cricket": Category.SPORTS,
    "formula 1": Category.SPORTS,
    "f1": Category.SPORTS,
    "premier league": Category.SPORTS,
    "champions league": Category.SPORTS,
    "world cup": Category.SPORTS,
    "super bowl": Category.SPORTS,
    "stanley cup": Category.SPORTS,
    "world series": Category.SPORTS,
    "olympics": Category.SPORTS,
    "ipl": Category.SPORTS,
    "indian premier": Category.SPORTS,
    "la liga": Category.SPORTS,
    "bundesliga": Category.SPORTS,
    "serie a": Category.SPORTS,
    "ligue 1": Category.SPORTS,
    "mls": Category.SPORTS,
    "pga": Category.SPORTS,
    "grand slam": Category.SPORTS,
    "wimbledon": Category.SPORTS,
    "nascar": Category.SPORTS,
    "indy": Category.SPORTS,
}

# Maps Gamma API category strings to our internal categories.
# Covers standard values plus common Polymarket variants (hyphenated, spaced, shorthand).
_API_CATEGORY_MAP: dict[str, Category] = {
    # --- Politics ---
    "politics": Category.POLITICS,
    "us-politics": Category.POLITICS,
    "us politics": Category.POLITICS,
    "american politics": Category.POLITICS,
    "us elections": Category.POLITICS,
    "us election": Category.POLITICS,
    "elections": Category.POLITICS,
    "political": Category.POLITICS,
    "trump": Category.POLITICS,
    "government": Category.POLITICS,
    # --- Geopolitics ---
    "world-politics": Category.GEOPOLITICS,
    "world politics": Category.GEOPOLITICS,
    "geopolitics": Category.GEOPOLITICS,
    "international": Category.GEOPOLITICS,
    "international relations": Category.GEOPOLITICS,
    "middle east": Category.GEOPOLITICS,
    "ukraine": Category.GEOPOLITICS,
    "russia": Category.GEOPOLITICS,
    "iran": Category.GEOPOLITICS,
    "china": Category.GEOPOLITICS,
    "taiwan": Category.GEOPOLITICS,
    "global": Category.GEOPOLITICS,
    "war": Category.GEOPOLITICS,
    "conflict": Category.GEOPOLITICS,
    # --- Technology ---
    "technology": Category.TECHNOLOGY,
    "tech": Category.TECHNOLOGY,
    "ai": Category.TECHNOLOGY,
    "artificial intelligence": Category.TECHNOLOGY,
    "crypto-tech": Category.TECHNOLOGY,
    "science-tech": Category.TECHNOLOGY,
    # --- Science & Health ---
    "science": Category.SCIENCE_HEALTH,
    "health": Category.SCIENCE_HEALTH,
    "science-health": Category.SCIENCE_HEALTH,
    "science & health": Category.SCIENCE_HEALTH,
    "medicine": Category.SCIENCE_HEALTH,
    "medical": Category.SCIENCE_HEALTH,
    "biotech": Category.SCIENCE_HEALTH,
    "pharma": Category.SCIENCE_HEALTH,
    "pandemic": Category.SCIENCE_HEALTH,
    "space": Category.SCIENCE_HEALTH,
    # --- Macro / Policy ---
    "economics": Category.MACRO_POLICY,
    "macro": Category.MACRO_POLICY,
    "economy": Category.MACRO_POLICY,
    "economic": Category.MACRO_POLICY,
    "finance": Category.MACRO_POLICY,
    "financial markets": Category.MACRO_POLICY,
    "markets": Category.MACRO_POLICY,
    "federal reserve": Category.MACRO_POLICY,
    "fed": Category.MACRO_POLICY,
    "interest rates": Category.MACRO_POLICY,
    "inflation": Category.MACRO_POLICY,
    "business": Category.MACRO_POLICY,
    "trade": Category.MACRO_POLICY,
    "tariffs": Category.MACRO_POLICY,
    # --- Sports ---
    "sports": Category.SPORTS,
    "sport": Category.SPORTS,
    "baseball": Category.SPORTS,
    "basketball": Category.SPORTS,
    "football": Category.SPORTS,
    "soccer": Category.SPORTS,
    "tennis": Category.SPORTS,
    "golf": Category.SPORTS,
    "hockey": Category.SPORTS,
    "mma": Category.SPORTS,
    "boxing": Category.SPORTS,
    "cricket": Category.SPORTS,
    "f1": Category.SPORTS,
    "formula 1": Category.SPORTS,
    "formula one": Category.SPORTS,
    "nba": Category.SPORTS,
    "nfl": Category.SPORTS,
    "mlb": Category.SPORTS,
    "nhl": Category.SPORTS,
    "nascar": Category.SPORTS,
    "ufc": Category.SPORTS,
    "epl": Category.SPORTS,
    "premier league": Category.SPORTS,
    "premier-league": Category.SPORTS,
    "champions league": Category.SPORTS,
    "champions-league": Category.SPORTS,
    "ipl": Category.SPORTS,
    "la liga": Category.SPORTS,
    "bundesliga": Category.SPORTS,
    "olympics": Category.SPORTS,
    "world cup": Category.SPORTS,
    "super bowl": Category.SPORTS,
}

_API_EXCLUDED_MAP: dict[str, ExcludedCategory] = {
    "news": ExcludedCategory.NEWS,
    "culture": ExcludedCategory.CULTURE,
    "entertainment": ExcludedCategory.CULTURE,
    "pop-culture": ExcludedCategory.CULTURE,
    "crypto": ExcludedCategory.CRYPTO,
    "cryptocurrency": ExcludedCategory.CRYPTO,
    "weather": ExcludedCategory.WEATHER,
}


def classify_category(
    *,
    raw_category: str | None = None,
    tags: list[str] | None = None,
    slug: str | None = None,
    title: str = "",
) -> CategoryClassification:
    """Classify a market into an allowed or excluded category.

    Priority order:
    1. Raw API category string (direct map)
    2. Tag-based matching
    3. Slug-based matching
    4. Title keyword matching
    5. Unknown (flagged for potential LLM escalation)

    Returns:
        CategoryClassification with the determined category, exclusion status,
        and quality tier.
    """

    # --- Step 0: Title-first override (fires before API category) ---
    # Catches Polymarket API miscategorization by checking high-confidence
    # title signals before trusting the raw_category field.
    if title:
        norm_title_0 = title.strip().lower()
        for pattern in _TITLE_GEOPOLITICS_PATTERNS:
            if pattern.search(norm_title_0):
                tier = CATEGORY_QUALITY_TIERS.get(Category.GEOPOLITICS.value, "standard")
                return CategoryClassification(
                    category=Category.GEOPOLITICS.value,
                    is_excluded=False,
                    quality_tier=tier,
                    confidence=0.95,
                    classification_method="title_override",
                    raw_category=raw_category,
                )
        for pattern in _TITLE_SPORTS_PATTERNS:
            if pattern.search(norm_title_0):
                tier = CATEGORY_QUALITY_TIERS.get(Category.SPORTS.value, "standard")
                return CategoryClassification(
                    category=Category.SPORTS.value,
                    is_excluded=False,
                    quality_tier=tier,
                    confidence=0.95,
                    classification_method="title_override",
                    raw_category=raw_category,
                )

    # --- Step 1: Try raw API category ---
    if raw_category:
        norm_cat = raw_category.strip().lower().replace(" ", "-")

        # Check excluded first
        if norm_cat in _API_EXCLUDED_MAP:
            excluded = _API_EXCLUDED_MAP[norm_cat]
            return CategoryClassification(
                category=None,
                is_excluded=True,
                quality_tier="excluded",
                confidence=1.0,
                classification_method="api_category_excluded",
                raw_category=raw_category,
            )

        # Check allowed
        if norm_cat in _API_CATEGORY_MAP:
            cat = _API_CATEGORY_MAP[norm_cat]
            tier = CATEGORY_QUALITY_TIERS.get(cat.value, "standard")
            return CategoryClassification(
                category=cat.value,
                is_excluded=False,
                quality_tier=tier,
                confidence=1.0,
                classification_method="api_category",
                raw_category=raw_category,
            )

    # --- Step 2: Tag-based matching ---
    tags = tags or []
    for tag in tags:
        norm_tag = tag.strip().lower()
        # Check excluded
        for keyword, excluded in _EXCLUDED_KEYWORDS.items():
            if keyword in norm_tag:
                return CategoryClassification(
                    category=None,
                    is_excluded=True,
                    quality_tier="excluded",
                    confidence=0.9,
                    classification_method="tag_match",
                    raw_category=raw_category,
                )
        # Check allowed
        for keyword, cat in _ALLOWED_KEYWORDS.items():
            if keyword in norm_tag:
                tier = CATEGORY_QUALITY_TIERS.get(cat.value, "standard")
                return CategoryClassification(
                    category=cat.value,
                    is_excluded=False,
                    quality_tier=tier,
                    confidence=0.9,
                    classification_method="tag_match",
                    raw_category=raw_category,
                )

    # --- Step 3: Slug-based matching ---
    if slug:
        norm_slug = slug.strip().lower()
        for keyword, excluded in _EXCLUDED_KEYWORDS.items():
            if keyword in norm_slug:
                return CategoryClassification(
                    category=None,
                    is_excluded=True,
                    quality_tier="excluded",
                    confidence=0.85,
                    classification_method="slug_match",
                    raw_category=raw_category,
                )
        for keyword, cat in _ALLOWED_KEYWORDS.items():
            if keyword in norm_slug:
                tier = CATEGORY_QUALITY_TIERS.get(cat.value, "standard")
                return CategoryClassification(
                    category=cat.value,
                    is_excluded=False,
                    quality_tier=tier,
                    confidence=0.85,
                    classification_method="slug_match",
                    raw_category=raw_category,
                )

    # --- Step 4: Title keyword matching ---
    if title:
        norm_title = title.strip().lower()
        for keyword, excluded in _EXCLUDED_KEYWORDS.items():
            if keyword in norm_title:
                return CategoryClassification(
                    category=None,
                    is_excluded=True,
                    quality_tier="excluded",
                    confidence=0.75,
                    classification_method="title_match",
                    raw_category=raw_category,
                )
        for keyword, cat in _ALLOWED_KEYWORDS.items():
            if keyword in norm_title:
                tier = CATEGORY_QUALITY_TIERS.get(cat.value, "standard")
                return CategoryClassification(
                    category=cat.value,
                    is_excluded=False,
                    quality_tier=tier,
                    confidence=0.75,
                    classification_method="title_match",
                    raw_category=raw_category,
                )

    # --- Step 5: Unknown category ---
    return CategoryClassification(
        category=None,
        is_excluded=False,
        quality_tier="unknown",
        confidence=0.0,
        classification_method="unclassified",
        raw_category=raw_category,
    )
