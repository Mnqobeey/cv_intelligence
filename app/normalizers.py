from __future__ import annotations

"""Profile normalization and builder state orchestration."""

import re
from dataclasses import asdict
from pathlib import Path
from .validation_state import split_validation_issues
from typing import Any, Dict, List, Optional, Tuple

from .constants import EMAIL_RE, FIELD_MAP, KNOWN_HEADING_TERMS, LINKEDIN_RE, PHONE_RE, TEMPLATE_COPY, URL_RE
from .models import empty_template_state
from .parsers import (
    build_text_blocks,
    clean_experience_entries,
    extract_identity,
    format_recruiter_date,
    infer_headline_from_profile,
    infer_headline_from_raw,
    infer_layout_flags,
    infer_name_from_filename,
    infer_skills_from_text,
    infer_summary_fallback,
    is_identity_headline_value_valid,
    is_valid_name_candidate,
    normalize_recruiter_date_text,
    parse_education_section,
    parse_experience_section,
    parse_reference_section,
    parse_simple_items,
    sanitize_entity_text,
    summarize_unknown_section,
)
from .utils_text import normalize_heading

GEORGE_REQUIRED_KEYS = ["full_name", "headline", "summary", "skills", "career_history"]
SKILL_BUCKET_LABELS = {
    "languages_programming": "Programming Languages",
    "frameworks": "Frameworks",
    "tools_platforms": "Tools",
    "cloud_devops": "Cloud / DevOps",
    "testing_qa": "Testing",
    "data_bi": "Data & Analytics",
    "databases": "Databases",
    "methodologies": "Methodologies",
}
TRAINING_HINTS = ("udemy", "coursera", "workshop", "course", "training", "alton", "torque")
EDUCATION_RECORD_HINTS = (
    "module", "subject", "coursework", "semester", "assessment", "assignment",
    "practical", "exam", "curriculum", "degree", "diploma", "honours",
    "honors", "bachelor", "masters", "doctorate", "nqf", "programme",
    "program", "course", "qualification",
)
EMPLOYMENT_ROLE_HINTS = (
    "student assistant", "lab demonstrator", "demonstrator", "tutor", "peer mentor",
    "research assistant", "researcher", "intern", "coordinator", "officer",
    "administrator", "developer", "analyst", "engineer", "consultant", "manager",
    "lecturer", "facilitator", "technician", "conference", "supervisor", "lead",
)
ROLE_TITLE_TERMS = ("analyst", "developer", "engineer", "tester", "manager", "consultant", "intern", "coordinator", "lead", "specialist", "officer", "administrator", "technician", "architect", "qa")
GENERIC_HEADLINE_PHRASES = {"software testing", "testing", "quality assurance", "data analytics", "computer literacy"}
PERSONAL_DETAIL_TERMS = {"date of birth", "marital status", "nationality", "gender", "race", "criminal offense", "criminal offence", "personal details"}
AWARD_TERMS = ("award", "distinction", "achiever", "dean's list", "top ten", "best performance")
SCHOOL_QUALIFICATION_TERMS = ("national senior certificate", "matric", "grade 12", "nqf 4 national senior certificate")
EDUCATION_INSTITUTION_RE = re.compile(r"\b(?:university|college|institute|school|academy|campus|high school|secondary school)\b", re.I)
ADDRESS_HINT_RE = re.compile(
    r"\b(?:street|st\b|road|rd\b|avenue|ave\b|drive|dr\b|lane|close|crescent|court|park|"
    r"midrand|johannesburg|pretoria|sandton|randburg|centurion|cape town|durban|"
    r"gauteng|limpopo|mpumalanga|north west|western cape|eastern cape|free state|"
    r"kwazulu[- ]natal|south africa)\b",
    re.I,
)


def _strip_leading_bullets(text: str) -> str:
    cleaned = sanitize_entity_text(text) or ""
    return (re.sub(r"^(?:[\u2022\u00b7\-\*\u25cf\?]+\s*)+", "", cleaned)).strip()


def _summary_needs_rescue(text: str) -> bool:
    cleaned = sanitize_entity_text(text) or ""
    lowered = cleaned.lower()
    if not cleaned:
        return True
    if lowered in {"personal details", "objective", "objectives", "skills", "education", "experience", "summary", "profile"}:
        return True
    if lowered in PERSONAL_DETAIL_TERMS:
        return True
    if EMAIL_RE.search(cleaned) or PHONE_RE.search(cleaned):
        return True
    return len(cleaned.split()) < 12


def _headline_needs_role_promotion(text: str) -> bool:
    cleaned = sanitize_entity_text(text) or ""
    lowered = cleaned.lower().replace("co-ordinator", "coordinator")
    if not cleaned:
        return True
    if lowered in GENERIC_HEADLINE_PHRASES:
        return True
    return not any(term in lowered for term in ROLE_TITLE_TERMS)


def _looks_like_address_line(text: str) -> bool:
    cleaned = sanitize_entity_text(text) or ""
    if not cleaned:
        return False
    if EMAIL_RE.search(cleaned) or PHONE_RE.search(cleaned) or LINKEDIN_RE.search(cleaned):
        return True
    if re.search(r"^(?:https?://|www\.|[A-Za-z]{2,3}\.linkedin\.com/|linkedin\.com/)", cleaned, re.I):
        return True
    return bool(ADDRESS_HINT_RE.search(cleaned) and len(cleaned.split()) <= 14)


def _looks_like_language_proficiency_line(text: str) -> bool:
    cleaned = sanitize_entity_text(text) or ""
    return bool(re.match(r"^(?:read|write|speak|spoken|written)\s*[-:]\s*.+$", cleaned, re.I))


def _looks_like_award_line(text: str) -> bool:
    lowered = (sanitize_entity_text(text) or "").lower()
    if not lowered:
        return False
    if not any(term in lowered for term in AWARD_TERMS):
        return False
    # Reject long prose / summary sentences that happen to contain award
    # keywords like "award-winning track record" – these are descriptions,
    # not actual award entries.
    if len(lowered.split()) > 25:
        return False
    if re.search(r"\b(?:award-winning|award winning)\b", lowered):
        return False
    if re.search(r"\b(?:track record|experienced in|expertise in|skilled in|i am)\b", lowered):
        return False
    return True


def _looks_like_qualification_text(text: str) -> bool:
    lowered = (sanitize_entity_text(text) or "").lower()
    if not lowered:
        return False
    if ":" in lowered or any(term in lowered for term in ("hod", "prof ", "lecturer", "reference")):
        return False
    if any(term in lowered for term in ROLE_TITLE_TERMS):
        return False
    return any(
        term in lowered
        for term in (
            "certificate",
            "degree",
            "diploma",
            "honours",
            "honors",
            "bsc",
            "bcom",
            "bachelor",
            "master",
            "matric",
            "grade 12",
        )
    )


