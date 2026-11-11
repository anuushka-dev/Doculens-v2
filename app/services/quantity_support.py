"""Necessary quantity/unit checks for explicitly quantitative questions.

These conservative lexical checks supplement the semantic reviewer. They do
not perform unit conversions or establish general semantic answer correctness.
"""

import re
from collections.abc import Sequence

from app.schemas.answer import Citation

_UNITS = (
    ({"dollar", "dollars", "usd"}, r"\$|(?<![A-Za-z])(?:usd|dollars?)\b", True),
    ({"euro", "euros", "eur"}, r"€|(?<![A-Za-z])(?:eur|euros?)\b", True),
    ({"rupee", "rupees", "inr"}, r"₹|(?<![A-Za-z])(?:inr|rupees?|rs\.?)\b", True),
    ({"pound", "pounds", "gbp"}, r"£|(?<![A-Za-z])(?:gbp|pounds?)\b", True),
    ({"percent", "percentage"}, r"%|\bpercent(?:age)?\b", False),
    ({"day", "days"}, r"(?<![A-Za-z])days?\b", False),
    ({"week", "weeks"}, r"(?<![A-Za-z])weeks?\b", False),
    ({"month", "months"}, r"(?<![A-Za-z])months?\b", False),
    ({"year", "years"}, r"(?<![A-Za-z])years?\b", False),
    ({"hour", "hours"}, r"(?<![A-Za-z])(?:hours?|hrs?)\b", False),
    ({"minute", "minutes"}, r"(?<![A-Za-z])(?:minutes?|mins?)\b", False),
    ({"second", "seconds"}, r"(?<![A-Za-z])(?:seconds?|secs?)\b", False),
    ({"kilogram", "kilograms", "kg"}, r"(?<![A-Za-z])(?:kg|kilograms?)\b", False),
    ({"gram", "grams"}, r"(?<![A-Za-z])(?:grams?|g)\b", False),
    ({"megabyte", "megabytes", "mb"}, r"(?<![A-Za-z])(?:(?-i:MB)|megabytes?)\b", False),
    ({"gigabyte", "gigabytes", "gb"}, r"(?<![A-Za-z])(?:(?-i:GB)|gigabytes?)\b", False),
)
_NUMBER = re.compile(
    r"\d|\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion)\b",
    re.IGNORECASE,
)
_FREE = re.compile(
    r"\b(?:free|no charge|without charge|at no cost|complimentary)\b", re.IGNORECASE
)

_NEGATED_FREE = re.compile(
    r"\b(?:not(?!\s+only\b)|never|isn't|isn’t|wasn't|wasn’t|no longer|no)\s+(?:\w+\s+){0,3}free\b",
    re.IGNORECASE,
)


def _explicitly_free(text: str) -> bool:
    return bool(_FREE.search(text) and not _NEGATED_FREE.search(text))


def has_requested_quantity_support(
    question: str, citations: Sequence[Citation]
) -> bool:
    text = "\n".join(c.excerpt for c in citations)
    requested = re.search(
        r"\bhow\s+(?:many|much)\s+([a-z]+)\b", question, re.IGNORECASE
    )
    word = requested.group(1).casefold() if requested else None
    if re.search(r"\bwhat\s+percentage\b", question, re.IGNORECASE):
        word = "percentage"
    if word in {"pound", "pounds"} and re.search(
        r"\b(?:weigh|weight|mass)\b", question, re.IGNORECASE
    ):
        return bool(
            _NUMBER.search(text)
            and re.search(r"(?<![A-Za-z])(?:pounds?|lbs?)\b", text, re.IGNORECASE)
        )
    for aliases, unit_pattern, monetary in _UNITS:
        if word in aliases:
            if monetary and _explicitly_free(text):
                return True
            return bool(
                _NUMBER.search(text) and re.search(unit_pattern, text, re.IGNORECASE)
            )
    # Unspecified-currency price questions still require a monetary statement.
    if re.search(
        r"\bhow\s+much\b.*\b(?:cost|price|charge|fee|pay)\b", question, re.IGNORECASE
    ):
        if _explicitly_free(text):
            return True
        money_pattern = "|".join(pattern for _, pattern, monetary in _UNITS if monetary)
        return bool(
            _NUMBER.search(text) and re.search(money_pattern, text, re.IGNORECASE)
        )
    return True
