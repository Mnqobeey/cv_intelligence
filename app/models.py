from __future__ import annotations

"""Shared data models used across parsing, storage, and rendering."""

from dataclasses import dataclass
import re
from typing import Any, Dict, List

from .constants import FIELD_DEFINITIONS


@dataclass
class SectionBlock:
    """A detected logical section from the uploaded CV."""

    id: str
    title: str
    canonical_key: str
    content: str
    confidence: float
    source: str
    start_line: int = 0
    end_line: int = 0


@dataclass
class Provenance:
    """Evidence trail for a normalized profile field."""

    text: str
    source_section: str
    confidence: float
    field_key: str


REVIEW_RULES = [
    ("full_name", "Identity", "Complete name found", "Missing information"),
    ("headline", "Professional Headline", "Headline ready", "Needs confirmation"),
    ("summary", "Career Summary", "Career summary ready", "Missing information"),
    ("skills", "Skills", "Skills ready", "Needs confirmation"),
    ("education", "Qualifications", "Qualifications ready", "Needs confirmation"),
    ("certifications", "Certifications", "Certifications ready", "Needs confirmation"),
    ("career_history", "Career History", "Career history ready", "Needs confirmation"),
]


def build_detected_blocks(sections: List[SectionBlock]) -> List[Dict[str, Any]]:
    """Return source sections in the lightweight structure required by the UI."""
    blocks: List[Dict[str, Any]] = []
    for sec in sections:
        if sec.canonical_key == "raw_unknown" and sec.title.strip().lower() == "header":
            header_lines = [ln.strip() for ln in sec.content.splitlines() if ln.strip()]
            if header_lines and all(
                "@" in line
                or "linkedin" in line.lower()
                or re.search(r"\b(?:\+?\d[\d\s]{7,}|0\d{2}\s*\d{3}\s*\d{4})\b", line)
                or len(line.split()) <= 5
                for line in header_lines
            ):
                continue
        mapped_field = {
            "summary": "summary",
            "skills": "skills",
            "education": "education",
            "experience": "career_history",
            "projects": "projects",
            "certifications": "certifications",
            "training": "training",
            "languages": "languages",
            "awards": "awards",
            "volunteering": "volunteering",
            "publications": "publications",
            "references": "references",
            "personal_details": "additional_sections",
        }.get(sec.canonical_key, "additional_sections")
        blocks.append({
            "id": sec.id,
            "title": sec.title,
            "section": sec.canonical_key,
            "mapped_field": mapped_field,
            "content": sec.content,
            "preview": " ".join(sec.content.splitlines()[:2])[:180],
            "status": "needs_review" if sec.confidence < 0.72 else "ready",
        })
    return blocks


def empty_template_state() -> Dict[str, str]:
    """Return an empty builder state for all supported fields."""
    return {field["key"]: "" for field in FIELD_DEFINITIONS}
