from __future__ import annotations

"""Deterministic ingestion for canonical sectioned plain-text CV input."""

import re
from typing import Any, Dict, List

from .source_views import build_pasted_text_source_view

STRUCTURED_SECTION_IMPORT_MODE = "structured_section_text"

_HEADER_PATTERN = re.compile(
    r"(?m)^(IDENTITY|CAREER SUMMARY|SKILLS|QUALIFICATIONS|CERTIFICATIONS|TRAINING|ACHIEVEMENTS|LANGUAGES|INTERESTS|REFERENCES|PROJECTS|CAREER HISTORY|ADDITIONAL INFORMATION)\s*$"
)
_SECTION_PATTERN = re.compile(
    r"(?ms)^(IDENTITY|CAREER SUMMARY|SKILLS|QUALIFICATIONS|CERTIFICATIONS|TRAINING|ACHIEVEMENTS|LANGUAGES|INTERESTS|REFERENCES|PROJECTS|CAREER HISTORY|ADDITIONAL INFORMATION)\s*\n(.*?)(?=^(?:IDENTITY|CAREER SUMMARY|SKILLS|QUALIFICATIONS|CERTIFICATIONS|TRAINING|ACHIEVEMENTS|LANGUAGES|INTERESTS|REFERENCES|PROJECTS|CAREER HISTORY|ADDITIONAL INFORMATION)\s*$|\Z)"
)
_LINE_ITEM_PATTERN = re.compile(r"(?m)^(?!\s*$)(.+)$")
_SKILL_LINE_PATTERN = re.compile(r"(?m)^([A-Za-z0-9&/\- ]+):\s*(.+)$")
_QUALIFICATION_PATTERN = re.compile(
    r"(?ms)^Qualification:\s*(.*?)\nInstitution:\s*(.*?)\nYear:\s*(.*?)(?=\nQualification:|\Z)"
)
_CERTIFICATION_PATTERN = re.compile(
    r"(?ms)^Name:\s*(.*?)\nProvider:\s*(.*?)\nYear:\s*(.*?)(?=\nName:|\Z)"
)
_PROJECT_PATTERN = re.compile(r"(?ms)^Project:\s*(.*?)\nDetails:\s*(.*?)(?=\nProject:|\Z)")
_CAREER_HISTORY_PATTERN = re.compile(
    r"(?ms)^Job Title:\s*(.*?)\nCompany:\s*(.*?)\nStart Date:\s*(.*?)\nEnd Date:\s*(.*?)\nResponsibilities:\s*(.*?)(?=\nJob Title:|\Z)"
)

_IDENTITY_FIELD_MAP = {
    "Full Name": "full_name",
    "Professional Headline": "headline",
    "Availability": "availability",
    "Region": "region",
    "Email": "email",
    "Phone": "phone",
    "Location": "location",
    "LinkedIn": "linkedin",
    "Portfolio": "portfolio",
}


