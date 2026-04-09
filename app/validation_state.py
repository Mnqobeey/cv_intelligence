from __future__ import annotations

"""Split validation feedback into blocking issues and non-blocking warnings."""

from typing import Iterable, List, Tuple

_WARNING_PREFIXES = (
    "Qualifications are required before build can pass.",
    "Portfolio / Website must contain a valid web link.",
)
_WARNING_CONTAINS = (
    "Qualifications contain malformed rows",
    "Region should be reduced",
    "References appear contaminated",
    "Some fields still contain empty placeholders.",
)


def split_validation_issues(issues: Iterable[str]) -> Tuple[List[str], List[str]]:
    blocking: List[str] = []
    warnings: List[str] = []
    for issue in issues:
        if any(issue.startswith(prefix) for prefix in _WARNING_PREFIXES) or any(token in issue for token in _WARNING_CONTAINS):
            warnings.append(issue)
        else:
            blocking.append(issue)
    return blocking, warnings