def _merge_education_rows(existing: List[Dict[str, Any]], incoming: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    by_key: Dict[tuple[str, str], Dict[str, Any]] = {}
    for row in list(existing) + list(incoming):
        qualification = (sanitize_entity_text(row.get("qualification")) or "").strip(" ,|-")
        institution = (sanitize_entity_text(row.get("institution")) or "").strip(" ,|-")
        if not qualification:
            continue
        key = (qualification.casefold(), institution.casefold())
        current = by_key.get(key)
        normalized = {
            "qualification": qualification,
            "institution": institution,
            "start_date": format_recruiter_date(row.get("start_date")),
            "end_date": normalize_recruiter_date_text(row.get("end_date")),
            "sa_standard_hint": row.get("sa_standard_hint"),
        }
        if current is None:
            by_key[key] = normalized
            continue
        for field in ("start_date", "end_date", "sa_standard_hint"):
            if not current.get(field) and normalized.get(field):
                current[field] = normalized[field]
    merged.extend(by_key.values())
    return merged


def _rescue_education_rows_from_text(raw_text: str) -> List[Dict[str, Any]]:
    lines = [sanitize_entity_text(line) or "" for line in raw_text.splitlines() if sanitize_entity_text(line)]
    rows: List[Dict[str, Any]] = []
    for idx, line in enumerate(lines[:-1]):
        next_line = sanitize_entity_text(lines[idx + 1]) or ""
        if not next_line:
            continue
        if EDUCATION_INSTITUTION_RE.search(line) and _looks_like_qualification_text(next_line):
            rows.append({
                "qualification": next_line,
                "institution": line,
                "start_date": "",
                "end_date": "",
                "sa_standard_hint": None,
            })
        elif _looks_like_qualification_text(line) and EDUCATION_INSTITUTION_RE.search(next_line):
            rows.append({
                "qualification": line,
                "institution": next_line,
                "start_date": "",
                "end_date": "",
                "sa_standard_hint": None,
            })
    return rows


_KNOWN_LANGUAGE_NAMES = {
    "english", "afrikaans", "zulu", "xhosa", "sepedi", "sotho", "tswana",
    "swati", "tshivenda", "tsonga", "isizulu", "isixhosa", "setswana",
    "sesotho", "siswati", "xitsonga", "isindebele", "french", "portuguese",
    "german", "mandarin", "spanish", "italian", "arabic", "hindi", "ndebele",
    "itsonga", "venda",
}


def _extract_languages_from_text(raw_text: str) -> List[str]:
    languages: List[str] = []
    # Strategy 1: "Read/Write/Speak: ..." patterns
    for raw_line in raw_text.splitlines():
        cleaned = sanitize_entity_text(raw_line) or ""
        match = re.match(r"^(?:read|write|speak|spoken|written)\s*[-:]\s*(.+)$", cleaned, re.I)
        if not match:
            continue
        for token in re.split(r"\s*,\s*|\s*/\s*|\s+and\s+", match.group(1)):
            language = sanitize_entity_text(token) or ""
            language = re.sub(r"^[^A-Za-z]+|[^A-Za-z]+$", "", language)
            if language:
                languages.append(language)
    # Strategy 2: standalone language names under a "Languages" heading
    lines = [sanitize_entity_text(line) or "" for line in raw_text.splitlines() if sanitize_entity_text(line)]
    capture = False
    _lang_stop = {"skills", "education", "experience", "references", "awards",
                  "achievements", "certifications", "certificates", "training",
                  "interests", "projects", "volunteering", "publications",
                  "career history", "work experience", "employment"}
    for line in lines:
        norm = normalize_heading(line)
        if norm in {"languages", "language proficiency", "language skills"}:
            capture = True
            continue
        if capture:
            if norm in _lang_stop or norm in KNOWN_HEADING_TERMS:
                break
            cleaned = sanitize_entity_text(line) or ""
            # Accept standalone known language names or short language entries
            lowered = cleaned.lower().strip()
            if lowered in _KNOWN_LANGUAGE_NAMES:
                languages.append(cleaned)
            elif len(cleaned.split()) <= 4 and any(lang in lowered for lang in _KNOWN_LANGUAGE_NAMES):
                languages.append(cleaned)
    return _dedupe_text_rows(languages)


def _normalize_language_values(values: List[str]) -> List[str]:
    languages: List[str] = []
    for value in values:
        cleaned = (sanitize_entity_text(value) or "").replace("ā??", "’").replace("â€™", "’").replace("â€˜", "‘")
        if not cleaned:
            continue
        cleaned = re.sub(r"^(?:read|write|speak|spoken|written)\s*[-:]\s*", "", cleaned, flags=re.I)
        for token in re.split(r"\s*,\s*|\s*/\s*|\s+and\s+", cleaned):
            language = sanitize_entity_text(token) or ""
            language = re.sub(r"^[^A-Za-z]+|[^A-Za-z]+$", "", language)
            if language:
                languages.append(language)
    return _dedupe_text_rows(languages)


def _extract_awards_from_text(raw_text: str) -> List[str]:
    lines = [sanitize_entity_text(line) or "" for line in raw_text.splitlines() if sanitize_entity_text(line)]
    return _dedupe_text_rows([
        line for line in lines
        if _looks_like_award_line(line) and normalize_heading(line) not in {"achievements", "achievements awards", "achievements & awards", "awards"}
    ])


def _prune_education_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        qualification = sanitize_entity_text(row.get("qualification")) or ""
        if not qualification:
            continue
        grouped.setdefault(qualification.casefold(), []).append(row)

    pruned: List[Dict[str, Any]] = []
    for _, candidates in grouped.items():
        candidates = sorted(
            candidates,
            key=lambda row: (
                1 if sanitize_entity_text(row.get("institution")) else 0,
                0 if re.search(r"\b(?:prof|hod|lecturer|reference)\b", sanitize_entity_text(row.get("institution")) or "", re.I) else 1,
                1 if EDUCATION_INSTITUTION_RE.search(sanitize_entity_text(row.get("institution")) or "") else 0,
            ),
            reverse=True,
        )
        best = None
        for candidate in candidates:
            institution = sanitize_entity_text(candidate.get("institution")) or ""
            qualification = sanitize_entity_text(candidate.get("qualification")) or ""
            lowered_qualification = qualification.lower()
            lowered_institution = institution.lower()
            if any(term in lowered_qualification for term in SCHOOL_QUALIFICATION_TERMS):
                if institution and not re.search(r"\b(?:school|academy|high school|secondary school)\b", lowered_institution, re.I):
                    continue
            elif institution and re.search(r"\b(?:prof|hod|lecturer|reference)\b", lowered_institution, re.I):
                continue
            best = candidate
            break
        if best is None:
            best = candidates[0]
        pruned.append(best)
    return pruned


def _clean_reference_rows(values: List[str], raw_text: str) -> List[str]:
    cleaned_rows: List[str] = []
    for value in values:
        cleaned = sanitize_entity_text(value) or ""
        lowered = cleaned.lower()
        if not cleaned:
            continue
        if _looks_like_award_line(cleaned) or "distinction" in lowered:
            continue
        if re.search(r"available on request", lowered, re.I):
            cleaned_rows.append("Available on request")
            continue
        if EMAIL_RE.search(cleaned) or PHONE_RE.search(cleaned) or "|" in cleaned or is_valid_name_candidate(cleaned):
            cleaned_rows.append(cleaned)
    if cleaned_rows:
        return _dedupe_text_rows(cleaned_rows)
    if re.search(r"\breference[s]?\b", raw_text, re.I):
        return ["Available on request"]
    return []


def _clean_certifications(certifications: List[str], education: List[Dict[str, Any]]) -> tuple[List[str], List[Dict[str, Any]]]:
    rescued_rows: List[Dict[str, Any]] = []
    filtered: List[str] = []
    for cert in certifications:
        cleaned = _strip_leading_bullets(cert)
        # Strip "Certificate : " or "Certificate:" label prefix
        cleaned = re.sub(r"^Certificate\s*:\s*", "", cleaned, flags=re.I).strip()
        lowered = cleaned.lower()
        if not cleaned:
            continue
        if any(term in lowered for term in SCHOOL_QUALIFICATION_TERMS):
            rescued_rows.append({
                "qualification": cleaned,
                "institution": "",
                "start_date": "",
                "end_date": "",
                "sa_standard_hint": None,
            })
            continue
        filtered.append(cleaned)
    return _dedupe_text_rows(filtered), _merge_education_rows(education, rescued_rows)


def _skill_line_is_leakage(line: str, profile: Dict[str, Any]) -> bool:
    cleaned = sanitize_entity_text(line) or ""
    lowered = cleaned.lower()
    if not cleaned:
        return True
    if cleaned.startswith(":") or _looks_like_address_line(cleaned):
        return True
    if normalize_recruiter_date_text(cleaned) == cleaned and re.search(r"\b(?:19|20)\d{2}\b", cleaned):
        return True
    if re.fullmatch(r"(?:19|20)\d{2}\s*(?:[-–—]|â€“|â€”)\s*(?:Present|Current|Now|(?:19|20)\d{2})", cleaned, re.I):
        return True
    if normalize_heading(cleaned) in PERSONAL_DETAIL_TERMS or normalize_heading(cleaned) in {"objective", "education", "qualifications", "qualification", "languages", "skills", "experience", "employment history", "career history", "achievements", "achievements awards", "achievements & awards", "reference", "references"}:
        return True
    if cleaned.lower() in {"present", "current", "now"}:
        return True
    if _looks_like_language_proficiency_line(cleaned) or _looks_like_award_line(cleaned):
        return True
    if any(term in lowered for term in PERSONAL_DETAIL_TERMS):
        return True
    # Reject biographical/personal metadata lines that leak into skills
    if re.fullmatch(r"(?:male|female|married|single|divorced|widowed|code\s*\d+)", cleaned, re.I):
        return True
    # Reject standalone dates of birth (e.g. "19 December 1988")
    if re.search(r"\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b", cleaned, re.I):
        return True
    # Reject pure postal codes or short address fragments
    if re.fullmatch(r"\d{4,5}", cleaned.strip()):
        return True
    # Reject qualification/education rows that look like degree names
    if _looks_like_qualification_text(cleaned):
        return True
    # Reject certificate entries leaking into skills
    if re.search(r"\b(?:azure data fundamentals|functional testing from)\b", lowered):
        return True
    if lowered.startswith(("designed ", "developed ", "logged ", "supported ", "assisted ", "worked ", "investigated ", "monitored ", "troubleshot ", "performed ", "strengthened ", "tutored ")):
        return True
    if cleaned.count("|") >= 2 and re.search(r"\b(?:19|20)\d{2}|present|current|now\b", cleaned, re.I):
        return True

    blocked = {
        (sanitize_entity_text((profile.get("identity") or {}).get("email")) or "").casefold(),
        (sanitize_entity_text((profile.get("identity") or {}).get("phone")) or "").casefold(),
        (sanitize_entity_text((profile.get("identity") or {}).get("linkedin")) or "").casefold(),
        (sanitize_entity_text((profile.get("identity") or {}).get("location")) or "").casefold(),
    }
    blocked.update((sanitize_entity_text(item.get("qualification")) or "").casefold() for item in profile.get("education", []) or [])
    blocked.update((sanitize_entity_text(item.get("institution")) or "").casefold() for item in profile.get("education", []) or [])
    blocked.update((sanitize_entity_text(item.get("company")) or "").casefold() for item in profile.get("experience", []) or [])
    blocked.update((sanitize_entity_text(item.get("position")) or "").casefold() for item in profile.get("experience", []) or [])
    for entry in profile.get("experience", []) or []:
        blocked.update((sanitize_entity_text(item) or "").casefold() for item in entry.get("responsibilities", []) or [])
    if cleaned.casefold() in blocked:
        return True
    return False


def _clean_declared_skills(profile: Dict[str, Any]) -> List[str]:
    raw_lines = list((profile.get("skills") or {}).get("declared") or [])
    normalized_lines = [
        sanitize_entity_text(re.sub(r"^Skills\s*:\s*", "", raw_line, flags=re.I)) or ""
        for raw_line in raw_lines
    ]
    standalone_items = {
        line.casefold()
        for line in normalized_lines
        if line and "," not in line
    }
    cleaned_lines: List[str] = []
    for raw_line in raw_lines:
        cleaned = sanitize_entity_text(re.sub(r"^Skills\s*:\s*", "", raw_line, flags=re.I)) or ""
        if cleaned in {"Soft", "Skills"}:
            continue
        if "," in cleaned or ";" in cleaned:
            parts = [
                sanitize_entity_text(part) or ""
                for part in re.split(r"\s*[;,]\s*", cleaned)
                if sanitize_entity_text(part)
            ]
            if len(parts) >= 3 and all(part.casefold() in standalone_items for part in parts):
                continue
        if len(cleaned.split()) > 12:
            continue
        # Reject prose sentences ending with '.', but keep structured skill
        # category lines like "API TESTING: Postman, Rest Assured & Blaze Meter."
        if cleaned.endswith(".") and ":" not in cleaned and "," not in cleaned and "&" not in cleaned:
            continue
        if _skill_line_is_leakage(cleaned, profile):
            continue
        cleaned_lines.append(cleaned)
    return _dedupe_text_rows(cleaned_lines)


def _augment_skill_lines_from_text(profile: Dict[str, Any], raw_text: str) -> List[str]:
    extras: List[str] = []
    capture = False
    stop_headings = {
        "projects",
        "project",
        "certifications",
        "certification",
        "courses",
        "training",
        "references",
        "reference",
        "awards",
        "achievements",
        "achievements awards",
        "achievements & awards",
        "education",
        "qualifications",
        "qualification",
        "career history",
        "experience",
        "professional experience",
        "work experience",
        "employment",
        "employment history",
        "previous experience",
    }
    for raw_line in raw_text.splitlines():
        cleaned = sanitize_entity_text(raw_line) or ""
        if not cleaned:
            continue
        normalized = normalize_heading(cleaned)
        if re.match(r"^Skills\s*:", cleaned, re.I):
            capture = True
            cleaned = sanitize_entity_text(re.sub(r"^Skills\s*:\s*", "", cleaned, flags=re.I)) or ""
            normalized = normalize_heading(cleaned)
        elif normalized in {"skills", "core skills", "technical skills"}:
            capture = True
            continue
        elif capture and normalized in stop_headings:
            if not extras and normalized in {"experience", "professional experience", "work experience", "career history"}:
                continue
            break

        if not capture or not cleaned or _skill_line_is_leakage(cleaned, profile):
            continue
        if len(cleaned.split()) > 12 or cleaned.endswith("."):
            continue
        extras.append(cleaned)
    return _dedupe_text_rows(list((profile.get("skills") or {}).get("declared") or []) + extras)


def _skills_should_render_source_faithfully(lines: List[str]) -> bool:
    normalized = [sanitize_entity_text(line) or "" for line in lines if sanitize_entity_text(line)]
    if len(normalized) >= 8:
        return True
    if any(re.search(r"[#./+]", line) for line in normalized):
        return True
    soft_skill_hits = sum(
        1
        for line in normalized
        if re.search(r"\b(?:critical|problem|adapt|self[- ]?learning|willingness|learn)\b", line, re.I)
    )
    if len(normalized) >= 4 and soft_skill_hits >= 3:
        return True
    if any("," in line for line in normalized):
        return True
    if any(len(line.split()) > 4 for line in normalized):
        return True
    if any("&" in line or ":" in line for line in normalized):
        return True
    return False


def _identity_window_lines(raw_text: str) -> List[str]:
    lines = [sanitize_entity_text(line) or "" for line in raw_text.splitlines() if sanitize_entity_text(line)]
    window: List[str] = []
    for line in lines[:40]:
        if re.search(r"\breference[s]?\b", line, re.I):
            break
        window.append(line)
    return window


def _extract_best_phone(raw_text: str) -> str:
    search_text = "\n".join(_identity_window_lines(raw_text))
    for match in PHONE_RE.finditer(search_text):
        candidate = re.sub(r"\s+", " ", match.group(0)).strip()
        digits = re.sub(r"\D", "", candidate)
        if len(digits) < 10:
            continue
        if re.fullmatch(r"(?:19|20)\d{2}(?:\s*(?:19|20)\d{2})*", digits):
            continue
        if "+" in candidate or candidate.startswith("0"):
            return candidate
    return ""


def _synthesize_summary_from_profile(profile: Dict[str, Any]) -> str:
    headline = sanitize_entity_text((profile.get("identity") or {}).get("headline")) or "Technology professional"
    experience = (profile.get("experience") or [None])[0] or {}
    qualification = (profile.get("education") or [None])[0] or {}

    skill_items: List[str] = []
    for line in list((profile.get("skills") or {}).get("declared") or []):
        for item in re.split(r"\s*,\s*", line):
            candidate = sanitize_entity_text(item) or ""
            if not candidate or _skill_line_is_leakage(candidate, profile):
                continue
            skill_items.append(candidate)
            if len(skill_items) >= 5:
                break
        if len(skill_items) >= 5:
            break
    skill_items = _dedupe_text_rows(skill_items)

    sentences: List[str] = []
    if experience.get("company"):
        sentences.append(f"{headline} with hands-on experience at {sanitize_entity_text(experience.get('company'))} supporting software quality and delivery.")
    else:
        sentences.append(f"{headline} with a practical foundation in software delivery and quality-focused work.")
    if skill_items:
        sentences.append(f"Skilled in {', '.join(skill_items[:5])}.")
    if qualification.get("qualification"):
        institution = sanitize_entity_text(qualification.get("institution")) or ""
        qualification_text = sanitize_entity_text(qualification.get("qualification")) or ""
        suffix = f" from {institution}" if institution else ""
        sentences.append(f"Holds {qualification_text}{suffix}.")
    return " ".join(sentences).strip()


def _friendly_placeholder(field_key: str) -> str:
    return {
        "availability": "Availability not provided",
        "region": "Region not provided",
        "location": "Location not provided",
        "linkedin": "LinkedIn not provided",
        "portfolio": "Portfolio not provided",
        "certifications": "No certifications listed",
        "training": "No training or courses listed",
        "projects": "No projects listed",
        "volunteering": "Not provided",
        "publications": "No publications listed",
        "languages": "Not provided",
        "awards": "Not provided",
        "interests": "Not provided",
        "references": "Available on request",
    }.get(field_key, "Not provided")


def _is_user_friendly_placeholder(text: str) -> bool:
    lowered = (sanitize_entity_text(text) or "").lower()
    return lowered in {
        "availability not provided",
        "region not provided",
        "location not provided",
        "linkedin not provided",
        "portfolio not provided",
        "no certifications listed",
        "no training or courses listed",
        "no projects listed",
        "no publications listed",
        "not provided",
        "available on request",
    }


def _paragraphize_source_summary(text: str) -> str:
    paragraphs = [re.sub(r"\s+", " ", sanitize_entity_text(part) or "").strip() for part in re.split(r"\n\s*\n+", text or "")]
    return "\n\n".join([paragraph for paragraph in paragraphs if paragraph])


def _dedupe_text_rows(values: List[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values:
        cleaned = sanitize_entity_text(value) or ""
        cleaned = re.sub(r"^[•·▪●*\-]+\s*", "", cleaned).strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _dedupe_skills(values: List[str]) -> List[str]:
    return _dedupe_text_rows(values)


def _display_skill_item(value: str) -> str:
    cleaned = sanitize_entity_text(value) or ""
    if not cleaned:
        return ""
    special = {
        "api testing": "API Testing",
        "jira": "Jira",
        "java": "Java",
        "python": "Python",
        "sql": "SQL",
        "microsoft office": "Microsoft Office",
        "power bi": "Power BI",
        "html": "HTML",
        "css": "CSS",
        "xml": "XML",
        "c#": "C#",
        "c++": "C++",
        "agile": "Agile",
        "scrum": "Scrum",
        "ci/cd": "CI/CD",
        "stlc": "STLC",
        "sdlc": "SDLC",
    }
    return special.get(cleaned.lower(), cleaned)


def _date_sort_value(text: str) -> tuple[int, int]:
    cleaned = normalize_recruiter_date_text(text)
    if not cleaned:
        return (0, 0)
    if re.search(r"\bPresent\b", cleaned, re.I):
        return (9999, 12)
    year_match = re.search(r"\b((?:19|20)\d{2})\b", cleaned)
    year = int(year_match.group(1)) if year_match else 0
    month = 0
    for idx, token in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1):
        if re.search(rf"\b{token}\b", cleaned, re.I):
            month = idx
            break
    return (year, month)


def _text_row_year_sort_key(text: str) -> tuple[int, int, str]:
    cleaned = sanitize_entity_text(text) or ""
    return (_date_sort_value(cleaned), len(cleaned), cleaned.casefold())


def _experience_sort_key(entry: Dict[str, Any]) -> tuple[tuple[int, int], tuple[int, int], str, str]:
    return (
        _date_sort_value(str(entry.get("end_date") or "")),
        _date_sort_value(str(entry.get("start_date") or "")),
        (sanitize_entity_text(entry.get("company")) or "").casefold(),
        (sanitize_entity_text(entry.get("position")) or "").casefold(),
    )


def _education_sort_key(entry: Dict[str, Any]) -> tuple[tuple[int, int], str, str]:
    return (
        _date_sort_value(str(entry.get("end_date") or "")),
        (sanitize_entity_text(entry.get("qualification")) or "").casefold(),
        (sanitize_entity_text(entry.get("institution")) or "").casefold(),
    )


def _serialize_education_row(row: Dict[str, Any]) -> str:
    qualification = sanitize_entity_text(row.get("qualification")) or ""
    institution = sanitize_entity_text(row.get("institution")) or ""
    start_date = format_recruiter_date(row.get("start_date"))
    end_date = normalize_recruiter_date_text(row.get("end_date"))
    if not qualification:
        return ""
    parts = [qualification]
    if institution:
        parts.append(institution)
    if start_date and end_date and start_date != end_date:
        parts.extend([start_date, end_date])
    elif end_date:
        parts.append(end_date)
    elif start_date:
        parts.append(start_date)
    return " | ".join(parts)


def _group_certification_lines(lines: List[str]) -> List[str]:
    label_map = {
        "name": "name",
        "certificate": "name",
        "certification": "name",
        "title": "name",
        "course": "name",
        "issuer": "provider",
        "provider": "provider",
        "organisation": "provider",
        "organization": "provider",
        "institution": "provider",
        "authority": "provider",
        "awarded by": "provider",
        "issued by": "provider",
        "date": "year",
        "issue date": "year",
        "issued": "year",
        "year": "year",
        "completed": "year",
    }

    grouped: List[str] = []
    current = ""
    current_open_hyphen = False

    structured_rows: List[str] = []
    current_row = {"name": "", "provider": "", "year": ""}

    def flush_structured() -> None:
        nonlocal current_row
        if current_row["name"]:
            parts = [current_row["name"], current_row["provider"], current_row["year"]]
            structured_rows.append(" | ".join(part for part in parts if part))
        current_row = {"name": "", "provider": "", "year": ""}

    for raw in lines:
        cleaned = sanitize_entity_text(raw) or ""
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if (
            lowered.startswith(("certificate no", "id no", "registrar", "vice-chancellor", "scan code"))
            or "this is to certify" in lowered
            or "requirements having been met" in lowered
            or "associated rights and privileges" in lowered
            or "conferred upon" in lowered
            or "genuine paper" in lowered
        ):
            continue

        label = value = ""
        if "|" in cleaned:
            parts = [sanitize_entity_text(piece) or "" for piece in cleaned.split("|")]
            parts = [piece for piece in parts if piece]
            if len(parts) >= 3:
                structured_rows.append(" | ".join(parts[:3]))
                continue
            if len(parts) == 2:
                label = normalize_heading(parts[0].rstrip(":"))
                value = parts[1]
        if not label:
            match = re.match(r"^([A-Za-z][A-Za-z /&+()-]{1,40}?)\s*:\s*(.+)$", cleaned)
            if match:
                label = normalize_heading(match.group(1))
                value = sanitize_entity_text(match.group(2)) or ""
        bucket = label_map.get(label)
        if bucket:
            if bucket == "name" and current_row["name"]:
                flush_structured()
            current_row[bucket] = value
            continue
        if current_row["name"] and any(current_row.values()):
            flush_structured()

        is_continuation = bool(current) and (
            current_open_hyphen
            or cleaned.startswith("(")
            or lowered.startswith(("associate", "professional", "foundation", "fundamentals", "coach", "analyst"))
            or lowered == "certificate"
        )
        if not current:
            current = cleaned
            current_open_hyphen = raw.strip().endswith("-")
            continue
        if is_continuation:
            current = f"{current.rstrip()}{' - ' if current_open_hyphen else ' '}{cleaned}".strip()
            current_open_hyphen = raw.strip().endswith("-")
            continue
        grouped.append(current)
        current = cleaned
        current_open_hyphen = raw.strip().endswith("-")
    if current_row["name"] and any(current_row.values()):
        flush_structured()
    if current:
        grouped.append(current)
    return _dedupe_text_rows(structured_rows + grouped)


def _extract_grounded_skill_items(section_content: str) -> List[str]:
    text = re.sub(r"\s+", " ", section_content or "").strip()
    if not text:
        return []
    lines = [sanitize_entity_text(line) or "" for line in section_content.splitlines() if sanitize_entity_text(line)]
    if not lines or len(lines) > 4 or any(len(line.split()) <= 6 for line in lines):
        return []
    patterns = [
        (r"\bcritical thinking\b", "Critical thinking"),
        (r"\bproblem[- ]solving\b", "Problem-solving"),
        (r"\badapt(?:able|ability)\b", "Adaptability"),
        (r"\b(?:teaching myself|teach myself|adept at teaching myself|self[- ]learning|self[- ]taught)\b", "Self-learning"),
        (r"\b(?:willingness to learn|enthusiasm to learn|enthusiasm to learn new skills|learn new skills)\b", "Willingness to learn"),
    ]
    items = [label for pattern, label in patterns if re.search(pattern, text, re.I)]
    return _dedupe_text_rows(items) if len(items) >= 2 else []


def _extract_source_faithful_skill_items(section_content: str) -> tuple[List[str], bool]:
    lines = [sanitize_entity_text(line) or "" for line in section_content.splitlines() if sanitize_entity_text(line)]
    lines = _dedupe_text_rows(lines)
    if not lines:
        return [], False
    grounded_items = _extract_grounded_skill_items(section_content)
    if grounded_items:
        return grounded_items, True
    compact_lines = [line for line in lines if len(line.split()) <= 10]
    if len(lines) >= 10 and len(compact_lines) >= max(8, int(len(lines) * 0.75)):
        return lines, True
    if len(lines) == 1:
        parts = [sanitize_entity_text(part) or "" for part in re.split(r"\s*,\s*", lines[0]) if sanitize_entity_text(part)]
        if len(parts) >= 4 and all(len(part.split()) <= 4 for part in parts):
            return _dedupe_text_rows(parts), False
    items = parse_simple_items(section_content)
    return (_dedupe_text_rows(items or lines), False)


def _bucket_skills_for_state(declared: List[str], inferred: Dict[str, List[str]]) -> str:
    rows: List[str] = []
    consumed = set()
    declared = _dedupe_skills(declared)
    for bucket, label in SKILL_BUCKET_LABELS.items():
        values = _dedupe_skills(list(inferred.get(bucket) or []))
        if not values:
            continue
        pretty_values = [_display_skill_item(value) for value in values if _display_skill_item(value)]
        rows.append(f"{label}: {', '.join(pretty_values)}")
        consumed.update(value.casefold() for value in values)
    leftovers = [item for item in declared if item.casefold() not in consumed]
    if leftovers:
        rows.insert(0, f"Core Skills: {', '.join(leftovers)}")
    return "\n".join(rows)


def _contains_reference_marker(text: str) -> bool:
    cleaned = sanitize_entity_text(text) or ""
    lowered = cleaned.lower()
    if not cleaned:
        return False
    if "available on request" in lowered:
        return True
    if re.search(r"\b(?:reference|references|referee|referees)\b", lowered):
        return True
    if (EMAIL_RE.search(cleaned) or PHONE_RE.search(cleaned)) and re.search(r"\b(?:supervisor|lecturer|professor|referee)\b", lowered):
        return True
    return False


def _normalize_region_text(text: str) -> str:
    cleaned = sanitize_entity_text(text) or ""
    if not cleaned:
        return ""
    # Reject education institution text used as region/location
    if re.search(r"\b(?:university|college|institute|school|academy|unisa|wits|uj|tut|dut|uct)\b", cleaned, re.I):
        # Strip the institution prefix if it precedes a city/province
        parts = [part.strip() for part in cleaned.split(",") if part.strip()]
        non_institution = [
            part for part in parts
            if not re.search(r"\b(?:university|college|institute|school|academy|unisa|wits|uj|tut|dut|uct)\b", part, re.I)
        ]
        if non_institution:
            cleaned = ", ".join(non_institution)
        else:
            return ""
    if re.search(r"\b\d+\s+[A-Za-z]", cleaned):
        parts = [part.strip() for part in cleaned.split(",") if part.strip()]
        if len(parts) >= 2:
            if len(parts) >= 3 and parts[-1].lower() == "south africa":
                return ", ".join(parts[-3:-1])
            return ", ".join(parts[-2:])
        trimmed = re.sub(r"\b\d{4}\b", "", cleaned).strip(" ,")
        province_tail = re.search(
            r"\b(?:gauteng|limpopo|mpumalanga|north west|western cape|eastern cape|free state|kwazulu[- ]natal)\b.*$",
            trimmed,
            re.I,
        )
        if province_tail:
            return sanitize_entity_text(province_tail.group(0)) or cleaned
        tail_words = trimmed.split()
        if len(tail_words) >= 2:
            return " ".join(tail_words[-2:])
    return cleaned


def _headline_is_clean(text: str) -> bool:
    cleaned = sanitize_entity_text(text) or ""
    lowered = cleaned.lower()
    if not cleaned:
        return False
    if lowered in {"professional profile", "profile", "professional summary", "summary"}:
        return False
    if len(cleaned.split()) > 8:
        return False
    if re.search(r"\b(?:curriculum vitae|resume|profile summary|objective)\b", lowered):
        return False
    return True


def _summary_is_weak(text: str) -> bool:
    cleaned = (sanitize_entity_text(text) or "").strip()
    if len(cleaned.split()) < 12:
        return True
    lowered = cleaned.lower()
    if any(term in lowered for term in ["hardworking", "dynamic individual", "team player", "willing to learn", "looking for"]):
        return True
    if re.match(r"^\s*(?:career\s+)?objectives?\b", lowered):
        return True
    return False


def _is_pure_education_history_entry(entry: Dict[str, Any]) -> bool:
    position = sanitize_entity_text(entry.get("position")) or ""
    company = sanitize_entity_text(entry.get("company")) or ""
    summary = sanitize_entity_text(entry.get("summary")) or ""
    responsibilities = [sanitize_entity_text(item) or "" for item in entry.get("responsibilities", []) or []]
    combined = " ".join(part for part in [position, company, summary, *responsibilities] if part).lower()
    position_lower = position.lower()
    if any(term in position_lower for term in EMPLOYMENT_ROLE_HINTS):
        return False
    if not any(term in combined for term in EDUCATION_RECORD_HINTS):
        return False
    has_work_evidence = bool(summary or any(item for item in responsibilities))
    return not has_work_evidence or any(term in position_lower for term in EDUCATION_RECORD_HINTS)


def _clean_additional_sections(profile: Dict[str, Any]) -> List[Dict[str, str]]:
    identity = profile.get("identity", {}) or {}
    blocked = {
        (sanitize_entity_text(identity.get("full_name")) or "").casefold(),
        (sanitize_entity_text(identity.get("headline")) or "").casefold(),
        (sanitize_entity_text(identity.get("email")) or "").casefold(),
        (sanitize_entity_text(identity.get("phone")) or "").casefold(),
        (sanitize_entity_text(profile.get("summary")) or "").casefold(),
    }
    result: List[Dict[str, str]] = []
    for section in profile.get("additional_sections", []):
        title = sanitize_entity_text(section.get("title")) or "Additional Information"
        lines: List[str] = []
        for raw_line in (section.get("content") or "").splitlines():
            line = sanitize_entity_text(raw_line) or ""
            if not line or line.casefold() in blocked:
                continue
            label_match = re.match(r"^([A-Za-z][A-Za-z /&+-]{1,30})\s*:\s*(.+)$", line)
            if label_match:
                label = label_match.group(1).strip().lower()
                if label in {"name", "full name", "availability", "headline", "title", "location", "region", "email", "phone", "mobile", "telephone", "linkedin", "portfolio", "website"}:
                    continue
            if EMAIL_RE.search(line) or PHONE_RE.search(line) or LINKEDIN_RE.search(line) or URL_RE.search(line):
                continue
            lines.append(line)
        lines = _dedupe_text_rows(lines)
        if lines:
            result.append({"title": title, "content": "\n".join(lines)})
    return result


def _raw_certification_fallback(raw_text: str) -> List[str]:
    lines = [sanitize_entity_text(line) or "" for line in raw_text.splitlines() if sanitize_entity_text(line)]
    # Strategy 1: lines that individually mention cert keywords
    keyword_hits = [line for line in lines if re.search(r"\b(?:certified|certification|certificate)\b", line, re.I)]
    # Strategy 2: items under a Certificates/Certifications heading
    heading_items: List[str] = []
    capture = False
    _cert_stop = {"education", "qualifications", "qualification", "training", "skills",
                  "experience", "employment", "references", "awards", "achievements",
                  "languages", "interests", "projects", "volunteering", "publications",
                  "career history", "work experience", "professional experience"}
    for line in lines:
        norm = normalize_heading(line)
        if norm in {"certificates", "certifications", "certification", "certificate"}:
            capture = True
            continue
        if capture:
            if norm in _cert_stop or norm in KNOWN_HEADING_TERMS:
                break
            cleaned = sanitize_entity_text(line) or ""
            if cleaned and len(cleaned.split()) <= 15 and not re.search(r"\b(?:19|20)\d{2}\s*[-–—]\s*(?:19|20)\d{2}\b", cleaned):
                heading_items.append(cleaned)
    return _group_certification_lines(_dedupe_text_rows(keyword_hits + heading_items))


def _raw_training_fallback(raw_text: str) -> List[str]:
    lines = [sanitize_entity_text(line) or "" for line in raw_text.splitlines() if sanitize_entity_text(line)]
    return _dedupe_text_rows([
        line for line in lines
        if any(token in line.lower() for token in TRAINING_HINTS)
        and not re.search(r"\b(?:certified|certification)\b", line, re.I)
        and normalize_heading(line) not in KNOWN_HEADING_TERMS
    ])


_PERSONAL_DETAIL_LABEL_MAP: Dict[str, str] = {
    "availability": "availability",
    "available": "availability",
    "notice period": "availability",
    "location": "location",
    "city": "location",
    "region": "region",
    "province": "region",
    "nationality": "nationality",
    "relocation": "relocation",
    "willing to relocate": "relocation",
    "languages": "languages",
    "language": "languages",
    "home language": "languages",
    "date of birth": "date_of_birth",
    "dob": "date_of_birth",
    "marital status": "marital_status",
    "gender": "gender",
    "race": "race",
    "id number": "id_number",
    "id no": "id_number",
    "drivers license": "drivers_license",
    "driver's license": "drivers_license",
    "driver's licence": "drivers_license",
    "drivers licence": "drivers_license",
    "criminal record": "criminal_record",
    "criminal offense": "criminal_record",
    "health": "health",
    "disability": "disability",
}

_PERSONAL_DETAIL_IDENTITY_FIELDS = {"availability", "location", "region"}


def _apply_personal_details_to_identity(profile: Dict[str, Any], content: str) -> None:
    """Extract label:value pairs from a Personal Details section and populate identity fields."""
    identity = profile.get("identity") or {}
    additional_parts: List[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = re.match(r"^([A-Za-z][A-Za-z /'-]{1,35}?)\s*[:]\s*(.+)$", stripped)
        if match:
            label_raw = match.group(1).strip()
            value = match.group(2).strip()
            label_key = label_raw.lower().strip()
            mapped = _PERSONAL_DETAIL_LABEL_MAP.get(label_key)
            if mapped and mapped in _PERSONAL_DETAIL_IDENTITY_FIELDS:
                if not identity.get(mapped):
                    identity[mapped] = value
            elif mapped == "languages":
                items = [v.strip() for v in re.split(r"[,;/]", value) if v.strip()]
                profile.setdefault("languages", []).extend(items)
            elif mapped:
                additional_parts.append(f"{label_raw}: {value}")
            else:
                additional_parts.append(stripped)
        else:
            additional_parts.append(stripped)
    if additional_parts:
        profile["additional_sections"].append({
            "title": "Personal Details",
            "content": "\n".join(additional_parts),
        })
    profile["identity"] = identity


def profile_from_sections(raw_text: str, sections: List[Any], path: Path) -> Dict[str, Any]:
    profile: Dict[str, Any] = {
        "document_meta": {
            "source_file": path.name,
            "source_type": path.suffix.lower().lstrip("."),
            "template_reference": TEMPLATE_COPY.name if TEMPLATE_COPY.exists() else None,
            "layout_flags": infer_layout_flags(raw_text, path, sections),
            "notes": [],
        },
        "identity": extract_identity(raw_text, sections, path),
        "summary": None,
        "summary_confidence": 0.0,
        "skills": {"declared": [], "inferred": infer_skills_from_text(raw_text, sections), "sa_context": [], "source_faithful": False},
        "education": [],
        "certifications": [],
        "training": [],
        "languages": [],
        "awards": [],
        "experience": [],
        "projects": [],
        "volunteering": [],
        "publications": [],
        "interests": [],
        "references": [],
        "additional_sections": [],
        "raw_sections": [asdict(section) for section in sections],
        "section_map": [],
        "confidence_overview": {},
    }
    section_confidences: Dict[str, float] = {}
    explicit_education = False
    explicit_experience = False
    explicit_certifications = False

    for section in sections:
        key = section.canonical_key
        content = section.content.strip()
        profile["section_map"].append({
            "title": section.title,
            "mapped_to": key,
            "confidence": section.confidence,
            "source": section.source,
            "preview": " ".join(content.splitlines()[:2])[:180],
        })
        section_confidences[key] = max(section_confidences.get(key, 0), section.confidence)
        if key == "summary" and not profile["summary"]:
            profile["summary"] = _paragraphize_source_summary(content)
            profile["summary_confidence"] = section.confidence
        elif key == "skills":
            skills, source_faithful = _extract_source_faithful_skill_items(content)
            profile["skills"]["declared"].extend(skills)
            profile["skills"]["source_faithful"] = bool(profile["skills"]["source_faithful"]) or source_faithful
        elif key == "education":
            explicit_education = True
            profile["education"].extend(parse_education_section(content))
        elif key == "certifications":
            explicit_certifications = True
            profile["certifications"].extend(_group_certification_lines([line.strip() for line in content.splitlines() if line.strip()]))
        elif key == "training":
            profile["training"].extend(_dedupe_text_rows([line.strip() for line in content.splitlines() if line.strip()]))
        elif key == "languages":
            profile["languages"].extend(parse_simple_items(content))
        elif key == "awards":
            profile["awards"].extend(parse_simple_items(content))
        elif key == "experience":
            parsed = parse_experience_section(content)
            if parsed:
                explicit_experience = True
                profile["experience"].extend(parsed)
        elif key == "projects":
            profile["projects"].extend(parse_simple_items(content))
        elif key == "volunteering":
            profile["volunteering"].extend(parse_simple_items(content))
        elif key == "publications":
            profile["publications"].extend(parse_simple_items(content))
        elif key == "interests":
            profile["interests"].extend(parse_simple_items(content))
        elif key == "references":
            profile["references"].extend(parse_reference_section(content))
        elif key == "personal_details":
            _apply_personal_details_to_identity(profile, content)
        elif key == "raw_unknown":
            profile["additional_sections"].append(summarize_unknown_section(section.title, content))

    if not explicit_education:
        profile["education"] = parse_education_section(raw_text)
    if not explicit_experience:
        profile["experience"] = parse_experience_section(raw_text)
    else:
        supplemental_experience = parse_experience_section(raw_text)
        if supplemental_experience:
            profile["experience"].extend(supplemental_experience)
    if not explicit_certifications:
        profile["certifications"] = _raw_certification_fallback(raw_text)
    if not profile["training"]:
        profile["training"] = _raw_training_fallback(raw_text)

    profile["education"] = _merge_education_rows(profile["education"], _rescue_education_rows_from_text(raw_text))
    profile["education"] = _prune_education_rows(profile["education"])
    profile["languages"] = _normalize_language_values(list(profile["languages"]) + _extract_languages_from_text(raw_text))
    profile["awards"] = _dedupe_text_rows(list(profile["awards"]) + _extract_awards_from_text(raw_text))
    profile["references"] = _clean_reference_rows(profile["references"], raw_text)
    profile["certifications"], profile["education"] = _clean_certifications(profile["certifications"], profile["education"])
    if re.search(r"\b(?:gmail|yahoo|hotmail|outlook)\.com\b", str((profile.get("identity") or {}).get("portfolio") or ""), re.I):
        profile["identity"]["portfolio"] = None
    email_value = sanitize_entity_text((profile.get("identity") or {}).get("email")) or ""
    portfolio_value = sanitize_entity_text((profile.get("identity") or {}).get("portfolio")) or ""
    if email_value and portfolio_value and "@" in email_value:
        email_domain = email_value.split("@", 1)[1].lower()
        if portfolio_value.lower() == email_domain or portfolio_value.lower().endswith(email_domain):
            profile["identity"]["portfolio"] = None
    portfolio_value = sanitize_entity_text((profile.get("identity") or {}).get("portfolio")) or ""
    if portfolio_value and not URL_RE.search(portfolio_value):
        profile["identity"]["portfolio"] = None
    best_phone = _extract_best_phone(raw_text)
    if best_phone:
        profile["identity"]["phone"] = best_phone

    if _summary_needs_rescue(profile.get("summary") or ""):
        profile["summary"] = None
        profile["summary_confidence"] = 0.0
    if not profile["summary"]:
        for block in build_text_blocks(raw_text)[:20]:
            text = block["text"]
            if _summary_needs_rescue(text):
                continue
            if 30 <= len(text.split()) <= 180 and not EMAIL_RE.search(text) and not PHONE_RE.search(text):
                profile["summary"] = _paragraphize_source_summary(text)
                profile["summary_confidence"] = 0.45
                break
    if not profile.get("summary") or _summary_needs_rescue(profile.get("summary") or ""):
        inferred_summary = _paragraphize_source_summary(infer_summary_fallback(raw_text) or "")
        if inferred_summary and not _summary_needs_rescue(inferred_summary):
            profile["summary"] = inferred_summary
            profile["summary_confidence"] = 0.68
        elif not profile.get("summary"):
            profile["summary_confidence"] = 0.0

    if not is_valid_name_candidate(profile["identity"].get("full_name") or ""):
        filename_name = infer_name_from_filename(path.name)
        if filename_name:
            profile["identity"]["full_name"] = filename_name
    else:
        # If filename-derived name is a strict subset of the document name
        # (sharing words), prefer the longer document name – it is more
        # complete.  E.g. filename "Prince Mafolo" vs document "Mochabo
        # Prince Mafolo".
        filename_name = infer_name_from_filename(path.name) if path else None
        if filename_name:
            doc_name = sanitize_entity_text(profile["identity"].get("full_name")) or ""
            fn_words = {w.casefold() for w in filename_name.split()}
            doc_words = {w.casefold() for w in doc_name.split()}
            shared = fn_words & doc_words
            if shared and len(shared) >= len(fn_words) - 1 and len(doc_words) > len(fn_words):
                pass  # keep the longer document name
            elif doc_name.casefold() == filename_name.casefold():
                pass  # exact match – keep either
            elif filename_name and doc_name:
                # Check if the document name appears in the raw text –
                # if it does, trust it over the filename.
                if doc_name in raw_text or doc_name.upper() in raw_text:
                    pass  # document name confirmed in source
                # Otherwise fall through – keep whichever we have

    explicit_upper_name = next(
        (
            line.strip()
            for line in raw_text.splitlines()[:8]
            if line.strip() == line.strip().upper() and is_valid_name_candidate(line.strip())
        ),
        "",
    )
    current_name = sanitize_entity_text(profile["identity"].get("full_name")) or ""
    if explicit_upper_name and current_name and explicit_upper_name.title() == current_name.title():
        profile["identity"]["full_name"] = explicit_upper_name

    profile["education"] = sorted(_prune_education_rows(profile["education"]), key=_education_sort_key, reverse=True)
    normalized_experience = sorted(clean_experience_entries(profile["experience"]), key=_experience_sort_key, reverse=True)
    if any(entry.get("start_date") or entry.get("end_date") for entry in normalized_experience):
        profile["experience"] = [
            entry for entry in normalized_experience
            if entry.get("start_date") or entry.get("end_date")
        ]
    else:
        profile["experience"] = [
            entry for entry in normalized_experience
            if entry.get("position") and entry.get("company")
        ]

    if not profile.get("summary") or _summary_needs_rescue(profile.get("summary") or ""):
        synthesized_summary = _paragraphize_source_summary(_synthesize_summary_from_profile(profile))
        if synthesized_summary and not _summary_needs_rescue(synthesized_summary):
            profile["summary"] = synthesized_summary
            profile["summary_confidence"] = max(profile.get("summary_confidence", 0.0), 0.62)

    current_headline = profile["identity"].get("headline") or ""
    if _headline_needs_role_promotion(current_headline) or not is_identity_headline_value_valid(current_headline):
        inferred_headline = infer_headline_from_profile(profile) or infer_headline_from_raw(raw_text)
        if inferred_headline:
            profile["identity"]["headline"] = inferred_headline

    profile["skills"]["declared"] = _augment_skill_lines_from_text(profile, raw_text)
    profile["skills"]["declared"] = _clean_declared_skills(profile)
    profile["skills"]["source_faithful"] = bool(profile["skills"].get("source_faithful")) or _skills_should_render_source_faithfully(profile["skills"]["declared"])
    profile["certifications"] = [_strip_leading_bullets(item) for item in profile["certifications"]]
    deduped_certifications = _dedupe_text_rows(profile["certifications"])
    if any(re.search(r"\b(?:19|20)\d{2}\b", row) for row in deduped_certifications):
        profile["certifications"] = sorted(deduped_certifications, key=_text_row_year_sort_key, reverse=True)
    else:
        profile["certifications"] = deduped_certifications
    profile["training"] = _dedupe_text_rows(profile["training"])
    profile["languages"] = _dedupe_text_rows(profile["languages"])
    profile["awards"] = _dedupe_text_rows(profile["awards"])
    profile["projects"] = _dedupe_text_rows(profile["projects"])
    profile["volunteering"] = _dedupe_text_rows(profile["volunteering"])
    profile["publications"] = _dedupe_text_rows(profile["publications"])
    profile["interests"] = _dedupe_text_rows(profile["interests"])
    profile["references"] = _dedupe_text_rows(profile["references"])
    profile["additional_sections"] = _clean_additional_sections(profile)
    profile["confidence_overview"] = {
        "identity": profile["identity"].get("confidence", 0.5),
        "summary": profile.get("summary_confidence", 0.0),
        "experience": section_confidences.get("experience", 0.0),
        "education": section_confidences.get("education", 0.0),
        "skills": section_confidences.get("skills", 0.0),
        "overall": round(sum(section_confidences.values()) / max(len(section_confidences), 1), 2),
    }
    return profile


def flatten_experience(entries: List[Dict[str, Any]]) -> Tuple[str, str]:
    if not entries:
        return "", ""
    summary_lines: List[str] = []
    history_lines: List[str] = []
    sorted_entries = sorted(clean_experience_entries(entries), key=_experience_sort_key, reverse=True)
    include_display_headers = len(sorted_entries) <= 2
    for entry in sorted_entries:
        company = sanitize_entity_text(entry.get("company")) or ""
        position = sanitize_entity_text(entry.get("position")) or ""
        start_date = format_recruiter_date(entry.get("start_date"))
        end_date = format_recruiter_date(entry.get("end_date"))
        if not company or not position:
            continue
        date_text = " – ".join(part for part in [start_date, end_date] if part)
        summary_line = f"{position} - {company}"
        if date_text:
            summary_line = f"{summary_line} ({date_text})"
        summary_lines.append(summary_line)
        if include_display_headers:
            history_lines.append(summary_line)
        history_lines.append(" | ".join([company, position, start_date, end_date]))
        raw_bullets = ([sanitize_entity_text(entry.get("summary")) or ""] if sanitize_entity_text(entry.get("summary")) else []) + list(entry.get("responsibilities", []) or [])
        bullets = _dedupe_text_rows(raw_bullets)
        if bullets:
            history_lines.append(f"Responsibilities: {bullets[0]}")
            for bullet in bullets[1:8]:
                history_lines.append(f"- {bullet}")
    return "\n".join(summary_lines), "\n".join(history_lines)


def profile_to_template_state(profile: Dict[str, Any]) -> Dict[str, str]:
    state = empty_template_state()
    identity = profile.get("identity", {}) or {}
    state["full_name"] = sanitize_entity_text(identity.get("full_name")) or ""
    headline = sanitize_entity_text(identity.get("headline")) or ""
    if _headline_needs_role_promotion(headline) or not is_identity_headline_value_valid(headline):
        headline = sanitize_entity_text(infer_headline_from_profile(profile) or infer_headline_from_raw(profile.get("summary") or "")) or ""
    state["headline"] = headline or "Professional Profile"
    state["availability"] = sanitize_entity_text(identity.get("availability")) or _friendly_placeholder("availability")
    state["region"] = _normalize_region_text(identity.get("region") or identity.get("location") or "") or _friendly_placeholder("region")
    state["email"] = sanitize_entity_text(identity.get("email")) or ""
    state["phone"] = sanitize_entity_text(identity.get("phone")) or ""
    _raw_location = sanitize_entity_text(identity.get("location")) or ""
    state["location"] = re.sub(r"^(?:location|address)\s*:\s*", "", _raw_location, flags=re.I).strip() or _friendly_placeholder("location")
    linkedin = re.sub(r"[?.,;]+$", "", sanitize_entity_text(identity.get("linkedin")) or "")
    portfolio = re.sub(r"[?.,;]+$", "", sanitize_entity_text(identity.get("portfolio")) or "")
    state["linkedin"] = linkedin or _friendly_placeholder("linkedin")
    state["portfolio"] = portfolio or _friendly_placeholder("portfolio")
    state["summary"] = _paragraphize_source_summary(profile.get("summary")) or ""

    skills = profile.get("skills", {}) or {}
    declared = list(skills.get("declared") or [])
    if bool(skills.get("source_faithful")):
        state["skills"] = "\n".join(_dedupe_text_rows(declared))
    else:
        state["skills"] = _bucket_skills_for_state(declared, skills.get("inferred") or {})

    state["education"] = "\n".join(_serialize_education_row(row) for row in sorted(profile.get("education", []) or [], key=_education_sort_key, reverse=True) if row.get("qualification"))
    raw_education_lines = []
    for section in profile.get("raw_sections", []) or []:
        if section.get("canonical_key") != "education":
            continue
        raw_education_lines.extend(
            line.strip().replace("â€“", "–").replace("â€”", "—")
            for line in str(section.get("content") or "").splitlines()
            if line.strip()
        )
    if raw_education_lines and any(token in line.lower() for line in raw_education_lines for token in ("incomplete", "in progress")):
        state["education"] = "\n".join(_dedupe_text_rows(raw_education_lines))
    cleaned_certifications = [_strip_leading_bullets(item) for item in (profile.get("certifications", []) or [])]
    state["certifications"] = "\n".join(_dedupe_text_rows(cleaned_certifications)) or _friendly_placeholder("certifications")
    training_rows = [
        (sanitize_entity_text(item) or "").replace("â€“", "–").replace("â€”", "—")
        for item in profile.get("training", []) or []
        if sanitize_entity_text(item)
    ]
    state["training"] = "\n".join(_dedupe_text_rows(training_rows)) or _friendly_placeholder("training")
    state["projects"] = "\n".join(_dedupe_text_rows(profile.get("projects", []) or [])) or _friendly_placeholder("projects")
    state["volunteering"] = "\n".join(_dedupe_text_rows(profile.get("volunteering", []) or [])) or _friendly_placeholder("volunteering")
    state["publications"] = "\n".join(_dedupe_text_rows(profile.get("publications", []) or [])) or _friendly_placeholder("publications")
    state["languages"] = "\n".join(_dedupe_text_rows(profile.get("languages", []) or [])) or _friendly_placeholder("languages")
    state["awards"] = "\n".join(_dedupe_text_rows(profile.get("awards", []) or [])) or _friendly_placeholder("awards")
    state["interests"] = "\n".join(_dedupe_text_rows(profile.get("interests", []) or [])) or _friendly_placeholder("interests")
    state["references"] = "\n".join(_dedupe_text_rows(profile.get("references", []) or [])) or _friendly_placeholder("references")
    state["career_summary"], state["career_history"] = flatten_experience(profile.get("experience", []) or [])
    state["additional_sections"] = "\n\n".join(f"{item['title']}\n{item['content']}" for item in profile.get("additional_sections", []) if item.get("content"))
    return state


def extract_linked_projects_from_experience(entries: List[Dict[str, Any]]) -> List[str]:
    linked: List[str] = []
    seen = set()
    for entry in entries:
        company = sanitize_entity_text(entry.get("company")) or sanitize_entity_text(entry.get("position")) or "Experience"
        for client in entry.get("clients", []) or []:
            project_name = sanitize_entity_text(client.get("project_name") or client.get("programme") or client.get("client_name"))
            client_name = sanitize_entity_text(client.get("client_name"))
            if not project_name:
                continue
            bits = [company, project_name]
            if client_name and client_name.lower() != project_name.lower():
                bits.append(client_name)
            summary = "; ".join((sanitize_entity_text(value) or "") for value in client.get("responsibilities", [])[:2] if sanitize_entity_text(value))
            if summary:
                bits.append(summary)
            item = " | ".join(bit for bit in bits if bit)
            key = item.casefold()
            if key not in seen:
                seen.add(key)
                linked.append(item)
    return linked


def clean_selected_text(selected_text: str, source_label: str = "") -> str:
    text = (selected_text or "").strip()
    label = (source_label or "").strip()
    if label and text.lower().startswith(label.lower()):
        remainder = text[len(label):].lstrip("\n: -")
        if remainder:
            text = remainder
    return text.strip()


def apply_field_value(existing: str, incoming: str, mode: str, kind: str) -> str:
    incoming = incoming.strip()
    existing = (existing or "").strip()
    if not incoming:
        return existing
    if mode in {"append", "new_item"}:
        if not existing:
            return incoming
        separator = "\n\n" if kind == "rich" else " | "
        if incoming.lower() in existing.lower():
            return existing
        return f"{existing.rstrip()}{separator}{incoming}"
    return incoming


def apply_selection_to_state(doc: Dict[str, Any], selected_text: str, target_key: str, mode: str, source_block_id: str = "manual", source_label: str = "") -> None:
    field_meta = FIELD_MAP[target_key]
    text = clean_selected_text(selected_text, source_label)
    if not text:
        return
    if target_key == "career_history":
        entries = clean_experience_entries(parse_experience_section(text))
        if entries:
            summary, history = flatten_experience(entries)
            doc["template_state"]["career_history"] = apply_field_value(doc["template_state"].get("career_history", ""), history or text, mode, "rich")
            if summary:
                doc["template_state"]["career_summary"] = apply_field_value(doc["template_state"].get("career_summary", ""), summary, mode, "rich")
            linked_projects = "\n".join(extract_linked_projects_from_experience(entries))
            if linked_projects:
                append_mode = "append" if (doc["template_state"].get("projects") or "").strip() and mode != "replace" else mode
                doc["template_state"]["projects"] = apply_field_value(doc["template_state"].get("projects", ""), linked_projects, append_mode, "rich")
            return
    if target_key == "education":
        items = parse_education_section(text)
        normalized = "\n".join(_serialize_education_row(item) for item in items if item.get("qualification")) or text
        doc["template_state"][target_key] = apply_field_value(doc["template_state"].get(target_key, ""), normalized, mode, field_meta["kind"])
        return
    if target_key == "certifications":
        normalized = "\n".join(_group_certification_lines([line.strip() for line in text.splitlines() if line.strip()])) or text
        doc["template_state"][target_key] = apply_field_value(doc["template_state"].get(target_key, ""), normalized, mode, field_meta["kind"])
        return
    if target_key in {"training", "projects", "volunteering", "publications", "languages", "awards", "interests", "references", "skills"}:
        items = parse_reference_section(text) if target_key == "references" else parse_simple_items(text)
        if not items:
            items = [line.strip() for line in text.splitlines() if line.strip()]
        normalized = "\n".join(_dedupe_text_rows(items)) or text
        doc["template_state"][target_key] = apply_field_value(doc["template_state"].get(target_key, ""), normalized, mode, field_meta["kind"])
        return
    if target_key == "summary":
        doc["template_state"][target_key] = apply_field_value(doc["template_state"].get(target_key, ""), _paragraphize_source_summary(text) or text, mode, field_meta["kind"])
        return
    doc["template_state"][target_key] = apply_field_value(doc["template_state"].get(target_key, ""), text, mode, field_meta["kind"])


def validate_profile_readiness(state: Dict[str, str]) -> List[str]:
    issues: List[str] = []
    full_name = (state.get("full_name") or "").strip()
    if not full_name:
        issues.append("Full Name is required before build can pass.")
    elif not is_valid_name_candidate(full_name):
        issues.append("Full Name needs a valid candidate name rather than a section or skills label.")
    headline = (state.get("headline") or "").strip()
    if not headline:
        issues.append("Professional Headline is required before build can pass.")
    elif not is_identity_headline_value_valid(headline) or not _headline_is_clean(headline):
        issues.append("Professional Headline needs a cleaner recruiter-facing title.")
    if _summary_is_weak((state.get("summary") or "").strip()):
        issues.append("Career Summary must be a polished recruiter-ready paragraph.")
    skill_lines = [line.strip() for line in (state.get("skills") or "").splitlines() if line.strip()]
    if not skill_lines:
        issues.append("Skills are required before build can pass.")
    elif any(
        line.startswith(":")
        or _looks_like_address_line(line)
        or _looks_like_language_proficiency_line(line)
        or normalize_heading(line) in {"experience", "employment history", "professional experience", "work experience", "career history"}
        or (line.count("|") >= 2 and re.search(r"\b(?:19|20)\d{2}|present|current|now\b", line, re.I))
        or any(term in line.lower() for term in PERSONAL_DETAIL_TERMS)
        or EDUCATION_INSTITUTION_RE.search(line)
        or re.fullmatch(r"(?:19|20)\d{2}\s*(?:[-â€“â€”]|Ã¢â‚¬â€œ|Ã¢â‚¬â€)\s*(?:Present|Current|Now|(?:19|20)\d{2})", line, re.I)
        for line in skill_lines
    ):
        issues.append("Skills appear contaminated by personal details, education, or career-history content.")

    education_lines = [line.strip() for line in (state.get("education") or "").splitlines() if line.strip()]
    if not education_lines:
        issues.append("Qualifications are required before build can pass.")
    else:
        parsed_education = parse_education_section("\n".join(education_lines))
        expected = len([line for line in education_lines if not re.search(r"\bqualification\b|\binstitution\b|\byear\b", line, re.I)])
        if len(parsed_education) < expected or any(not row.get("qualification") or not row.get("institution") for row in parsed_education):
            issues.append("Qualifications contain malformed rows that need review.")

    history = (state.get("career_history") or "").strip()
    career_summary = (state.get("career_summary") or "").strip()
    if not history:
        issues.append("Career History is required before build can pass.")
    else:
        if not career_summary:
            issues.append("Career Summary table must be populated when Career History exists.")
        parsed_history = parse_experience_section(history)
        history_has_role_info = any(
            re.search(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", line)
            for line in history.splitlines() if line.strip()
        )
        if not parsed_history and not history_has_role_info:
            issues.append("Career History contains malformed role, company, or date parsing.")
        elif parsed_history and any(not entry.get("position") or not entry.get("company") for entry in parsed_history):
            issues.append("Career History contains malformed role, company, or date parsing.")
        if any(_is_pure_education_history_entry(entry) for entry in parsed_history):
            issues.append("Career History contains pure education records that must be removed.")
        parsed_history_text = "\n".join("\n".join([sanitize_entity_text(entry.get("company")) or "", sanitize_entity_text(entry.get("position")) or "", sanitize_entity_text(entry.get("summary")) or "", *[sanitize_entity_text(item) or "" for item in entry.get("responsibilities", [])]]) for entry in parsed_history)
        if _contains_reference_marker(history) or _contains_reference_marker(parsed_history_text):
            issues.append("Career History appears contaminated by references or third-party contacts.")

    certifications = (state.get("certifications") or "").strip()
    if certifications and not _is_user_friendly_placeholder(certifications):
        if any(term in certifications.lower() for term in SCHOOL_QUALIFICATION_TERMS):
            issues.append("Certifications include school or formal qualification content that should be under Qualifications.")

    region = (state.get("region") or "").strip()
    if region and not _is_user_friendly_placeholder(region) and not _normalize_region_text(region) and len(region) > 40:
        issues.append("Region should be reduced to a recruiter-friendly location.")
    combined_identity = " ".join((state.get(key) or "") for key in ["full_name", "headline", "email", "phone", "location"])
    combined_identity = " ".join(part for part in combined_identity.split() if part)
    if combined_identity and _contains_reference_marker(combined_identity):
        issues.append("Candidate identity appears contaminated by references or third-party contacts.")
    portfolio = (state.get("portfolio") or "").strip()
    if portfolio and not _is_user_friendly_placeholder(portfolio) and not re.search(r"(?:https?://|www\.)\S+", portfolio, re.I):
        issues.append("Portfolio / Website must contain a valid web link.")
    references = (state.get("references") or "").strip()
    if references and not _is_user_friendly_placeholder(references) and any(term in references.lower() for term in ("distinction", "award", "achiever")):
        issues.append("References appear contaminated by awards or distinctions.")
    if "()" in "\n".join(value for value in state.values() if isinstance(value, str)):
        issues.append("Some fields still contain empty placeholders.")
    return issues


def build_review_board(template_state: Dict[str, str], profile: Optional[Dict[str, Any]] = None, *, precomputed_issues: Optional[List[str]] = None) -> Dict[str, Any]:
    issues = set(precomputed_issues if precomputed_issues is not None else validate_profile_readiness(template_state))
    sections: List[Dict[str, Any]] = []
    ready = 0
    attention = 0
    required_ready = 0
    labels = {"full_name": "Identity", "headline": "Professional Headline", "summary": "Career Summary", "skills": "Skills", "education": "Qualifications", "certifications": "Certifications", "career_history": "Career History"}
    for key in ["full_name", "headline", "summary", "skills", "education", "certifications", "career_history"]:
        value = (template_state.get(key) or "").strip()
        required = key in GEORGE_REQUIRED_KEYS
        if not value and not required:
            status = "Optional"
            issue = "Certifications are optional and may be omitted when not present." if key == "certifications" else f"{labels[key]} are optional."
        else:
            related = [issue for issue in issues if labels[key] in issue or (key == "full_name" and issue.startswith("Full Name")) or (key == "headline" and issue.startswith("Professional Headline"))]
            if related:
                status = "Needs review"
                issue = related[0]
            else:
                status = "Ready"
                issue = f"{labels[key]} ready"
        if status == "Ready":
            ready += 1
            if required:
                required_ready += 1
        elif status != "Optional":
            attention += 1
        sections.append({"key": key, "label": labels[key], "status": status, "issue": issue, "required": required, "preview": value.splitlines()[0][:120] if value else ""})
    return {"summary": {"ready": ready, "needs_attention": attention, "total": len(sections), "required_total": len(GEORGE_REQUIRED_KEYS), "required_ready": required_ready}, "sections": sections}


def build_workflow_state(template_state: Dict[str, str], review_board: Dict[str, Any], review_confirmed: bool = False, *, precomputed_issues: Optional[List[str]] = None) -> Dict[str, Any]:
    issues = precomputed_issues if precomputed_issues is not None else validate_profile_readiness(template_state)
    blocking_issues, warning_issues = split_validation_issues(issues)
    required_ready = review_board.get("summary", {}).get("required_ready", 0)
    review_ready = not blocking_issues and required_ready >= len(GEORGE_REQUIRED_KEYS)
    return {
        "preview_available": bool(template_state),
        "review_ready": review_ready,
        "review_confirmed": bool(review_confirmed and review_ready),
        "can_download": bool(template_state),
        "blocking_issues": blocking_issues,
        "warning_issues": warning_issues,
    }


# ---------------------------------------------------------------------------
# Final shared summary, language, awards, and identity-detail guardrails
# ---------------------------------------------------------------------------

_SUMMARY_SECTION_DUMP_TERMS = (
    "certificate / course / training",
    "certificates / courses / training",
    "education / qualifications",
    "qualification:",
    "institution:",
    "date:",
    "organisation:",
    "position:",
    "technologies:",
    "what i did",
    "skills and competencies",
)
_SAFE_PHONE_LABELS = {"phone", "mobile", "telephone", "tel", "cell", "cellphone", "contact number"}
_ID_LABELS = {"id number", "identity number", "id no", "passport", "passport number"}


def _split_pipe_label_value(line: str) -> tuple[str, str]:
    cleaned = sanitize_entity_text(line) or ""
    if not cleaned:
        return "", ""
    parts = [part for part in (sanitize_entity_text(piece) or "" for piece in cleaned.split("|")) if part]
    if len(parts) >= 2:
        return normalize_heading(parts[0].rstrip(":")), " | ".join(parts[1:]).strip(" |")
    match = re.match(r"^([A-Za-z][A-Za-z /&+-]{1,40}?)\s*:\s*(.+)$", cleaned)
    if not match:
        return "", ""
    return normalize_heading(match.group(1)), sanitize_entity_text(match.group(2)) or ""


def _collapse_duplicate_pipe_text(text: str) -> str:
    cleaned = sanitize_entity_text(text) or ""
    if not cleaned:
        return ""
    parts = [part for part in (sanitize_entity_text(piece) or "" for piece in cleaned.split("|")) if part]
    if len(parts) >= 2 and len({part.casefold() for part in parts}) == 1:
        return parts[0]
    return cleaned


_summary_needs_rescue_before_shared_guardrails = _summary_needs_rescue


def _summary_needs_rescue(text: str) -> bool:
    cleaned = sanitize_entity_text(text) or ""
    lowered = cleaned.lower()
    if _summary_needs_rescue_before_shared_guardrails(cleaned):
        return True
    if cleaned.count("|") >= 3:
        return True
    if sum(1 for term in _SUMMARY_SECTION_DUMP_TERMS if term in lowered) >= 2:
        return True
    if re.search(r"\b(?:qualification|institution|organisation|position|technologies)\s*:\s*", cleaned, re.I):
        return True
    return False


def _phone_candidate_is_safe(candidate: str, context_line: str = "") -> bool:
    cleaned = re.sub(r"\s+", " ", sanitize_entity_text(candidate) or "").strip()
    digits = re.sub(r"\D", "", cleaned)
    lowered_context = (sanitize_entity_text(context_line) or "").lower()
    if not cleaned or any(label in lowered_context for label in _ID_LABELS):
        return False
    if len(digits) < 10 or len(digits) > 12:
        return False
    if len(digits) == 13:
        return False
    if digits.startswith("0") and len(digits) == 10:
        return True
    if digits.startswith("27") and len(digits) == 11:
        return True
    if cleaned.startswith("+") and 11 <= len(digits) <= 12:
        return True
    if any(label in lowered_context for label in _SAFE_PHONE_LABELS):
        return True
    return False


def _extract_best_phone(raw_text: str) -> str:
    search_lines = _identity_window_lines(raw_text)
    for line in search_lines:
        label, value = _split_pipe_label_value(line)
        if label in _SAFE_PHONE_LABELS and _phone_candidate_is_safe(value, line):
            return re.sub(r"\s+", " ", value).strip()
    for line in search_lines:
        if any(label in line.lower() for label in _ID_LABELS):
            continue
        for match in PHONE_RE.finditer(line):
            candidate = re.sub(r"\s+", " ", match.group(0)).strip()
            if _phone_candidate_is_safe(candidate, line):
                return candidate
    return ""


_extract_languages_from_text_before_shared_guardrails = _extract_languages_from_text


def _extract_languages_from_text(raw_text: str) -> List[str]:
    languages = list(_extract_languages_from_text_before_shared_guardrails(raw_text))
    for raw_line in raw_text.splitlines():
        label, value = _split_pipe_label_value(raw_line)
        if label not in {"languages", "language"} or not value:
            continue
        for token in re.split(r"\s*,\s*|\s*/\s*|\s+\band\b\s+", value):
            language = sanitize_entity_text(token) or ""
            language = re.sub(r"^[^A-Za-z]+|[^A-Za-z]+$", "", language)
            if language:
                languages.append(language)
    return _dedupe_text_rows(languages)


_extract_awards_from_text_before_shared_guardrails = _extract_awards_from_text


def _extract_awards_from_text(raw_text: str) -> List[str]:
    awards = list(_extract_awards_from_text_before_shared_guardrails(raw_text))
    capture = False
    stop_headings = {
        "personal details",
        "qualifications",
        "education",
        "certifications",
        "training",
        "skills",
        "skills and competencies",
        "career history",
        "experience",
        "professional experience",
        "projects",
        "references",
    }
    for raw_line in raw_text.splitlines():
        cleaned = _collapse_duplicate_pipe_text(raw_line)
        if not cleaned:
            continue
        normalized = normalize_heading(cleaned)
        label, value = _split_pipe_label_value(cleaned)
        if normalized in {"key achievements / awards", "achievements / awards", "key achievements", "awards"} or label in {"key achievements / awards", "achievements / awards", "key achievements", "awards"}:
            capture = True
            if value and normalize_heading(value) not in {"key achievements / awards", "achievements / awards", "key achievements", "awards"}:
                awards.append(value)
            continue
        if capture:
            if re.match(r"^Reason for Leaving", cleaned, re.I):
                capture = False
                continue
            if normalize_heading(cleaned) in stop_headings:
                capture = False
                continue
            awards.append(cleaned)
    filtered: List[str] = []
    for item in _dedupe_text_rows(awards):
        normalized = normalize_heading(item)
        lowered = item.lower()
        if normalized in {"key achievements / awards", "achievements / awards", "key achievements", "awards"}:
            continue
        if "key achievements" in lowered and len(item.split()) <= 5:
            continue
        if lowered.startswith("awards:") and "key achievements" in lowered:
            continue
        filtered.append(item)
    return filtered


_clean_additional_sections_before_shared_guardrails = _clean_additional_sections


def _clean_additional_sections(profile: Dict[str, Any]) -> List[Dict[str, str]]:
    sections = _clean_additional_sections_before_shared_guardrails(profile)
    cleaned_sections: List[Dict[str, str]] = []
    identity_name = sanitize_entity_text(((profile.get("identity") or {}).get("full_name"))) or ""
    for section in sections:
        lines: List[str] = []
        for raw_line in (section.get("content") or "").splitlines():
            line = sanitize_entity_text(raw_line) or ""
            if not line:
                continue
            collapsed = _collapse_duplicate_pipe_text(line)
            if collapsed == identity_name:
                continue
            label, _ = _split_pipe_label_value(line)
            normalized = label or normalize_heading(line)
            if normalized in {"languages", "language", "id number", "identity number", "id no", "passport", "passport number"}:
                continue
            parts = [part for part in (sanitize_entity_text(piece) or "" for piece in line.split("|")) if part]
            if len(parts) >= 2:
                line = f"{parts[0].rstrip(':')}: {' | '.join(parts[1:])}".strip()
            lines.append(line)
        lines = _dedupe_text_rows(lines)
        if lines:
            cleaned_sections.append({"title": section.get("title") or "Additional Information", "content": "\n".join(lines)})
    return cleaned_sections


_prune_education_rows_before_shared_guardrails = _prune_education_rows


def _prune_education_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    pruned = _prune_education_rows_before_shared_guardrails(rows)
    filtered: List[Dict[str, Any]] = []
    for row in pruned:
        qualification = sanitize_entity_text(row.get("qualification")) or ""
        institution = sanitize_entity_text(row.get("institution")) or ""
        lowered_qualification = qualification.lower()
        if not qualification:
            continue
        if any(
            token in lowered_qualification
            for token in (
                "certificate / course / training",
                "institution | date",
                "qualification:",
                "provider | year",
            )
        ):
            continue
        if not institution and ("|" in qualification or "institution" in lowered_qualification or "date" in lowered_qualification):
            continue
        filtered.append(row)
    return filtered


def _synthesize_summary_from_profile(profile: Dict[str, Any]) -> str:
    headline = sanitize_entity_text((profile.get("identity") or {}).get("headline")) or "Technology professional"
    experience_entries = profile.get("experience", []) or []
    skills_profile = profile.get("skills", {}) or {}
    declared_skills = [sanitize_entity_text(item) or "" for item in skills_profile.get("declared", []) or []]
    declared_skills = [item for item in declared_skills if item and not _skill_line_is_leakage(item, profile)]

    if not declared_skills:
        for entry in experience_entries:
            for technology in entry.get("technologies", []) or []:
                candidate = sanitize_entity_text(technology) or ""
                if candidate and not _skill_line_is_leakage(candidate, profile):
                    declared_skills.append(candidate)
    declared_skills = _dedupe_text_rows(declared_skills)

    sentences: List[str] = []
    if experience_entries:
        sentences.append(
            f"{headline} with hands-on experience across software engineering, development, and delivery-focused roles."
        )
    else:
        sentences.append(f"{headline} with hands-on experience across software delivery and production support environments.")
    if declared_skills:
        sentences.append(f"Core strengths include {', '.join(declared_skills[:6])}.")
    if any(entry.get("clients") for entry in experience_entries) or any("(via " in (sanitize_entity_text(entry.get("company")) or "").lower() for entry in experience_entries):
        sentences.append("Brings consulting and client-facing delivery exposure grounded in multi-client and contract engagements.")
    elif len(experience_entries) >= 4:
        sentences.append("Brings experience across multiple delivery teams, production systems, and contract environments.")
    return " ".join(sentences).strip()