def normalize_structured_section_text(raw_text: str) -> str:
    text = (raw_text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def looks_like_structured_section_text(raw_text: str) -> bool:
    normalized = normalize_structured_section_text(raw_text)
    headers = [match.group(1) for match in _HEADER_PATTERN.finditer(normalized)]
    return len(headers) >= 3


def _section_map(raw_text: str) -> Dict[str, str]:
    normalized = normalize_structured_section_text(raw_text)
    return {header: body.strip() for header, body in _SECTION_PATTERN.findall(normalized)}


def _parse_identity(body: str) -> Dict[str, str]:
    parsed = {value: "" for value in _IDENTITY_FIELD_MAP.values()}
    for line in body.splitlines():
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        key = _IDENTITY_FIELD_MAP.get(label.strip())
        if key is None:
            continue
        parsed[key] = value.strip()
    return parsed


def _parse_skills(body: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for category, raw_items in _SKILL_LINE_PATTERN.findall(body):
        items = [item.strip() for item in re.split(r"\s*;\s*", raw_items.strip()) if item.strip()]
        if items:
            rows.append({"category": category.strip(), "items": items})
    return rows


def _parse_qualifications(body: str) -> List[Dict[str, str]]:
    return [
        {"qualification": qualification.strip(), "institution": institution.strip(), "year": year.strip()}
        for qualification, institution, year in _QUALIFICATION_PATTERN.findall(body.strip())
    ]


def _parse_certifications(body: str) -> List[Dict[str, str]]:
    return [
        {"name": name.strip(), "provider": provider.strip(), "year": year.strip()}
        for name, provider, year in _CERTIFICATION_PATTERN.findall(body.strip())
    ]


def _parse_simple_items(body: str, *, none_listed_means_empty: bool = False) -> List[str]:
    items = [line.strip() for line in _LINE_ITEM_PATTERN.findall(body.strip()) if line.strip()]
    if none_listed_means_empty and len(items) == 1 and items[0].casefold() == "none listed":
        return []
    return [item for item in items if item.casefold() != "none listed"]


def _parse_projects(body: str) -> List[Dict[str, str]]:
    return [{"project": project.strip(), "details": details.strip()} for project, details in _PROJECT_PATTERN.findall(body.strip())]


def _parse_career_history(body: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for job_title, company, start_date, end_date, responsibilities in _CAREER_HISTORY_PATTERN.findall(body.strip()):
        role = {
            "job_title": job_title.strip(),
            "company": company.strip(),
            "start_date": start_date.strip(),
            "end_date": end_date.strip(),
            "responsibilities": [item.strip() for item in re.split(r"\s*;\s*", responsibilities.strip()) if item.strip()],
        }
        if role["job_title"] and role["company"]:
            rows.append(role)
    return rows


def parse_structured_section_text(raw_text: str) -> Dict[str, Any]:
    if not looks_like_structured_section_text(raw_text):
        raise ValueError("Structured section text requires at least three recognized headers.")
    sections = _section_map(raw_text)
    identity = _parse_identity(sections.get("IDENTITY", ""))
    return {
        "identity": identity,
        "career_summary": sections.get("CAREER SUMMARY", "").strip(),
        "skills": _parse_skills(sections.get("SKILLS", "")),
        "qualifications": _parse_qualifications(sections.get("QUALIFICATIONS", "")),
        "certifications": _parse_certifications(sections.get("CERTIFICATIONS", "")),
        "training": _parse_simple_items(sections.get("TRAINING", ""), none_listed_means_empty=True),
        "achievements": _parse_simple_items(sections.get("ACHIEVEMENTS", ""), none_listed_means_empty=True),
        "languages": _parse_simple_items(sections.get("LANGUAGES", ""), none_listed_means_empty=True),
        "interests": _parse_simple_items(sections.get("INTERESTS", ""), none_listed_means_empty=True),
        "references": _parse_simple_items(sections.get("REFERENCES", ""), none_listed_means_empty=True),
        "projects": _parse_projects(sections.get("PROJECTS", "")),
        "career_history": _parse_career_history(sections.get("CAREER HISTORY", "")),
        "additional_information": "" if sections.get("ADDITIONAL INFORMATION", "").strip().casefold() == "none listed" else sections.get("ADDITIONAL INFORMATION", "").strip(),
        "raw_text": normalize_structured_section_text(raw_text),
    }


def build_template_state_from_structured_sections(parsed: Dict[str, Any]) -> Dict[str, str]:
    identity = parsed.get("identity") or {}
    qualifications = parsed.get("qualifications") or []
    certifications = parsed.get("certifications") or []
    projects = parsed.get("projects") or []
    history = parsed.get("career_history") or []
    return {
        "full_name": identity.get("full_name", ""),
        "headline": identity.get("headline", ""),
        "availability": identity.get("availability", ""),
        "region": identity.get("region", ""),
        "email": identity.get("email", ""),
        "phone": identity.get("phone", ""),
        "location": identity.get("location", ""),
        "linkedin": identity.get("linkedin", ""),
        "portfolio": identity.get("portfolio", ""),
        "summary": parsed.get("career_summary", ""),
        "career_summary": "\n".join(
            " | ".join(part for part in [row.get("job_title", ""), row.get("company", ""), row.get("start_date", ""), row.get("end_date", "")] if part)
            for row in history
        ),
        "skills": "\n".join(f"{row['category']}: {'; '.join(row['items'])}" for row in parsed.get("skills") or []),
        "education": "\n".join(
            " | ".join(part for part in [row.get("qualification", ""), row.get("institution", ""), row.get("year", "")] if part)
            for row in qualifications
        ),
        "certifications": "\n".join(
            " | ".join(part for part in [row.get("name", ""), row.get("provider", ""), row.get("year", "")] if part)
            for row in certifications
            if row.get("name", "").strip()
        ),
        "training": "\n".join(parsed.get("training") or []),
        "career_history": "\n".join(
            filter(
                None,
                [
                    item
                    for row in history
                    for item in (
                        " | ".join(part for part in [row.get("company", ""), row.get("job_title", ""), row.get("start_date", ""), row.get("end_date", "")] if part),
                        *row.get("responsibilities", []),
                    )
                ],
            )
        ),
        "projects": "\n\n".join(
            "\n".join(filter(None, [f"Project: {row.get('project', '').strip()}", f"Details: {row.get('details', '').strip()}"]))
            for row in projects
            if row.get("project", "").strip() or row.get("details", "").strip()
        ),
        "volunteering": "",
        "publications": "",
        "languages": "\n".join(parsed.get("languages") or []),
        "awards": "\n".join(parsed.get("achievements") or []),
        "interests": "\n".join(parsed.get("interests") or []),
        "references": "\n".join(parsed.get("references") or []),
        "additional_sections": parsed.get("additional_information", ""),
    }


def build_profile_from_structured_sections(parsed: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "identity": dict(parsed.get("identity") or {}),
        "summary": parsed.get("career_summary", ""),
        "career_summary": parsed.get("career_summary", ""),
        "skills": {
            "declared": [f"{row['category']}: {'; '.join(row['items'])}" for row in parsed.get("skills") or []],
            "inferred": {},
            "sa_context": [],
            "source_faithful": True,
        },
        "education": [
            {
                "qualification": row.get("qualification", ""),
                "institution": row.get("institution", ""),
                "end_date": row.get("year", ""),
            }
            for row in parsed.get("qualifications") or []
        ],
        "certifications": [
            " | ".join(part for part in [row.get("name", ""), row.get("provider", ""), row.get("year", "")] if part)
            for row in parsed.get("certifications") or []
            if row.get("name", "").strip()
        ],
        "training": list(parsed.get("training") or []),
        "projects": [
            "\n".join(filter(None, [f"Project: {row.get('project', '').strip()}", f"Details: {row.get('details', '').strip()}"]))
            for row in parsed.get("projects") or []
            if row.get("project", "").strip() or row.get("details", "").strip()
        ],
        "languages": list(parsed.get("languages") or []),
        "awards": list(parsed.get("achievements") or []),
        "interests": list(parsed.get("interests") or []),
        "references": list(parsed.get("references") or []),
        "experience": [
            {
                "position": row.get("job_title", ""),
                "company": row.get("company", ""),
                "start_date": row.get("start_date", ""),
                "end_date": row.get("end_date", ""),
                "responsibilities": list(row.get("responsibilities") or []),
                "projects": [],
                "client_engagements": [],
                "summary": "",
            }
            for row in parsed.get("career_history") or []
        ],
        "additional_sections": (
            [{"title": "Additional Information", "content": parsed.get("additional_information", "")}]
            if parsed.get("additional_information", "")
            else []
        ),
        "raw_sections": [],
        "document_meta": {"layout_flags": {"structured_section_text": True}, "import_mode": STRUCTURED_SECTION_IMPORT_MODE},
    }


def build_structured_section_document_payload(parsed: Dict[str, Any], *, document_id: str, filename: str = "Structured Section CV Text") -> Dict[str, Any]:
    raw_text = parsed.get("raw_text") or ""
    return {
        "document_id": document_id,
        "filename": filename,
        "path": None,
        "raw_text": raw_text,
        "sections": [],
        "text_blocks": [],
        "source_sections": [],
        "source_view": build_pasted_text_source_view(raw_text),
        "annotations": [],
        "profile": build_profile_from_structured_sections(parsed),
        "template_state": build_template_state_from_structured_sections(parsed),
        "detected_blocks": [],
        "review_confirmed": False,
        "structured_source": True,
        "import_mode": STRUCTURED_SECTION_IMPORT_MODE,
    }
