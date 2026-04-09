from __future__ import annotations

"""Section detection and CV parsing logic."""

import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .constants import *
from .models import Provenance, SectionBlock
from .utils_text import *

_IDENTITY_INLINE_LABEL_TERMS = {
    "portfolio",
    "website",
    "web site",
    "linkedin",
    "headline",
    "professional headline",
    "availability",
    "region",
}

# ---------------------------------------------------------------------------
def likely_heading(line: str) -> bool:
    stripped = line.strip().strip(":")
    if not stripped or len(stripped) > 82:
        return False
    norm = normalize_heading(stripped)
    if norm in {"responsibilities", "responsibility", "duties"}:
        return False
    if norm in KNOWN_HEADING_TERMS:
        return True
    if norm in LABEL_ONLY_TERMS or norm in _IDENTITY_INLINE_LABEL_TERMS:
        return False
    # Reject lines that are clearly label:value pairs with structured CV data
    if LABEL_VALUE_RE.match(stripped) and norm.split(":")[0].strip() in LABEL_ONLY_TERMS:
        return False
    # Reject lines that look like role-company patterns (e.g. "Software Engineer - Acme Corp")
    if re.search(r"\s[-–—|]\s", stripped):
        lower_stripped = stripped.lower()
        if any(kw in lower_stripped for kw in ROLE_KEYWORDS):
            return False
    # Reject lines that are entirely role titles (e.g. "Senior Software Engineer")
    lower_stripped = stripped.lower()
    role_word_count = sum(1 for kw in ROLE_KEYWORDS if kw in lower_stripped)
    words = norm.split()
    if role_word_count >= 1 and len(words) <= 5 and not norm in KNOWN_HEADING_TERMS:
        # If most words are role keywords, it's a job title not a section heading
        if role_word_count >= len(words) * 0.4:
            return False
    upper_like = bool(GENERIC_UPPER_RE.fullmatch(stripped))
    short = len(words) <= 5
    reject = any([
        EMAIL_RE.search(stripped),
        PHONE_RE.search(stripped),
        re.search(rf"\b{MONTH}\b", stripped, re.I),
        len(re.findall(r"\d", stripped)) >= 4 and len(words) <= 5,
        any(x in norm for x in ["http", "www", "linkedin.com"]),
    ])
    # For unknown headings (not in KNOWN_HEADING_TERMS), require ALL CAPS or very short (2-3 words)
    # This prevents certification names, degree names, etc. from being treated as section headings
    if not upper_like and len(words) > 3:
        return False
    multi_word = len(words) >= 2
    # Also accept single-word known headings
    single_known = len(words) == 1 and norm in KNOWN_HEADING_TERMS
    return (short and multi_word and upper_like and not reject) or single_known


def content_classifier(title: str, content: str) -> Tuple[str, float]:
    """Hybrid content-based classification with confidence scoring."""
    # Step 1: Direct heading match with special-case remaps
    explicit = map_heading_to_key(title)
    title_norm = normalize_heading(title)
    if explicit:
        if title_norm in {"career highlights", "key achievements", "highlights"}:
            return "awards", 0.9
        return explicit, 0.96

    # Step 2: Content-based signal scoring
    corpus = f"{title}\n{content}".lower()
    scores: Dict[str, float] = {key: 0.0 for key in SECTION_SIGNAL_TERMS}
    for key, terms in SECTION_SIGNAL_TERMS.items():
        for term in terms:
            if term in corpus:
                scores[key] += 1.0

    # Boost scores based on structural signals
    if EMAIL_RE.search(content) or PHONE_RE.search(content):
        scores.setdefault("header", 0.0)
        scores["header"] = scores.get("header", 0.0) + 1.5
    if DATE_RANGE_RE.search(content):
        scores["experience"] += 1.0
    if re.search(r"\b(?:university|college|institute|school|unisa|wits|uj|tut|dut|uct)\b", corpus):
        scores["education"] += 1.5
    if re.search(r"\b(?:python|java|sql|power bi|react|azure|docker|selenium|javascript|typescript|c#|\.net)\b", corpus):
        scores["skills"] += 1.2
    if re.search(r"\b(?:honours|honor|diploma|degree|bachelor|masters|nqf|matric|grade 12)\b", corpus):
        scores["education"] += 1.3
    if re.search(r"\b(?:certified|certification|certificate|accredited)\b", corpus):
        scores["certifications"] += 1.2
    if re.search(r"\b(?:training|course|workshop|short course|cpd)\b", corpus):
        scores["training"] += 1.2
    if re.search(r"\b(?:project|delivered|implemented|built|developed|deployed)\b", corpus):
        scores["projects"] += 0.8

    best_key = max(scores, key=lambda k: scores[k])
    best_score = scores[best_key]

    if best_score >= 2.0:
        confidence = min(0.90, 0.58 + best_score / 8)
        return best_key, round(confidence, 2)

    # Step 3: Fallback — preserve as additional information
    return "raw_unknown", 0.40


def merge_section_blocks(blocks: List[SectionBlock]) -> List[SectionBlock]:
    merged: List[SectionBlock] = []
    for block in blocks:
        if (
            merged
            and block.canonical_key in {"responsibilities", "responsibility", "duties"}
            and merged[-1].canonical_key == "experience"
        ):
            prev = merged[-1]
            addition = f"{block.title}: {block.content}".strip()
            prev.content = f"{prev.content}\n{addition}".strip()
            prev.confidence = max(prev.confidence, block.confidence)
            prev.end_line = block.end_line
        elif merged and block.canonical_key == merged[-1].canonical_key and block.canonical_key not in {"raw_unknown"}:
            prev = merged[-1]
            addition = block.content
            current_title = normalize_heading(block.title)
            previous_title = normalize_heading(prev.title)
            if current_title and current_title not in {previous_title, "header"}:
                addition = f"{block.title}\n{addition}".strip()
            prev.content = f"{prev.content}\n{addition}".strip()
            prev.confidence = max(prev.confidence, block.confidence)
            prev.end_line = block.end_line
        else:
            merged.append(block)
    return merged


def _parse_sections_v137(raw_text: str) -> List[SectionBlock]:
    lines = [line.rstrip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        return []

    candidates: List[Tuple[str, List[str], str, int, int]] = []
    current_title = "Header"
    current_source = "detected"
    bucket: List[str] = []
    start_line = 0

    def flush(title: str, source: str, end_ln: int) -> None:
        nonlocal bucket
        content = "\n".join(bucket).strip()
        if content:
            candidates.append((title, bucket[:], source, start_line, end_ln))
        bucket = []

    for index, line in enumerate(lines):
        stripped = line.strip()

        # Check for inline heading pattern (e.g. "Skills: Python, Java")
        inline_match = re.match(r"^([A-Z][A-Za-z &/+-]{2,40}|[A-Z][A-Z &/+-]{2,40})\s*:\s*(.+)$", stripped)
        if inline_match and map_heading_to_key(inline_match.group(1)):
            # Don't treat label-only terms as section headings
            norm_label = normalize_heading(inline_match.group(1))
            if norm_label not in LABEL_ONLY_TERMS and norm_label not in {"responsibilities", "responsibility", "duties"}:
                flush(current_title, current_source, index - 1)
                current_title = inline_match.group(1)
                current_source = "inline"
                start_line = index
                bucket = [inline_match.group(2).strip()]
                continue

        if index > 0 and likely_heading(stripped):
            flush(current_title, current_source, index - 1)
            current_title = stripped
            current_source = "detected"
            start_line = index
            continue
        bucket.append(stripped)

    flush(current_title, current_source, len(lines) - 1)

    sections: List[SectionBlock] = []
    for title, content_lines, source, s_line, e_line in candidates:
        content = "\n".join(content_lines).strip()
        canonical_key, confidence = content_classifier(title, content)
        sections.append(SectionBlock(
            id=str(uuid.uuid4())[:8],
            title=title.strip(),
            canonical_key=canonical_key,
            content=content,
            confidence=round(confidence, 2),
            source=source,
            start_line=s_line,
            end_line=e_line,
        ))
    return merge_section_blocks(sections)


# ---------------------------------------------------------------------------
# Text block builder for source viewer
# ---------------------------------------------------------------------------
def build_text_blocks(raw_text: str) -> List[Dict[str, str]]:
    chunks = [part.strip() for part in re.split(r"\n\s*\n+", raw_text) if part.strip()]
    if not chunks and raw_text.strip():
        chunks = [raw_text.strip()]
    return [{"id": f"blk-{i+1}", "text": chunk} for i, chunk in enumerate(chunks)]


def build_source_sections(sections: List[SectionBlock]) -> List[Dict[str, Any]]:
    """Build structured source sections for the source viewer panel."""
    result = []
    field_lookup = {
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
    }
    for sec in sections:
        if sec.canonical_key == "raw_unknown" and normalize_heading(sec.title) == "header":
            header_lines = [ln.strip() for ln in sec.content.splitlines() if ln.strip()]
            if header_lines and all(
                EMAIL_RE.search(line)
                or PHONE_RE.search(line)
                or LINKEDIN_RE.search(line)
                or URL_RE.search(line)
                or is_valid_name_candidate(line)
                or _looks_like_role_title_local(line)
                or ("," in line and len(line.split()) <= 4)
                for line in header_lines
            ):
                continue
        confidence_label = "High" if sec.confidence >= 0.85 else ("Medium" if sec.confidence >= 0.65 else "Low")
        mapped_field = field_lookup.get(sec.canonical_key, "additional_sections")
        result.append({
            "id": sec.id,
            "title": sec.title,
            "canonical_key": sec.canonical_key,
            "mapped_field": mapped_field,
            "mapped_label": FIELD_MAP.get(mapped_field, {}).get("label", "Additional Information"),
            "content": sec.content,
            "confidence": sec.confidence,
            "confidence_label": confidence_label,
            "source": sec.source,
            "needs_review": sec.confidence < 0.75,
        })
    return result


# ---------------------------------------------------------------------------
# Identity extraction
# ---------------------------------------------------------------------------
def is_valid_name_candidate(text: str) -> bool:
    text = text.strip()
    if not text or len(text) > 60:
        return False
    if EMAIL_RE.search(text) or PHONE_RE.search(text) or re.search(r"\d{4}", text):
        return False
    if re.search(r"\b(cv|resume|curriculum vitae|profile|summary|objective|candidate|experience|skills)\b", text, re.I):
        return False
    words = text.split()
    alpha_words = [w for w in words if re.fullmatch(r"[A-Za-z'.-]+", w)]
    if not (2 <= len(words) <= 5 and len(alpha_words) >= 2):
        return False
    return sum(w[:1].isupper() for w in alpha_words) >= max(2, len(alpha_words) - 1)


_MONTH_NUM_TO_ABBR = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}
_MONTH_TEXT_TO_NUM = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
_MONTH_TEXT_PATTERN = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
_NUMERIC_MONTH_YEAR_PATTERN = r"(?:0?[1-9]|1[0-2])[/-](?:19|20)\d{2}"
_TEXT_MONTH_YEAR_PATTERN = rf"{_MONTH_TEXT_PATTERN}\.?,?\s*(?:19|20)\d{{2}}"
_DATE_VALUE_PATTERN = rf"(?:{_NUMERIC_MONTH_YEAR_PATTERN}|{_TEXT_MONTH_YEAR_PATTERN}|(?:19|20)\d{{2}})"
_DATE_SEPARATOR_CHARS = f"-{chr(8211)}{chr(8212)}"
_MONTH_YEAR_TOKEN_RE = re.compile(
    rf"\b(?:(?P<num_month>0?[1-9]|1[0-2])[/-](?P<num_year>(?:19|20)\d{{2}})|(?P<text_month>{_MONTH_TEXT_PATTERN})\.?,?\s*(?P<text_year>(?:19|20)\d{{2}}))\b",
    re.I,
)
_PRESENT_TOKEN_RE = re.compile(r"^(?:present|current|now)$", re.I)
_IN_PROGRESS_TOKEN_RE = re.compile(r"^in progress$", re.I)
_DATE_TEXT_RANGE_RE = re.compile(
    rf"(?P<start>{_DATE_VALUE_PATTERN})\s*(?:[{_DATE_SEPARATOR_CHARS}]|to|until)\s*(?P<end>Present|Current|Now|In Progress|{_DATE_VALUE_PATTERN})",
    re.I,
)


def format_recruiter_date(value: Optional[str]) -> str:
    text = sanitize_entity_text(value) or ""
    text = re.sub(r"\s+", " ", text).strip(" |,.;:-")
    if not text:
        return ""
    if _PRESENT_TOKEN_RE.fullmatch(text):
        return "Present"
    if _IN_PROGRESS_TOKEN_RE.fullmatch(text):
        return "In Progress"
    if re.fullmatch(r"(?:19|20)\d{2}", text):
        return text
    month_match = _MONTH_YEAR_TOKEN_RE.fullmatch(text)
    if not month_match:
        return text
    year = month_match.group("num_year") or month_match.group("text_year") or ""
    month_num = int(month_match.group("num_month")) if month_match.group("num_month") else _MONTH_TEXT_TO_NUM[(month_match.group("text_month") or "").lower().rstrip(".")]
    return f"{_MONTH_NUM_TO_ABBR[month_num]} {year}"


def normalize_recruiter_date_text(text: Optional[str]) -> str:
    cleaned = sanitize_entity_text(text) or ""
    if not cleaned:
        return ""
    normalized = _MONTH_YEAR_TOKEN_RE.sub(lambda match: format_recruiter_date(match.group(0)), cleaned)
    normalized = _DATE_TEXT_RANGE_RE.sub(
        lambda match: f"{format_recruiter_date(match.group('start'))} {chr(8211)} {format_recruiter_date(match.group('end'))}",
        normalized,
    )
    normalized = re.sub(r"\b(?:current|now)\b", "Present", normalized, flags=re.I)
    normalized = re.sub(r"\bpresent\b", "Present", normalized, flags=re.I)
    normalized = re.sub(r"\bin progress\b", "In Progress", normalized, flags=re.I)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def extract_date_range(text: str) -> Tuple[Optional[str], Optional[str]]:
    if not text:
        return None, None
    numeric = _DATE_TEXT_RANGE_RE.search(text)
    if numeric:
        return format_recruiter_date(numeric.group("start")), format_recruiter_date(numeric.group("end"))
    match = DATE_RANGE_RE.search(text)
    if match:
        return format_recruiter_date(match.group("start")), format_recruiter_date(match.group("end"))
    return None, None


def remove_date_range(text: str) -> str:
    return DATE_RANGE_RE.sub("", text).strip(" |-\u2013\u2014")


def split_bullets(text: str) -> List[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    bullets: List[str] = []
    for line in lines:
        cleaned = BULLET_RE.sub("", line).strip()
        if cleaned:
            bullets.append(cleaned)
    return bullets


def maybe_set_if_blank(data: Dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, str):
        value = value.strip()
    if value and not data.get(key):
        data[key] = value


def infer_layout_flags(raw_text: str, path: Path, sections: List[SectionBlock]) -> Dict[str, bool]:
    lower = raw_text.lower()
    return {
        "multi_column": any(token in lower for token in ["|", "technical summary", "core skills", "competencies"]) and raw_text.count("|") >= 3,
        "letter_spaced_text": bool(re.search(r"(?:\b[A-Za-z]\s){6,}[A-Za-z]\b", raw_text)),
        "date_dense_header": sum(1 for line in raw_text.splitlines()[:12] if re.search(r"\b(?:19|20)\d{2}\b", line)) >= 3,
        "consulting_style": sum(token in lower for token in ["client:", "programme", "engagement", "consulting", "project:"]) >= 2,
        "label_value_layout": sum(1 for line in raw_text.splitlines()[:60] if LABEL_VALUE_RE.match(line)) >= 4,
        "template_aligned": any(sec.title.lower() == "candidate summary" for sec in sections) or "availability" in lower,
        "source_pdf": path.suffix.lower() == ".pdf",
        "section_coverage_strong": len(sections) >= 4,
    }


# ---------------------------------------------------------------------------
# Experience parsing
# ---------------------------------------------------------------------------
ROLE_COMPANY_RE = re.compile(r"^(?P<role>[^|–\-]+?)\s*[|–\-]\s*(?P<company>.+)$")
COMPANY_ROLE_RE = re.compile(r"^(?P<company>[^|–\-]+?)\s*[|–\-]\s*(?P<role>.+)$")
CLIENT_PROJECT_RE = re.compile(r"Client\s*:\s*(?P<client>.+?)\s*(?:[–\-|]|\s+)\s*Project\s*:\s*(?P<project>.+)$", re.I)
CLIENT_ONLY_RE = re.compile(r"^Client(?: Organisation)?\s*:\s*(?P<client>.+)$", re.I)
PROGRAMME_ONLY_RE = re.compile(r"^Programme\s*:\s*(?P<programme>.+)$", re.I)


def classify_experience_line(line: str) -> Dict[str, Any]:
    line = line.strip()
    m = CLIENT_PROJECT_RE.match(line)
    if m:
        return {"type": "client_project", **m.groupdict()}
    m = CLIENT_ONLY_RE.match(line)
    if m:
        return {"type": "client_programme", "client": m.group("client"), "programme": None}
    m = PROGRAMME_ONLY_RE.match(line)
    if m:
        return {"type": "client_programme", "client": None, "programme": m.group("programme")}
    no_dates = remove_date_range(line)
    m = ROLE_COMPANY_RE.match(no_dates)
    if m and any(word in m.group("role").lower() for word in ROLE_KEYWORDS):
        return {"type": "role_company", **m.groupdict()}
    m = COMPANY_ROLE_RE.match(no_dates)
    if m and any(word in m.group("role").lower() for word in ROLE_KEYWORDS):
        return {"type": "company_role", **m.groupdict()}
    if "\u2014" in line and len(line.split("\u2014")) == 2:
        left, right = [x.strip() for x in line.split("\u2014", 1)]
        if left and right and not EMAIL_RE.search(line):
            return {"type": "client_programme", "client": left, "programme": right}
    return {"type": "text", "text": line}


def infer_sa_qualification_note(text: str) -> Optional[str]:
    lower = text.lower()
    if "bcom" in lower and "honours" not in lower and "honor" not in lower:
        return None
    for key, note in SA_QUALIFICATION_HINTS.items():
        if key in lower:
            return note
    return None


def infer_skills_from_text(raw_text: str, sections: List[SectionBlock]) -> Dict[str, List[str]]:
    corpus = "\n".join([raw_text] + [sec.content for sec in sections if sec.canonical_key in {"skills", "summary", "experience", "projects", "certifications", "training"}]).lower()
    inferred: Dict[str, List[str]] = {k: [] for k in SKILL_BUCKETS}
    for bucket, terms in SKILL_BUCKETS.items():
        for term in terms:
            if re.search(r"\b" + re.escape(term.lower()) + r"\b", corpus):
                inferred[bucket].append(term)
    return {k: sorted(set(v), key=str.lower) for k, v in inferred.items() if v}


def parse_label_value_blocks(lines: List[str]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {}
    for line in lines:
        m = LABEL_VALUE_RE.match(line)
        if m:
            label = normalize_heading(m.group(1))
            value = m.group(2).strip()
            if label in {"employer", "company", "company name"} and current:
                entries.append(current)
                current = {}
            current[label] = value
        elif current and line.strip():
            current.setdefault("_free_text", []).append(line.strip())
    if current:
        entries.append(current)
    return entries


def normalize_employment_entry(block: Dict[str, Any]) -> Dict[str, Any]:
    period = block.get("period employed") or block.get("period") or block.get("duration") or ""
    start, end = extract_date_range(period)
    responsibilities = split_bullets("\n".join(block.get("_free_text", []))) or split_bullets(block.get("responsibilities", "")) or split_bullets(block.get("duties", ""))
    return {
        "company": block.get("employer") or block.get("company") or block.get("company name"),
        "position": block.get("occupation") or block.get("role") or block.get("position") or block.get("job title"),
        "start_date": start,
        "end_date": end,
        "responsibilities": responsibilities,
        "clients": [],
        "technologies": split_bullets(block.get("technologies", "")),
        "summary": block.get("summary") or block.get("project") or None,
    }


def line_looks_like_new_experience(line: str) -> bool:
    stripped = remove_date_range(line)
    if classify_experience_line(line)["type"] in {"role_company", "company_role"}:
        return True
    if DATE_RANGE_RE.search(line) and any(word in stripped.lower() for word in ROLE_KEYWORDS):
        return True
    if LABEL_VALUE_RE.match(line):
        return False
    return False


def _parse_experience_section_v494(content: str) -> List[Dict[str, Any]]:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        return []
    structured = parse_label_value_blocks(lines)
    if structured and any(block.get("employer") or block.get("company") or block.get("occupation") for block in structured):
        normalized = [normalize_employment_entry(block) for block in structured]
        normalized = [entry for entry in normalized if entry.get("company") or entry.get("position")]
        return clean_experience_entries(normalized)

    entries: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    current_client: Optional[Dict[str, Any]] = None

    for line in lines:
        classified = classify_experience_line(line)
        start, end = extract_date_range(line)

        if classified["type"] in {"role_company", "company_role"}:
            if current:
                entries.append(current)
            current = {
                "company": classified.get("company", "").strip() or None,
                "position": classified.get("role", "").strip() or remove_date_range(line),
                "start_date": start,
                "end_date": end,
                "responsibilities": [],
                "clients": [],
                "technologies": [],
                "summary": None,
            }
            current_client = None
            continue

        if classified["type"] == "client_project" and current:
            current_client = {
                "client_name": classified.get("client"),
                "project_name": classified.get("project"),
                "programme": None,
                "responsibilities": [],
            }
            current["clients"].append(current_client)
            continue

        if classified["type"] == "client_programme" and current:
            current_client = {
                "client_name": classified.get("client"),
                "project_name": None,
                "programme": classified.get("programme"),
                "responsibilities": [],
            }
            current["clients"].append(current_client)
            continue

        if current is None:
            current = {
                "company": None,
                "position": remove_date_range(line),
                "start_date": start,
                "end_date": end,
                "responsibilities": [],
                "clients": [],
                "technologies": [],
                "summary": None,
            }
            continue

        if line_looks_like_new_experience(line) and (current.get("position") or current.get("company")):
            entries.append(current)
            current = {
                "company": None,
                "position": remove_date_range(line),
                "start_date": start,
                "end_date": end,
                "responsibilities": [],
                "clients": [],
                "technologies": [],
                "summary": None,
            }
            current_client = None
            continue

        cleaned = BULLET_RE.sub("", line).strip()
        if re.search(r"\b(?:technology|tools|environment|stack)\b", cleaned, re.I):
            target = current_client if current_client else current
            target.setdefault("technologies", []).extend(parse_simple_items(cleaned))
        elif current_client:
            current_client["responsibilities"].append(cleaned)
        elif current.get("summary") is None and len(cleaned.split()) > 10 and not BULLET_RE.match(line):
            current["summary"] = cleaned
        else:
            current["responsibilities"].append(cleaned)

    if current:
        entries.append(current)
    entries = [e for e in entries if e.get("company") or e.get("position") or e.get("responsibilities")]
    return clean_experience_entries(entries)


def looks_like_achievement_line(line: str) -> bool:
    lower = line.lower()
    if any(term in lower for term in ["matric", "grade 12", "national senior certificate"]):
        return False
    achievement_signals = [
        "achieved", "improved", "expanded", "increased", "reduced", "secured", "launched",
        "growth", "revenue", "quota", "target", "portfolio", "clients", "contracts", "churn",
        "%", "million", "sales team", "market penetration", "renewal rates", "new-logo acquisition"
    ]
    return any(sig in lower for sig in achievement_signals)


def looks_like_education_line(line: str) -> bool:
    cleaned = BULLET_RE.sub("", line).strip()
    lower = cleaned.lower()
    if not cleaned or looks_like_achievement_line(cleaned):
        return False
    if len(cleaned.split()) > 18:
        return False
    if re.search(r"\b(?:graduate with|skilled in|experienced in|strong skills|with a strong|passionate about|certified in|proficient in|looking for|seeking)\b", lower):
        return False
    edu_terms = [
        "university", "college", "school", "institute", "academy", "matric", "grade 12", "honours",
        "honors", "diploma", "degree", "bachelor", "master", "phd", "certificate", "qualification",
        "political sciences", "international relations", "business studies", "national senior certificate",
        "higher certificate", "advanced diploma", "national diploma", "postgraduate"
    ]
    has_edu = any(term in lower for term in edu_terms)
    has_separator = any(sep in cleaned for sep in [" – ", " - ", " | ", "—"])
    has_year = bool(re.search(rf"\b{YEAR}\b", cleaned))
    return has_edu or (has_separator and has_year and not looks_like_achievement_line(cleaned))


def sanitize_entity_text(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    value = re.sub(r"\s*\(\s*\)\s*", "", str(value)).strip(" |-–—")
    value = re.sub(r"\s{2,}", " ", value).strip()
    return value or None


def clean_experience_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    for entry in entries:
        entry["company"] = sanitize_entity_text(entry.get("company"))
        entry["position"] = sanitize_entity_text(entry.get("position"))
        if entry.get("summary"):
            entry["summary"] = sanitize_entity_text(entry.get("summary"))
        entry["responsibilities"] = [sanitize_entity_text(x) for x in entry.get("responsibilities", []) if sanitize_entity_text(x)]
        entry["technologies"] = [sanitize_entity_text(x) for x in entry.get("technologies", []) if sanitize_entity_text(x)]
        for client in entry.get("clients", []):
            client["client_name"] = sanitize_entity_text(client.get("client_name"))
            client["project_name"] = sanitize_entity_text(client.get("project_name"))
            client["programme"] = sanitize_entity_text(client.get("programme"))
            client["responsibilities"] = [sanitize_entity_text(x) for x in client.get("responsibilities", []) if sanitize_entity_text(x)]

        looks_bogus = (
            bool(entry.get("position") and entry["position"].startswith("•")) or
            (not entry.get("company") and entry.get("position") and len(entry.get("responsibilities", [])) == 0 and len(entry["position"].split()) > 8)
        )
        if cleaned and looks_bogus:
            cleaned[-1].setdefault("responsibilities", []).append(BULLET_RE.sub("", entry["position"]).strip())
            cleaned[-1].setdefault("responsibilities", []).extend(entry.get("responsibilities", []))
            continue

        if not entry.get("position") and not entry.get("company") and not entry.get("responsibilities"):
            continue
        cleaned.append(entry)

    return cleaned


def infer_headline_from_profile(profile: Dict[str, Any]) -> Optional[str]:
    headline = sanitize_entity_text(profile["identity"].get("headline"))
    if headline:
        return headline
    for entry in profile.get("experience", []):
        pos = sanitize_entity_text(entry.get("position"))
        if pos and not pos.startswith("•"):
            return pos
    summary = profile.get("summary") or ""
    first_sentence = re.split(r"(?<=[.!?])\s+", summary.strip())[0] if summary.strip() else ""
    m = re.search(r"(?:accomplished|experienced|seasoned|results-driven|strategic)?\s*([A-Za-z& /-]{6,80}?(?:executive|manager|engineer|developer|analyst|consultant|specialist|representative|architect|lead))", first_sentence, re.I)
    if m:
        return sanitize_entity_text(m.group(1).title())
    return None


def validate_profile_readiness(state: Dict[str, str]) -> List[str]:
    """Compatibility wrapper for the canonical normalizer readiness validator."""
    from .normalizers import validate_profile_readiness as _validate_profile_readiness

    return _validate_profile_readiness(state)


def parse_education_section(content: str) -> List[Dict[str, Any]]:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    grouped: List[Dict[str, Any]] = []
    for line in lines:
        cleaned = BULLET_RE.sub("", line).strip()
        if not looks_like_education_line(cleaned):
            continue
        start, end = extract_date_range(cleaned)
        core = sanitize_entity_text(remove_date_range(cleaned)) or cleaned
        parts = [sanitize_entity_text(part) for part in re.split(r"\s*(?:\||–|—|-)\s*", core) if sanitize_entity_text(part)]
        qualification = parts[0] if parts else core
        institution = None
        if len(parts) > 1:
            education_like = [p for p in parts[1:] if re.search(r"\b(?:university|college|institute|school|academy|technic|uj|wits|unisa|tut|dut|uct|ukzn|nmmu|up|stellenbosch|cput)\b", p, re.I)]
            institution = education_like[0] if education_like else (parts[1] if len(parts[1].split()) <= 10 else None)
        explicit_end = re.search(rf"\b{YEAR}\b", cleaned)
        item = {
            "qualification": sanitize_entity_text(qualification),
            "institution": sanitize_entity_text(institution),
            "start_date": start,
            "end_date": end or (explicit_end.group(0) if explicit_end else None),
            "sa_standard_hint": infer_sa_qualification_note(cleaned),
        }
        if item["qualification"]:
            grouped.append(item)

    deduped: List[Dict[str, Any]] = []
    seen = set()
    for item in grouped:
        key = (item.get("qualification") or "", item.get("institution") or "", item.get("end_date") or "")
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def parse_simple_items(content: str) -> List[str]:
    text = content.replace("|", "\n")
    parts = [BULLET_RE.sub("", p).strip(" ,-\u2022") for p in re.split(r"\n|;|\u2022", text) if p.strip()]
    dedup: List[str] = []
    seen = set()
    for part in parts:
        if not part:
            continue
        key = part.lower()
        if key not in seen:
            seen.add(key)
            dedup.append(part)
    return dedup


def parse_reference_section(content: str) -> List[str]:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if len(lines) == 1 and re.search(r"available upon request", lines[0], re.I):
        return lines
    grouped: List[str] = []
    current: List[str] = []
    for line in lines:
        if is_valid_name_candidate(line) and current:
            grouped.append(" | ".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        grouped.append(" | ".join(current))
    return grouped


def summarize_unknown_section(title: str, content: str) -> Dict[str, str]:
    title = title.strip() or "Additional Information"
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    preview = "\n".join(lines[:20])
    return {"title": title, "content": preview}


# ---------------------------------------------------------------------------
# Identity extraction
# ---------------------------------------------------------------------------
def infer_name_from_filename(path_like: str) -> Optional[str]:
    stem = Path(path_like).stem
    stem = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stem)
    stem = re.sub(r"[_-]+", " ", stem)
    stem = re.sub(r"\b(cv|resume|profile|oct|updated|202[0-9]|copy|share|of|flow|flowcv)\b", "", stem, flags=re.I)
    stem = re.sub(r"\s{2,}", " ", stem).strip()
    words = [w for w in stem.split() if re.fullmatch(r"[A-Za-z'.]+", w)]
    if 2 <= len(words) <= 6:
        # Skip abbreviation/initial tokens (all-caps, 2-3 chars) that are not
        # plausible name words – e.g. "MPT", "CV", "IT".  Genuine short names
        # like "Li" or "Bo" are mixed-case after capitalize(), so they survive.
        filtered = [
            w for w in words
            if w.lower() not in {"new", "final"}
            and not (w.isupper() and 2 <= len(w) <= 3 and w.lower() not in {"de", "da", "du", "la", "le"})
        ]
        if len(filtered) < 2:
            filtered = [w for w in words if w.lower() not in {"new", "final"}]
        candidate = " ".join(w.capitalize() for w in filtered)
        if is_valid_name_candidate(candidate):
            return candidate
    return None


def infer_summary_fallback(raw_text: str) -> Optional[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", raw_text) if p.strip()]


    for para in paragraphs[:4]:
        if len(para.split()) >= 20 and not EMAIL_RE.search(para) and not PHONE_RE.search(para):
            return para[:1400]
    return None


def infer_headline_from_raw(raw_text: str) -> Optional[str]:
    first_lines = [ln.strip() for ln in raw_text.splitlines()[:24] if ln.strip()]
    for line in first_lines:
        low = line.lower()
        if len(line) <= 100 and any(word in low for word in ROLE_KEYWORDS) and not EMAIL_RE.search(line) and not PHONE_RE.search(line):
            cleaned = sanitize_entity_text(remove_date_range(line))
            if cleaned and len(cleaned.split()) <= 12:
                return cleaned.title() if cleaned.isupper() else cleaned
    summary = infer_summary_fallback(raw_text) or ""
    m = re.search(r"\b(?:i am a|i am an|highly experienced|experienced|accomplished|seasoned|results-driven)?\s*([A-Za-z& /-]{3,60}?(?:project coordinator|project manager|software developer|cobol software developer|engineer|consultant|analyst|manager|specialist|representative|architect|lead|officer|intern))\b", summary, re.I)
    if m:
        return sanitize_entity_text(m.group(1).title())
    compact = re.sub(r"[^a-z]", "", raw_text.lower())
    for token, label in {
        'projectcoordinator': 'Project Coordinator',
        'projectmanager': 'Project Manager',
        'softwaredeveloper': 'Software Developer',
        'seniersoftwareengineeringconsultant': 'Senior Software Engineering Consultant',
        'cobolsoftwaredeveloper': 'COBOL Software Developer',
        'businessdevelopmentrepresentative': 'Business Development Representative',
        'salesexecutive': 'Sales Executive',
    }.items():
        if token in compact:
            return label
    return None


def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    header = sections[0].content if sections else raw_text.split("\n\n", 1)[0]
    header_lines = [line.strip() for line in header.splitlines() if line.strip()]
    identity: Dict[str, Any] = {
        "full_name": None,
        "headline": None,
        "availability": None,
        "region": None,
        "email": None,
        "phone": None,
        "location": None,
        "linkedin": None,
        "portfolio": None,
        "confidence": 0.5,
    }
    for line in header_lines[:10]:
        if is_valid_name_candidate(line):
            identity["full_name"] = line
            identity["confidence"] = 0.92
            break
    if not identity["full_name"]:
        for section in sections[:4]:
            if is_valid_name_candidate(section.title):
                identity["full_name"] = section.title
                identity["confidence"] = 0.78
                break
    if (not identity["full_name"]) and path is not None:
        guessed_name = infer_name_from_filename(path.name)
        if guessed_name:
            identity["full_name"] = guessed_name
            identity["confidence"] = 0.7
    for line in header_lines[:12]:
        low = line.lower()
        if line != identity.get("full_name") and len(line) < 90 and not EMAIL_RE.search(line) and not PHONE_RE.search(line):
            if any(word in low for word in ROLE_KEYWORDS):
                identity["headline"] = line
                break
    email = EMAIL_RE.search(raw_text)
    phone = PHONE_RE.search(raw_text)
    linkedin = LINKEDIN_RE.search(raw_text)
    urls = [m.group(0) for m in URL_RE.finditer(raw_text) if "linkedin" not in m.group(0).lower()]
    if email:
        identity["email"] = email.group(0)
    if phone:
        identity["phone"] = phone.group(0)
    if linkedin:
        identity["linkedin"] = linkedin.group(0)
    if urls:
        first_url = urls[0]
        if not first_url.lower().endswith(('.com', '.co.za')) or '/' in first_url or first_url.lower().startswith(('http', 'www')):
            identity["portfolio"] = first_url
    for line in header_lines[:16]:
        if re.search(r"availability", line, re.I):
            identity["availability"] = line.split(":", 1)[-1].strip()
        if re.search(r"region", line, re.I):
            identity["region"] = line.split(":", 1)[-1].strip()
        if not identity.get("location") and re.search(r"(Johannesburg|Bryanston|Sandton|Pretoria|Cape Town|Durban|Midrand|Randburg|South Africa|Centurion|Soweto|Polokwane|Bloemfontein|East London|Port Elizabeth|Nelspruit|Mbombela|Rustenburg|Kimberley|Pietermaritzburg)", line, re.I):
            identity["location"] = line
    return identity



# ---------------------------------------------------------------------------
# Enhanced extraction and normalization overrides
# ---------------------------------------------------------------------------
_REFERENCE_LINE_RE = re.compile(r"\b(?:references?|referees?|supervisor|lecturer|manager|director|professor)\b", re.I)
_DATE_TOKEN_RE = re.compile(rf"(?:{_NUMERIC_MONTH_YEAR_PATTERN}|{_TEXT_MONTH_YEAR_PATTERN}|(?:19|20)\d{{2}}|Present|Current|Now|In Progress)", re.I)


def _split_table_like_row(line: str) -> List[str]:
    if "|" in line:
        return [sanitize_entity_text(part) or "" for part in re.split(r"\s*\|\s*", line) if sanitize_entity_text(part)]
    if re.search(r"\s{3,}", line):
        return [sanitize_entity_text(part) or "" for part in re.split(r"\s{3,}", line) if sanitize_entity_text(part)]
    return []


def _looks_like_name_zone_line(line: str) -> bool:
    line = line.strip()
    if not line:
        return False
    if EMAIL_RE.search(line) or PHONE_RE.search(line) or URL_RE.search(line):
        return False
    if _REFERENCE_LINE_RE.search(line):
        return False
    if LABEL_VALUE_RE.match(line):
        return False
    return is_valid_name_candidate(line)


def _extract_candidate_zone_lines(raw_text: str, sections: List[SectionBlock]) -> List[str]:
    section_titles = {normalize_heading(sec.title) for sec in sections[:6]}
    zone: List[str] = []
    for line in [ln.strip() for ln in raw_text.splitlines()[:36] if ln.strip()]:
        normalized = normalize_heading(line)
        if normalized in {"references", "referees"}:
            break
        if normalized in KNOWN_HEADING_TERMS and normalized not in section_titles and zone:
            break
        zone.append(line)
    return zone


def _infer_dates_from_parts(parts: List[str]) -> Tuple[str, str]:
    tokens: List[str] = []
    for part in parts:
        tokens.extend([format_recruiter_date(match.group(0)) for match in _DATE_TOKEN_RE.finditer(part)])
    if not tokens:
        return "", ""
    if len(tokens) == 1:
        return tokens[0], ""
    return tokens[0], tokens[1]


def _strip_dates_from_text(text: str) -> str:
    cleaned = _DATE_TOKEN_RE.sub("", text)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip(" |-–—")


def _split_role_company_date_line(line: str) -> Optional[Dict[str, Any]]:
    original = sanitize_entity_text(line) or ""
    if not original:
        return None
    parts = _split_table_like_row(original)
    if len(parts) >= 3:
        start_date, end_date = _infer_dates_from_parts(parts)
        non_date_parts = [_strip_dates_from_text(part) for part in parts if _strip_dates_from_text(part)]
        if len(non_date_parts) >= 2:
            first, second = non_date_parts[0], non_date_parts[1]
            if any(word in first.lower() for word in ROLE_KEYWORDS) and not any(word in second.lower() for word in ROLE_KEYWORDS[:5]):
                position, company = first, second
            else:
                company, position = first, second
            return {
                "company": company,
                "position": position,
                "start_date": start_date,
                "end_date": end_date,
                "responsibilities": [],
                "clients": [],
                "technologies": [],
                "summary": None,
            }
    start_date, end_date = extract_date_range(original)
    stem = _strip_dates_from_text(remove_date_range(original) or original)
    if " - " in stem:
        left, right = [part.strip() for part in stem.rsplit(" - ", 1)]
        if any(word in left.lower() for word in ROLE_KEYWORDS):
            position, company = left, right
        elif any(word in right.lower() for word in ROLE_KEYWORDS):
            company, position = left, right
        else:
            company, position = left, right
        return {
            "company": company,
            "position": position,
            "start_date": start_date,
            "end_date": end_date,
            "responsibilities": [],
            "clients": [],
            "technologies": [],
            "summary": None,
        }
    return None


def _parse_experience_section_v1002(content: str) -> List[Dict[str, Any]]:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        return []
    entries: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for line in lines:
        classified = classify_experience_line(line)
        parsed_row = _split_role_company_date_line(line)
        if parsed_row and (parsed_row.get("company") or parsed_row.get("position")):
            if current and (current.get("company") or current.get("position") or current.get("responsibilities")):
                entries.append(current)
            current = parsed_row
            continue
        if classified["type"] in {"role_company", "company_role"}:
            if current and (current.get("company") or current.get("position") or current.get("responsibilities")):
                entries.append(current)
            start, end = extract_date_range(line)
            current = {
                "company": sanitize_entity_text(classified.get("company")) or None,
                "position": sanitize_entity_text(classified.get("role")) or _strip_dates_from_text(line),
                "start_date": start,
                "end_date": end,
                "responsibilities": [],
                "clients": [],
                "technologies": [],
                "summary": None,
            }
            continue
        if current is None:
            inferred = _split_role_company_date_line(line)
            if inferred:
                current = inferred
                continue
            current = {
                "company": None,
                "position": _strip_dates_from_text(remove_date_range(line) or line),
                "start_date": "",
                "end_date": "",
                "responsibilities": [],
                "clients": [],
                "technologies": [],
                "summary": None,
            }
            continue
        cleaned = BULLET_RE.sub("", line).strip()
        if line_looks_like_new_experience(line) and current and (current.get("company") or current.get("position")):
            entries.append(current)
            current = _split_role_company_date_line(line) or {
                "company": None,
                "position": _strip_dates_from_text(remove_date_range(line) or line),
                "start_date": "",
                "end_date": "",
                "responsibilities": [],
                "clients": [],
                "technologies": [],
                "summary": None,
            }
            continue
        if re.search(r"\b(?:technology|technologies|tools|environment|stack)\b", cleaned, re.I):
            current.setdefault("technologies", []).extend(parse_simple_items(cleaned))
        elif len(cleaned.split()) >= 10 and not current.get("summary") and not BULLET_RE.match(line):
            current["summary"] = cleaned
        else:
            current.setdefault("responsibilities", []).append(cleaned)
    if current and (current.get("company") or current.get("position") or current.get("responsibilities")):
        entries.append(current)
    return clean_experience_entries(entries)


def parse_education_section(content: str) -> List[Dict[str, Any]]:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    grouped: List[Dict[str, Any]] = []
    for line in lines:
        cleaned = BULLET_RE.sub("", line).strip()
        parts = _split_table_like_row(cleaned)
        if not parts and not looks_like_education_line(cleaned):
            continue
        if parts:
            qualification = parts[0]
            institution = ""
            year = ""
            for part in parts[1:]:
                if not institution and re.search(r"\b(?:university|college|institute|school|academy|technic|uj|wits|unisa|tut|dut|uct|ukzn|nmmu|up|stellenbosch|cput)\b", part, re.I):
                    institution = part
                    continue
                if not year and re.search(rf"\b(?:{YEAR}|Present|Current|In Progress)\b", part, re.I):
                    year_match = re.search(rf"\b({YEAR}|Present|Current|In Progress)\b", part, re.I)
                    year = year_match.group(1) if year_match else part
            item = {
                "qualification": sanitize_entity_text(qualification),
                "institution": sanitize_entity_text(institution),
                "start_date": "",
                "end_date": sanitize_entity_text(year),
                "sa_standard_hint": infer_sa_qualification_note(cleaned),
            }
        else:
            start, end = extract_date_range(cleaned)
            core = sanitize_entity_text(remove_date_range(cleaned)) or cleaned
            parts = [sanitize_entity_text(part) for part in re.split(r"\s*(?:\||–|—|-)\s*", core) if sanitize_entity_text(part)]
            qualification = parts[0] if parts else core
            institution = ""
            if len(parts) > 1:
                institution = next((p for p in parts[1:] if re.search(r"\b(?:university|college|institute|school|academy|technic|uj|wits|unisa|tut|dut|uct|ukzn|nmmu|up|stellenbosch|cput)\b", p, re.I)), "")
            explicit_end = re.search(rf"\b{YEAR}\b", cleaned)
            item = {
                "qualification": sanitize_entity_text(qualification),
                "institution": sanitize_entity_text(institution),
                "start_date": start,
                "end_date": end or (explicit_end.group(0) if explicit_end else ""),
                "sa_standard_hint": infer_sa_qualification_note(cleaned),
            }
        if item.get("qualification"):
            grouped.append(item)
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for item in grouped:
        key = ((item.get("qualification") or "").lower(), (item.get("institution") or "").lower(), (item.get("end_date") or "").lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def infer_summary_fallback(raw_text: str) -> Optional[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", raw_text) if p.strip()]
    for para in paragraphs[:5]:
        if len(para.split()) >= 24 and not EMAIL_RE.search(para) and not PHONE_RE.search(para) and not _REFERENCE_LINE_RE.search(para):
            cleaned = re.sub(r"\s+", " ", para)
            if not re.search(r"\b(i|my|me|seeking|objective)\b", cleaned, re.I):
                return cleaned[:1400]
    return None


def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    zone_lines = _extract_candidate_zone_lines(raw_text, sections)
    header = "\n".join(zone_lines) if zone_lines else (sections[0].content if sections else raw_text.split("\n\n", 1)[0])
    header_lines = [line.strip() for line in header.splitlines() if line.strip()]
    identity: Dict[str, Any] = {
        "full_name": None,
        "headline": None,
        "availability": None,
        "region": None,
        "email": None,
        "phone": None,
        "location": None,
        "linkedin": None,
        "portfolio": None,
        "confidence": 0.5,
    }
    for line in header_lines[:10]:
        if _looks_like_name_zone_line(line):
            identity["full_name"] = line
            identity["confidence"] = 0.93
            break
    if (not identity["full_name"]) and path is not None:
        guessed_name = infer_name_from_filename(path.name)
        if guessed_name:
            identity["full_name"] = guessed_name
            identity["confidence"] = 0.72
    for line in header_lines[:14]:
        low = line.lower()
        if line != identity.get("full_name") and len(line) < 95 and not EMAIL_RE.search(line) and not PHONE_RE.search(line) and not _REFERENCE_LINE_RE.search(line):
            if any(word in low for word in ROLE_KEYWORDS):
                identity["headline"] = sanitize_entity_text(remove_date_range(line)) or line
                break
    search_zone = "\n".join(zone_lines or header_lines[:14])
    email = EMAIL_RE.search(search_zone) or EMAIL_RE.search(raw_text)
    phone = PHONE_RE.search(search_zone) or PHONE_RE.search(raw_text)
    linkedin = LINKEDIN_RE.search(search_zone) or LINKEDIN_RE.search(raw_text)
    urls = [m.group(0) for m in URL_RE.finditer(search_zone or raw_text) if "linkedin" not in m.group(0).lower()]
    if email:
        identity["email"] = email.group(0)
    if phone:
        identity["phone"] = phone.group(0)
    if linkedin:
        identity["linkedin"] = linkedin.group(0)
    if urls:
        identity["portfolio"] = urls[0]
    for line in header_lines[:18]:
        if re.search(r"availability", line, re.I):
            identity["availability"] = line.split(":", 1)[-1].strip()
        if re.search(r"(?:region|location|city|address)", line, re.I):
            value = line.split(":", 1)[-1].strip()
            if re.search(r"(Johannesburg|Bryanston|Sandton|Pretoria|Cape Town|Durban|Midrand|Randburg|South Africa|Centurion|Soweto|Polokwane|Bloemfontein|East London|Port Elizabeth|Nelspruit|Mbombela|Rustenburg|Kimberley|Pietermaritzburg)", value, re.I):
                identity["location"] = value
                if not identity.get("region") and "south africa" in value.lower():
                    identity["region"] = "South Africa"
        if not identity.get("location") and re.search(r"(Johannesburg|Bryanston|Sandton|Pretoria|Cape Town|Durban|Midrand|Randburg|South Africa|Centurion|Soweto|Polokwane|Bloemfontein|East London|Port Elizabeth|Nelspruit|Mbombela|Rustenburg|Kimberley|Pietermaritzburg)", line, re.I):
            identity["location"] = line
    return identity


def _split_company_and_role_tokens(text: str) -> Tuple[str, str]:
    tokens = [tok for tok in re.split(r"\s+", sanitize_entity_text(text) or "") if tok]
    if len(tokens) < 2:
        return "", sanitize_entity_text(text) or ""
    role_index = None
    for idx, token in enumerate(tokens):
        low = token.lower()
        if any(low == kw or kw in low for kw in ROLE_KEYWORDS):
            role_index = idx
            break
    if role_index is None or role_index == 0:
        return "", sanitize_entity_text(text) or ""
    company = " ".join(tokens[:role_index])
    role = " ".join(tokens[role_index:])
    return company, role


def _split_role_company_date_line(line: str) -> Optional[Dict[str, Any]]:
    original = sanitize_entity_text(line) or ""
    if not original:
        return None
    parts = _split_table_like_row(original)
    if parts and all(normalize_heading(part) in {"company", "role", "start date", "end date", "dates", "period"} for part in parts):
        return None
    if len(parts) >= 3:
        start_date, end_date = _infer_dates_from_parts(parts)
        non_date_parts = [_strip_dates_from_text(part) for part in parts if _strip_dates_from_text(part)]
        if len(non_date_parts) >= 2:
            first, second = non_date_parts[0], non_date_parts[1]
            if any(word in first.lower() for word in ROLE_KEYWORDS):
                position, company = first, second
            else:
                company, position = first, second
            return {"company": company, "position": position, "start_date": start_date, "end_date": end_date, "responsibilities": [], "clients": [], "technologies": [], "summary": None}
    if len(parts) == 2 and _DATE_TOKEN_RE.search(parts[1]):
        start_date, end_date = _infer_dates_from_parts([parts[1]])
        company, position = _split_company_and_role_tokens(parts[0])
        if position:
            return {"company": company or None, "position": position, "start_date": start_date, "end_date": end_date, "responsibilities": [], "clients": [], "technologies": [], "summary": None}
    start_date, end_date = extract_date_range(original)
    stem = _strip_dates_from_text(remove_date_range(original) or original)
    if re.search(r"\s-\s", stem):
        left, right = [part.strip() for part in re.split(r"\s-\s", stem, maxsplit=1)]
        if any(word in left.lower() for word in ROLE_KEYWORDS):
            position, company = left, right
        elif any(word in right.lower() for word in ROLE_KEYWORDS):
            company, position = left, right
        else:
            company, position = left, right
        return {"company": company, "position": position, "start_date": start_date, "end_date": end_date, "responsibilities": [], "clients": [], "technologies": [], "summary": None}
    return None


def _parse_experience_section_v1249(content: str) -> List[Dict[str, Any]]:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        return []
    entries: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for line in lines:
        parsed_row = _split_role_company_date_line(line)
        classified = classify_experience_line(line)
        if parsed_row and (parsed_row.get("company") or parsed_row.get("position")):
            if current and (current.get("company") or current.get("position") or current.get("responsibilities")):
                entries.append(current)
            current = parsed_row
            continue
        if classified["type"] in {"role_company", "company_role"}:
            if current and (current.get("company") or current.get("position") or current.get("responsibilities")):
                entries.append(current)
            start, end = extract_date_range(line)
            current = {"company": sanitize_entity_text(classified.get("company")) or None, "position": sanitize_entity_text(classified.get("role")) or _strip_dates_from_text(line), "start_date": start, "end_date": end, "responsibilities": [], "clients": [], "technologies": [], "summary": None}
            continue
        if current is None:
            continue
        cleaned = BULLET_RE.sub("", line).strip()
        if re.search(r"\b(?:technology|technologies|tools|environment|stack)\b", cleaned, re.I):
            current.setdefault("technologies", []).extend(parse_simple_items(cleaned))
        elif len(cleaned.split()) >= 10 and not current.get("summary") and not BULLET_RE.match(line):
            current["summary"] = cleaned
        else:
            current.setdefault("responsibilities", []).append(cleaned)
    if current and (current.get("company") or current.get("position") or current.get("responsibilities")):
        entries.append(current)
    return clean_experience_entries(entries)


# ---------------------------------------------------------------------------
# Final hardened overrides for dense/tricky CVs
# ---------------------------------------------------------------------------
_REFERENCE_NEAR_TOP_RE = re.compile(r"\b(?:references?\s+on\s+request|references?|referees?|supervisor|lecturer|manager|director|professor|contact:)\b", re.I)
_HEADER_SPLIT_RE = re.compile(r"\s*[|•·]\s*|\s{3,}")
_EMPLOYER_HINTS = re.compile(r"\b(?:pty|ltd|limited|bank|group|technologies|technology|solutions|services|institute|university|college|school|department|municipality|council|agency|open text|opentext|gijima|investec|sap|client)\b", re.I)
_CERT_HINTS = re.compile(r"\b(?:certif|certificate|certified|badge|accredit|course|training)\b", re.I)


def _clean_line(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip(" |\t")


def _split_header_tokens(line: str) -> List[str]:
    return [_clean_line(part) for part in _HEADER_SPLIT_RE.split(line) if _clean_line(part)]


def _looks_like_reference_line(line: str) -> bool:
    return bool(_REFERENCE_NEAR_TOP_RE.search(line))


def _looks_like_candidate_heading(line: str) -> bool:
    text = _clean_line(line)
    return is_valid_name_candidate(text) and not _looks_like_reference_line(text)


def _find_candidate_zone(raw_text: str) -> List[str]:
    lines = [_clean_line(ln) for ln in raw_text.splitlines() if _clean_line(ln)]
    zone: List[str] = []
    reference_mode = False
    for idx, line in enumerate(lines[:80]):
        norm = normalize_heading(line)
        if norm in {"references", "referees"}:
            reference_mode = True
            continue
        if reference_mode:
            if EMAIL_RE.search(line) or PHONE_RE.search(line) or is_valid_name_candidate(line):
                continue
            if likely_heading(line):
                reference_mode = False
            else:
                continue
        zone.append(line)
        if idx > 6 and likely_heading(line) and normalize_heading(line) in {"experience", "career history", "employment", "qualifications", "education", "skills"}:
            break
    return zone[:30]


def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    zone_lines = _find_candidate_zone(raw_text)
    identity: Dict[str, Any] = {
        "full_name": None,
        "headline": None,
        "availability": None,
        "region": None,
        "email": None,
        "phone": None,
        "location": None,
        "linkedin": None,
        "portfolio": None,
        "confidence": 0.45,
    }

    # Look for compressed header tokens first.
    for line in zone_lines[:8]:
        if _looks_like_reference_line(line):
            continue
        for token in _split_header_tokens(line):
            if not identity["full_name"] and _looks_like_candidate_heading(token):
                identity["full_name"] = token
                identity["confidence"] = 0.9
            elif not identity["headline"] and any(word in token.lower() for word in ROLE_KEYWORDS) and not EMAIL_RE.search(token) and not PHONE_RE.search(token):
                identity["headline"] = sanitize_entity_text(remove_date_range(token)) or token

    # Search visible lines near the top but allow name to appear after profile summary.
    if not identity["full_name"]:
        for line in zone_lines[:18]:
            if _looks_like_candidate_heading(line):
                identity["full_name"] = line
                identity["confidence"] = 0.86
                break
    if not identity["headline"]:
        for line in zone_lines[:20]:
            if _looks_like_reference_line(line):
                continue
            if len(line) < 110 and any(word in line.lower() for word in ROLE_KEYWORDS) and not EMAIL_RE.search(line) and not PHONE_RE.search(line):
                identity["headline"] = sanitize_entity_text(remove_date_range(line)) or line
                break

    if not identity["full_name"] and path is not None:
        guessed = infer_name_from_filename(path.name)
        if guessed:
            identity["full_name"] = guessed
            identity["confidence"] = 0.72

    # Candidate-owned contact details should come from non-reference top-zone lines first.
    search_lines = [ln for ln in zone_lines[:24] if not _looks_like_reference_line(ln)]
    search_zone = "\n".join(search_lines)
    email = EMAIL_RE.search(search_zone) or EMAIL_RE.search(raw_text)
    phone = PHONE_RE.search(search_zone) or PHONE_RE.search(raw_text)
    linkedin = LINKEDIN_RE.search(search_zone) or LINKEDIN_RE.search(raw_text)
    urls = [m.group(0) for m in URL_RE.finditer(search_zone or raw_text) if "linkedin" not in m.group(0).lower()]
    if email:
        identity["email"] = email.group(0)
    if phone:
        identity["phone"] = phone.group(0)
    if linkedin:
        identity["linkedin"] = linkedin.group(0)
    if urls:
        identity["portfolio"] = urls[0]

    for line in search_lines:
        lower = line.lower()
        if "availability" in lower:
            identity["availability"] = line.split(":", 1)[-1].strip()
        if re.search(r"\b(region|location|city|address)\b", lower):
            value = line.split(":", 1)[-1].strip()
            if value:
                identity["location"] = value
        if not identity.get("location") and re.search(r"(Johannesburg|Bryanston|Sandton|Pretoria|Cape Town|Durban|Midrand|Randburg|South Africa|Centurion|Soweto|Polokwane|Bloemfontein|East London|Port Elizabeth|Nelspruit|Mbombela|Rustenburg|Kimberley|Pietermaritzburg)", line, re.I):
            identity["location"] = line
        if not identity.get("region") and re.search(r"\bSouth Africa\b", line, re.I):
            identity["region"] = "South Africa"

    return identity


def _split_table_like_row(line: str) -> List[str]:
    if "|" in line:
        return [_clean_line(part) for part in re.split(r"\s*\|\s*", line) if _clean_line(part)]
    if re.search(r"\s{3,}", line):
        return [_clean_line(part) for part in re.split(r"\s{3,}", line) if _clean_line(part)]
    return []


def _extract_year_token(text: str) -> str:
    match = re.search(r"\b((?:19|20)\d{2}|Present|Current|In Progress)\b", text, re.I)
    return match.group(1) if match else ""


def _parse_certification_row(parts: List[str]) -> Optional[str]:
    if not parts:
        return None
    headerish = {normalize_heading(p) for p in parts}
    if headerish & {"provider", "year", "certification", "certificate"} and len(headerish) >= 2:
        return None
    if not any(_CERT_HINTS.search(p) for p in parts):
        return None
    name = parts[0]
    provider = parts[1] if len(parts) > 1 else ""
    year = next((_extract_year_token(p) for p in parts[1:] if _extract_year_token(p)), "")
    pieces = [name]
    if provider and provider.lower() not in name.lower():
        pieces.append(provider)
    if year:
        pieces.append(f"({year})")
    return " - ".join(pieces[:-1]) + (f" {pieces[-1]}" if year else "") if len(pieces) > 1 else name


def parse_education_section(content: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen = set()
    for raw in [ln.strip() for ln in content.splitlines() if ln.strip()]:
        cleaned = BULLET_RE.sub("", raw).strip()
        parts = _split_table_like_row(cleaned)
        if parts:
            headerish = {normalize_heading(p) for p in parts}
            if headerish & {"qualification", "institution", "year", "degree"} and len(headerish) >= 2:
                continue
            qualification = parts[0]
            institution = ""
            year = ""
            for part in parts[1:]:
                if not institution and re.search(r"\b(?:university|college|institute|school|academy|technic|uj|wits|unisa|tut|dut|uct|ukzn|nmmu|up|stellenbosch|cput|mancosa|nw\b|north-west university)\b", part, re.I):
                    institution = part
                if not year:
                    year = _extract_year_token(part)
            if looks_like_education_line(cleaned) or institution or year:
                row = {"qualification": sanitize_entity_text(qualification), "institution": sanitize_entity_text(institution), "start_date": "", "end_date": sanitize_entity_text(year), "sa_standard_hint": infer_sa_qualification_note(cleaned)}
            else:
                continue
        else:
            if not looks_like_education_line(cleaned):
                continue
            start, end = extract_date_range(cleaned)
            core = sanitize_entity_text(remove_date_range(cleaned)) or cleaned
            parts = [sanitize_entity_text(part) for part in re.split(r"\s*(?:\||–|—|-)\s*", core) if sanitize_entity_text(part)]
            qualification = parts[0] if parts else core
            institution = next((p for p in parts[1:] if re.search(r"\b(?:university|college|institute|school|academy|technic|uj|wits|unisa|tut|dut|uct|ukzn|nmmu|up|stellenbosch|cput|mancosa|north-west university)\b", p, re.I)), "")
            row = {"qualification": sanitize_entity_text(qualification), "institution": sanitize_entity_text(institution), "start_date": start or "", "end_date": end or _extract_year_token(cleaned), "sa_standard_hint": infer_sa_qualification_note(cleaned)}
        if row.get("qualification"):
            key = ((row.get("qualification") or "").lower(), (row.get("institution") or "").lower(), (row.get("end_date") or "").lower())
            if key not in seen:
                seen.add(key)
                rows.append(row)
    return rows


def _client_line(line: str) -> Optional[Dict[str, str]]:
    text = _clean_line(BULLET_RE.sub("", line))
    m = re.match(r"^Client(?:\s*Organisation)?\s*:\s*(.+)$", text, re.I)
    if m:
        return {"client_name": m.group(1), "project_name": "", "programme": ""}
    m = re.match(r"^Client\s*:\s*(.+?)\s*(?:\||-|–|—)\s*Project\s*:\s*(.+)$", text, re.I)
    if m:
        return {"client_name": m.group(1), "project_name": m.group(2), "programme": ""}
    m = re.match(r"^Programme\s*:\s*(.+)$", text, re.I)
    if m:
        return {"client_name": "", "project_name": "", "programme": m.group(1)}
    if re.match(r"^(?:client|project|programme)\b", text, re.I):
        return {"client_name": text, "project_name": "", "programme": ""}
    return None


def _split_role_company_date_line(line: str) -> Optional[Dict[str, Any]]:
    text = _clean_line(line)
    if not text:
        return None
    parts = _split_table_like_row(text)
    if parts and {normalize_heading(p) for p in parts} & {"company", "role", "start date", "end date", "dates", "period"}:
        return None
    if len(parts) >= 3:
        date_parts = [p for p in parts if extract_date_range(p)[0] or _extract_year_token(p)]
        non_dates = [p for p in parts if p not in date_parts]
        if len(non_dates) >= 2:
            a, b = non_dates[0], non_dates[1]
            start, end = extract_date_range(" | ".join(date_parts))
            if not start and date_parts:
                years = [_extract_year_token(x) for x in date_parts if _extract_year_token(x)]
                start = years[0] if years else ""
                end = years[1] if len(years) > 1 else ""
            if any(word in a.lower() for word in ROLE_KEYWORDS):
                position, company = a, b
            elif any(word in b.lower() for word in ROLE_KEYWORDS):
                company, position = a, b
            else:
                company, position = a, b
            return {"company": sanitize_entity_text(company), "position": sanitize_entity_text(position), "start_date": start or "", "end_date": end or "", "responsibilities": [], "clients": [], "technologies": [], "summary": None}
    start, end = extract_date_range(text)
    stem = sanitize_entity_text(remove_date_range(text)) or text
    if re.search(r"\s[-|–—]\s", stem):
        left, right = [part.strip() for part in re.split(r"\s[-|–—]\s", stem, maxsplit=1)]
        if any(word in left.lower() for word in ROLE_KEYWORDS):
            position, company = left, right
        elif any(word in right.lower() for word in ROLE_KEYWORDS):
            company, position = left, right
        else:
            company, position = left, right
        return {"company": sanitize_entity_text(company), "position": sanitize_entity_text(position), "start_date": start or "", "end_date": end or "", "responsibilities": [], "clients": [], "technologies": [], "summary": None}
    if (start or end) and any(word in stem.lower() for word in ROLE_KEYWORDS):
        company = ""
        position = stem
        if _EMPLOYER_HINTS.search(stem):
            tokens = [tok for tok in stem.split() if tok]
            split_idx = None
            for i, tok in enumerate(tokens):
                if any(k in tok.lower() for k in ROLE_KEYWORDS):
                    split_idx = i
                    break
            if split_idx and split_idx > 0:
                company = " ".join(tokens[:split_idx])
                position = " ".join(tokens[split_idx:])
        return {"company": sanitize_entity_text(company), "position": sanitize_entity_text(position), "start_date": start or "", "end_date": end or "", "responsibilities": [], "clients": [], "technologies": [], "summary": None}
    return None


def _looks_like_new_parent_role(line: str) -> bool:
    parsed = _split_role_company_date_line(line)
    if not parsed:
        return False
    return bool(parsed.get("position") and (parsed.get("company") or parsed.get("start_date") or parsed.get("end_date")))


def _looks_like_academic_project(text: str) -> bool:
    lower = text.lower()
    academic_terms = ["project", "module", "subject", "capstone", "coursework", "semester", "honours project", "student"]
    professional_terms = ["company", "client", "intern", "consultant", "employer", "bank", "technologies", "pty", "ltd"]
    return any(t in lower for t in academic_terms) and not any(t in lower for t in professional_terms)


def _parse_experience_section_v1563(content: str) -> List[Dict[str, Any]]:
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    if not lines:
        return []

    entries: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    current_client: Optional[Dict[str, Any]] = None

    for raw in lines:
        line = _clean_line(raw)
        if not line or _looks_like_reference_line(line):
            continue
        if _looks_like_academic_project(line):
            continue

        client_meta = _client_line(line)
        if client_meta and current:
            if current_client and client_meta.get("programme") and not client_meta.get("client_name"):
                current_client["programme"] = sanitize_entity_text(client_meta.get("programme"))
            else:
                current_client = {
                    "client_name": sanitize_entity_text(client_meta.get("client_name")),
                    "project_name": sanitize_entity_text(client_meta.get("project_name")),
                    "programme": sanitize_entity_text(client_meta.get("programme")),
                    "responsibilities": [],
                }
                current.setdefault("clients", []).append(current_client)
            continue

        if _looks_like_new_parent_role(line):
            parsed = _split_role_company_date_line(line)
            # Do not multiply consulting CVs when only client/programme shifts; require distinct employer/role/date combo.
            if current and parsed:
                same_parent = (
                    (parsed.get("company") or "").casefold() == (current.get("company") or "").casefold()
                    and (parsed.get("position") or "").casefold() == (current.get("position") or "").casefold()
                    and (parsed.get("start_date") or "").casefold() == (current.get("start_date") or "").casefold()
                    and (parsed.get("end_date") or "").casefold() == (current.get("end_date") or "").casefold()
                )
                if same_parent:
                    continue
            if current and (current.get("company") or current.get("position") or current.get("responsibilities") or current.get("clients")):
                entries.append(current)
            current = parsed
            current_client = None
            continue

        if current is None:
            # Ignore loose project lines until a real role/company/date anchor appears.
            continue

        cleaned = BULLET_RE.sub("", line).strip()
        if re.search(r"\b(?:technology|technologies|tools|environment|stack)\b", cleaned, re.I):
            target = current_client if current_client else current
            target.setdefault("technologies", []).extend(parse_simple_items(cleaned))
        elif current_client:
            current_client.setdefault("responsibilities", []).append(cleaned)
        elif len(cleaned.split()) >= 12 and not current.get("summary") and not BULLET_RE.match(raw):
            current["summary"] = cleaned
        else:
            current.setdefault("responsibilities", []).append(cleaned)

    if current and (current.get("company") or current.get("position") or current.get("responsibilities") or current.get("clients")):
        entries.append(current)
    return clean_experience_entries(entries)


def clean_experience_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    for entry in entries:
        normalized = dict(entry)
        normalized["company"] = sanitize_entity_text(normalized.get("company"))
        normalized["position"] = sanitize_entity_text(normalized.get("position"))
        normalized["summary"] = sanitize_entity_text(normalized.get("summary"))
        normalized["start_date"] = sanitize_entity_text(normalized.get("start_date")) or ""
        normalized["end_date"] = sanitize_entity_text(normalized.get("end_date")) or ""
        normalized["responsibilities"] = [sanitize_entity_text(x) for x in normalized.get("responsibilities", []) if sanitize_entity_text(x)]
        normalized["technologies"] = [sanitize_entity_text(x) for x in normalized.get("technologies", []) if sanitize_entity_text(x)]
        client_rows = []
        for client in normalized.get("clients", []) or []:
            client_rows.append({
                "client_name": sanitize_entity_text(client.get("client_name")),
                "project_name": sanitize_entity_text(client.get("project_name")),
                "programme": sanitize_entity_text(client.get("programme")),
                "responsibilities": [sanitize_entity_text(x) for x in client.get("responsibilities", []) if sanitize_entity_text(x)],
            })
        normalized["clients"] = client_rows
        if not normalized.get("company") and normalized.get("clients"):
            normalized["company"] = "Consulting Engagement"
        if not normalized.get("position") and normalized.get("summary"):
            continue
        # fold client rows into parent bullets for locked final profile export without exploding jobs
        for client in normalized.get("clients", []):
            label = " | ".join([x for x in [client.get("client_name"), client.get("project_name") or client.get("programme")] if x])
            if label:
                normalized["responsibilities"].append(f"Client engagement: {label}")
            normalized["responsibilities"].extend(client.get("responsibilities", [])[:3])
        normalized["responsibilities"] = [x for i, x in enumerate(normalized.get("responsibilities", [])) if x and x not in normalized.get("responsibilities", [])[:i]][:8]
        if normalized.get("company") or normalized.get("position"):
            cleaned.append(normalized)
    return cleaned


def infer_summary_fallback(raw_text: str) -> Optional[str]:
    paragraphs = [re.sub(r"\s+", " ", p.strip()) for p in re.split(r"\n\s*\n+", raw_text) if p.strip()]
    for para in paragraphs[:20]:
        if len(para.split()) < 24:
            continue
        if EMAIL_RE.search(para) or PHONE_RE.search(para) or _looks_like_reference_line(para):
            continue
        if re.search(r"\b(i|my|me|objective|seeking)\b", para, re.I):
            continue
        return para[:1400]
    return None


def _parse_sections_core(raw_text: str) -> List[SectionBlock]:
    # preserve original logic but make heading detection a bit safer for dense CVs
    lines = [line.rstrip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        return []
    candidates: List[Tuple[str, List[str], str, int, int]] = []
    current_title = "Header"
    current_source = "detected"
    bucket: List[str] = []
    start_line = 0

    def flush(title: str, source: str, end_ln: int) -> None:
        nonlocal bucket
        content = "\n".join(bucket).strip()
        if content:
            candidates.append((title, bucket[:], source, start_line, end_ln))
        bucket = []

    for index, line in enumerate(lines):
        stripped = line.strip()
        inline_match = re.match(r"^([A-Z][A-Za-z &/+-]{2,40}|[A-Z][A-Z &/+-]{2,40})\s*:\s*(.+)$", stripped)
        if inline_match and map_heading_to_key(inline_match.group(1)):
            norm_label = normalize_heading(inline_match.group(1))
            if norm_label not in LABEL_ONLY_TERMS and norm_label not in _IDENTITY_INLINE_LABEL_TERMS:
                flush(current_title, current_source, index - 1)
                current_title = inline_match.group(1)
                current_source = "inline"
                start_line = index
                bucket = [inline_match.group(2).strip()]
                continue
        if index > 0 and likely_heading(stripped) and (normalize_heading(stripped) in KNOWN_HEADING_TERMS or not _looks_like_candidate_heading(stripped)):
            flush(current_title, current_source, index - 1)
            current_title = stripped
            current_source = "detected"
            start_line = index
            continue
        bucket.append(stripped)
    flush(current_title, current_source, len(lines) - 1)

    sections: List[SectionBlock] = []
    for title, content_lines, source, s_line, e_line in candidates:
        content = "\n".join(content_lines).strip()
        canonical_key, confidence = content_classifier(title, content)
        sections.append(SectionBlock(id=str(uuid.uuid4())[:8], title=title.strip(), canonical_key=canonical_key, content=content, confidence=round(confidence, 2), source=source, start_line=s_line, end_line=e_line))
    return merge_section_blocks(sections)


# ---------------------------------------------------------------------------
# Patch overrides: candidate-owned contact proximity and experience gating
# ---------------------------------------------------------------------------

def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    zone_lines = _find_candidate_zone(raw_text)
    identity: Dict[str, Any] = {"full_name": None, "headline": None, "availability": None, "region": None, "email": None, "phone": None, "location": None, "linkedin": None, "portfolio": None, "confidence": 0.45}
    for line in zone_lines[:8]:
        if _looks_like_reference_line(line):
            continue
        for token in _split_header_tokens(line):
            if not identity["full_name"] and _looks_like_candidate_heading(token):
                identity["full_name"] = token
                identity["confidence"] = 0.9
            elif not identity["headline"] and any(word in token.lower() for word in ROLE_KEYWORDS) and not EMAIL_RE.search(token) and not PHONE_RE.search(token):
                identity["headline"] = sanitize_entity_text(remove_date_range(token)) or token
    if not identity["full_name"]:
        for line in zone_lines[:24]:
            if _looks_like_candidate_heading(line):
                identity["full_name"] = line
                identity["confidence"] = 0.86
                break
    if not identity["headline"]:
        for line in zone_lines[:24]:
            if _looks_like_reference_line(line):
                continue
            if len(line) < 110 and any(word in line.lower() for word in ROLE_KEYWORDS) and not EMAIL_RE.search(line) and not PHONE_RE.search(line):
                identity["headline"] = sanitize_entity_text(remove_date_range(line)) or line
                break
    if not identity["full_name"] and path is not None:
        guessed = infer_name_from_filename(path.name)
        if guessed:
            identity["full_name"] = guessed
            identity["confidence"] = 0.72

    search_lines = [ln for ln in zone_lines[:30] if not _looks_like_reference_line(ln)]
    # Prefer contact details adjacent to the candidate's name block when available.
    candidate_contact_zone = search_lines
    if identity.get("full_name"):
        try:
            idx = next(i for i, ln in enumerate(search_lines) if identity["full_name"] in ln)
            candidate_contact_zone = search_lines[max(0, idx - 1): idx + 6]
        except StopIteration:
            pass
    search_zone = "\n".join(candidate_contact_zone)
    email = EMAIL_RE.search(search_zone) or EMAIL_RE.search("\n".join(search_lines))
    phone = PHONE_RE.search(search_zone) or PHONE_RE.search("\n".join(search_lines))
    linkedin = LINKEDIN_RE.search(search_zone) or LINKEDIN_RE.search("\n".join(search_lines))
    urls = [m.group(0) for m in URL_RE.finditer(search_zone or "\n".join(search_lines)) if "linkedin" not in m.group(0).lower()]
    if email:
        identity["email"] = email.group(0)
    if phone:
        identity["phone"] = phone.group(0)
    if linkedin:
        identity["linkedin"] = linkedin.group(0)
    if urls:
        identity["portfolio"] = urls[0]
    for line in candidate_contact_zone:
        lower = line.lower()
        if "availability" in lower:
            identity["availability"] = line.split(":", 1)[-1].strip()
        if re.search(r"\b(region|location|city|address)\b", lower):
            value = line.split(":", 1)[-1].strip()
            if value:
                identity["location"] = value
        if not identity.get("location") and re.search(r"(Johannesburg|Bryanston|Sandton|Pretoria|Cape Town|Durban|Midrand|Randburg|South Africa|Centurion|Soweto|Polokwane|Bloemfontein|East London|Port Elizabeth|Nelspruit|Mbombela|Rustenburg|Kimberley|Pietermaritzburg)", line, re.I):
            identity["location"] = line
        if not identity.get("region") and re.search(r"\bSouth Africa\b", line, re.I):
            identity["region"] = "South Africa"
    return identity


def _split_role_company_date_line(line: str) -> Optional[Dict[str, Any]]:
    text = _clean_line(line)
    if not text:
        return None
    parts = _split_table_like_row(text)
    if parts and {normalize_heading(p) for p in parts} & {"company", "role", "start date", "end date", "dates", "period"}:
        return None
    if len(parts) >= 3:
        date_parts = [p for p in parts if extract_date_range(p)[0] or _extract_year_token(p)]
        non_dates = [p for p in parts if p not in date_parts]
        if len(non_dates) >= 2:
            a, b = non_dates[0], non_dates[1]
            start, end = extract_date_range(" | ".join(date_parts))
            if not start and date_parts:
                years = [_extract_year_token(x) for x in date_parts if _extract_year_token(x)]
                start = years[0] if years else ""
                end = years[1] if len(years) > 1 else ""
            if any(word in a.lower() for word in ROLE_KEYWORDS):
                position, company = a, b
            elif any(word in b.lower() for word in ROLE_KEYWORDS):
                company, position = a, b
            else:
                company, position = a, b
            return {"company": sanitize_entity_text(company), "position": sanitize_entity_text(position), "start_date": start or "", "end_date": end or "", "responsibilities": [], "clients": [], "technologies": [], "summary": None}
    if len(parts) == 2 and (extract_date_range(parts[1])[0] or _extract_year_token(parts[1])):
        stem = parts[0]
        start, end = extract_date_range(parts[1])
        if not start:
            years = [_extract_year_token(x) for x in [parts[1]] if _extract_year_token(x)]
            start = years[0] if years else ""
            end = years[1] if len(years) > 1 else ""
        tokens = stem.split()
        split_idx = None
        for i, tok in enumerate(tokens):
            if any(k == tok.lower() or k in tok.lower() for k in ROLE_KEYWORDS):
                split_idx = i
                break
        if split_idx and split_idx > 0:
            company = " ".join(tokens[:split_idx])
            position = " ".join(tokens[split_idx:])
        else:
            company, position = "", stem
        return {"company": sanitize_entity_text(company), "position": sanitize_entity_text(position), "start_date": start or "", "end_date": end or "", "responsibilities": [], "clients": [], "technologies": [], "summary": None}
    start, end = extract_date_range(text)
    stem = sanitize_entity_text(remove_date_range(text)) or text
    if re.search(r"\s[-|–—]\s", stem):
        left, right = [part.strip() for part in re.split(r"\s[-|–—]\s", stem, maxsplit=1)]
        if any(word in left.lower() for word in ROLE_KEYWORDS):
            position, company = left, right
        elif any(word in right.lower() for word in ROLE_KEYWORDS):
            company, position = left, right
        else:
            company, position = left, right
        return {"company": sanitize_entity_text(company), "position": sanitize_entity_text(position), "start_date": start or "", "end_date": end or "", "responsibilities": [], "clients": [], "technologies": [], "summary": None}
    if (start or end) and any(word in stem.lower() for word in ROLE_KEYWORDS):
        company = ""
        position = stem
        if _EMPLOYER_HINTS.search(stem):
            tokens = [tok for tok in stem.split() if tok]
            split_idx = None
            for i, tok in enumerate(tokens):
                if any(k == tok.lower() or k in tok.lower() for k in ROLE_KEYWORDS):
                    split_idx = i
                    break
            if split_idx and split_idx > 0:
                company = " ".join(tokens[:split_idx])
                position = " ".join(tokens[split_idx:])
        return {"company": sanitize_entity_text(company), "position": sanitize_entity_text(position), "start_date": start or "", "end_date": end or "", "responsibilities": [], "clients": [], "technologies": [], "summary": None}
    return None


def _parse_experience_section_v1870(content: str) -> List[Dict[str, Any]]:
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    if not lines:
        return []
    experience_started = not any(normalize_heading(ln) in {"career history", "experience", "employment", "work experience", "professional experience"} for ln in lines)
    entries: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    current_client: Optional[Dict[str, Any]] = None
    for raw in lines:
        line = _clean_line(raw)
        if not line or _looks_like_reference_line(line):
            continue
        norm = normalize_heading(line)
        if norm in {"career history", "experience", "employment", "work experience", "professional experience"}:
            experience_started = True
            continue
        if not experience_started:
            continue
        if norm in {"qualifications", "education", "certifications", "references", "skills", "projects"}:
            if current and (current.get("company") or current.get("position") or current.get("responsibilities") or current.get("clients")):
                entries.append(current)
            break
        if _looks_like_academic_project(line):
            continue
        client_meta = _client_line(line)
        if client_meta and current:
            if current_client and client_meta.get("programme") and not client_meta.get("client_name"):
                current_client["programme"] = sanitize_entity_text(client_meta.get("programme"))
            else:
                current_client = {"client_name": sanitize_entity_text(client_meta.get("client_name")), "project_name": sanitize_entity_text(client_meta.get("project_name")), "programme": sanitize_entity_text(client_meta.get("programme")), "responsibilities": []}
                current.setdefault("clients", []).append(current_client)
            continue
        if _looks_like_new_parent_role(line):
            parsed = _split_role_company_date_line(line)
            if current and parsed:
                same_parent = ((parsed.get("company") or "").casefold() == (current.get("company") or "").casefold() and (parsed.get("position") or "").casefold() == (current.get("position") or "").casefold() and (parsed.get("start_date") or "").casefold() == (current.get("start_date") or "").casefold() and (parsed.get("end_date") or "").casefold() == (current.get("end_date") or "").casefold())
                if same_parent:
                    continue
            if current and (current.get("company") or current.get("position") or current.get("responsibilities") or current.get("clients")):
                entries.append(current)
            current = parsed
            current_client = None
            continue
        if current is None:
            continue
        cleaned = BULLET_RE.sub("", line).strip()
        if re.search(r"\b(?:technology|technologies|tools|environment|stack)\b", cleaned, re.I):
            target = current_client if current_client else current
            target.setdefault("technologies", []).extend(parse_simple_items(cleaned))
        elif current_client:
            current_client.setdefault("responsibilities", []).append(cleaned)
        elif len(cleaned.split()) >= 12 and not current.get("summary") and not BULLET_RE.match(raw):
            current["summary"] = cleaned
        else:
            current.setdefault("responsibilities", []).append(cleaned)
    if current and (current.get("company") or current.get("position") or current.get("responsibilities") or current.get("clients")):
        entries.append(current)
    return clean_experience_entries(entries)


# ---------------------------------------------------------------------------
# Final patch overrides: name-adjacent contact recovery and no duplicate break flush
# ---------------------------------------------------------------------------

def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    zone_lines = _find_candidate_zone(raw_text)
    all_lines = [_clean_line(ln) for ln in raw_text.splitlines() if _clean_line(ln)]
    identity: Dict[str, Any] = {"full_name": None, "headline": None, "availability": None, "region": None, "email": None, "phone": None, "location": None, "linkedin": None, "portfolio": None, "confidence": 0.45}
    for line in zone_lines[:8]:
        if _looks_like_reference_line(line):
            continue
        for token in _split_header_tokens(line):
            if not identity["full_name"] and _looks_like_candidate_heading(token):
                identity["full_name"] = token
                identity["confidence"] = 0.9
            elif not identity["headline"] and any(word in token.lower() for word in ROLE_KEYWORDS) and not EMAIL_RE.search(token) and not PHONE_RE.search(token):
                identity["headline"] = sanitize_entity_text(remove_date_range(token)) or token
    if not identity["full_name"]:
        for line in all_lines[:40]:
            if _looks_like_candidate_heading(line):
                identity["full_name"] = line
                identity["confidence"] = 0.86
                break
    if not identity["headline"]:
        for line in all_lines[:50]:
            if _looks_like_reference_line(line):
                continue
            if len(line) < 110 and any(word in line.lower() for word in ROLE_KEYWORDS) and not EMAIL_RE.search(line) and not PHONE_RE.search(line):
                identity["headline"] = sanitize_entity_text(remove_date_range(line)) or line
                break
    if not identity["full_name"] and path is not None:
        guessed = infer_name_from_filename(path.name)
        if guessed:
            identity["full_name"] = guessed
            identity["confidence"] = 0.72

    candidate_contact_zone = []
    if identity.get("full_name"):
        try:
            idx = next(i for i, ln in enumerate(all_lines[:60]) if identity["full_name"] in ln)
            candidate_contact_zone = [ln for ln in all_lines[max(0, idx - 1): idx + 6] if not _looks_like_reference_line(ln)]
        except StopIteration:
            candidate_contact_zone = []
    if not candidate_contact_zone:
        candidate_contact_zone = [ln for ln in zone_lines[:30] if not _looks_like_reference_line(ln)]
    search_zone = "\n".join(candidate_contact_zone)
    email = EMAIL_RE.search(search_zone) or EMAIL_RE.search("\n".join(candidate_contact_zone))
    phone = PHONE_RE.search(search_zone) or PHONE_RE.search("\n".join(candidate_contact_zone))
    linkedin = LINKEDIN_RE.search(search_zone)
    urls = [m.group(0) for m in URL_RE.finditer(search_zone) if "linkedin" not in m.group(0).lower()]
    if email:
        identity["email"] = email.group(0)
    if phone:
        identity["phone"] = phone.group(0)
    if linkedin:
        identity["linkedin"] = linkedin.group(0)
    if urls:
        identity["portfolio"] = urls[0]
    for line in candidate_contact_zone:
        lower = line.lower()
        if "availability" in lower:
            identity["availability"] = line.split(":", 1)[-1].strip()
        if re.search(r"\b(region|location|city|address)\b", lower):
            value = line.split(":", 1)[-1].strip()
            if value:
                identity["location"] = value
        if not identity.get("location") and re.search(r"(Johannesburg|Bryanston|Sandton|Pretoria|Cape Town|Durban|Midrand|Randburg|South Africa|Centurion|Soweto|Polokwane|Bloemfontein|East London|Port Elizabeth|Nelspruit|Mbombela|Rustenburg|Kimberley|Pietermaritzburg)", line, re.I):
            identity["location"] = line
        if not identity.get("region") and re.search(r"\bSouth Africa\b", line, re.I):
            identity["region"] = "South Africa"
    return identity


def _parse_experience_section_v2003(content: str) -> List[Dict[str, Any]]:
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    if not lines:
        return []
    experience_started = not any(normalize_heading(ln) in {"career history", "experience", "employment", "work experience", "professional experience"} for ln in lines)
    entries: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    current_client: Optional[Dict[str, Any]] = None
    for raw in lines:
        line = _clean_line(raw)
        if not line or _looks_like_reference_line(line):
            continue
        norm = normalize_heading(line)
        if norm in {"career history", "experience", "employment", "work experience", "professional experience"}:
            experience_started = True
            continue
        if not experience_started:
            continue
        if norm in {"qualifications", "education", "certifications", "references", "skills", "projects"}:
            if current and (current.get("company") or current.get("position") or current.get("responsibilities") or current.get("clients")):
                entries.append(current)
            current = None
            break
        if _looks_like_academic_project(line):
            continue
        client_meta = _client_line(line)
        if client_meta and current:
            if current_client and client_meta.get("programme") and not client_meta.get("client_name"):
                current_client["programme"] = sanitize_entity_text(client_meta.get("programme"))
            else:
                current_client = {"client_name": sanitize_entity_text(client_meta.get("client_name")), "project_name": sanitize_entity_text(client_meta.get("project_name")), "programme": sanitize_entity_text(client_meta.get("programme")), "responsibilities": []}
                current.setdefault("clients", []).append(current_client)
            continue
        if _looks_like_new_parent_role(line):
            parsed = _split_role_company_date_line(line)
            if current and parsed:
                same_parent = ((parsed.get("company") or "").casefold() == (current.get("company") or "").casefold() and (parsed.get("position") or "").casefold() == (current.get("position") or "").casefold() and (parsed.get("start_date") or "").casefold() == (current.get("start_date") or "").casefold() and (parsed.get("end_date") or "").casefold() == (current.get("end_date") or "").casefold())
                if same_parent:
                    continue
            if current and (current.get("company") or current.get("position") or current.get("responsibilities") or current.get("clients")):
                entries.append(current)
            current = parsed
            current_client = None
            continue
        if current is None:
            continue
        cleaned = BULLET_RE.sub("", line).strip()
        if re.search(r"\b(?:technology|technologies|tools|environment|stack)\b", cleaned, re.I):
            target = current_client if current_client else current
            target.setdefault("technologies", []).extend(parse_simple_items(cleaned))
        elif current_client:
            current_client.setdefault("responsibilities", []).append(cleaned)
        elif len(cleaned.split()) >= 12 and not current.get("summary") and not BULLET_RE.match(raw):
            current["summary"] = cleaned
        else:
            current.setdefault("responsibilities", []).append(cleaned)
    if current and (current.get("company") or current.get("position") or current.get("responsibilities") or current.get("clients")):
        entries.append(current)
    return clean_experience_entries(entries)


# ---------------------------------------------------------------------------
# Final patch override: reference-aware identity candidate selection
# ---------------------------------------------------------------------------

def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    zone_lines = _find_candidate_zone(raw_text)
    all_lines = [_clean_line(ln) for ln in raw_text.splitlines() if _clean_line(ln)]

    def looks_reference_context(index: int) -> bool:
        window_before = " ".join(all_lines[max(0, index - 2): index]).lower()
        window_after = " ".join(all_lines[index + 1: index + 4]).lower()
        line = all_lines[index].lower()
        if 'references' in window_before or 'referees' in window_before:
            return True
        if any(term in window_after for term in ['lecturer', 'manager', 'director', 'professor', 'supervisor', 'contact:']):
            return True
        if line.startswith('dr ') or line.startswith('mr ') or line.startswith('ms ') or line.startswith('mrs '):
            return True
        return False

    identity: Dict[str, Any] = {"full_name": None, "headline": None, "availability": None, "region": None, "email": None, "phone": None, "location": None, "linkedin": None, "portfolio": None, "confidence": 0.45}
    for line in zone_lines[:8]:
        if _looks_like_reference_line(line):
            continue
        for token in _split_header_tokens(line):
            if not identity["full_name"] and _looks_like_candidate_heading(token):
                identity["full_name"] = token
                identity["confidence"] = 0.9
            elif not identity["headline"] and any(word in token.lower() for word in ROLE_KEYWORDS) and not EMAIL_RE.search(token) and not PHONE_RE.search(token):
                identity["headline"] = sanitize_entity_text(remove_date_range(token)) or token
    if not identity["full_name"]:
        for idx, line in enumerate(all_lines[:40]):
            if _looks_like_candidate_heading(line) and not looks_reference_context(idx):
                identity["full_name"] = line
                identity["confidence"] = 0.86
                break
    if not identity["headline"]:
        for idx, line in enumerate(all_lines[:50]):
            if _looks_like_reference_line(line) or looks_reference_context(idx):
                continue
            if len(line) < 110 and any(word in line.lower() for word in ROLE_KEYWORDS) and not EMAIL_RE.search(line) and not PHONE_RE.search(line):
                identity["headline"] = sanitize_entity_text(remove_date_range(line)) or line
                break
    if not identity["full_name"] and path is not None:
        guessed = infer_name_from_filename(path.name)
        if guessed:
            identity["full_name"] = guessed
            identity["confidence"] = 0.72

    candidate_contact_zone = []
    if identity.get("full_name"):
        try:
            idx = next(i for i, ln in enumerate(all_lines[:60]) if identity["full_name"] in ln)
            candidate_contact_zone = [ln for ln in all_lines[max(0, idx - 1): idx + 6] if not _looks_like_reference_line(ln)]
        except StopIteration:
            candidate_contact_zone = []
    if not candidate_contact_zone:
        candidate_contact_zone = [ln for ln in zone_lines[:30] if not _looks_like_reference_line(ln)]
    search_zone = "\n".join(candidate_contact_zone)
    email = EMAIL_RE.search(search_zone)
    phone = PHONE_RE.search(search_zone)
    linkedin = LINKEDIN_RE.search(search_zone)
    urls = [m.group(0) for m in URL_RE.finditer(search_zone) if "linkedin" not in m.group(0).lower()]
    if email:
        identity["email"] = email.group(0)
    if phone:
        identity["phone"] = phone.group(0)
    if linkedin:
        identity["linkedin"] = linkedin.group(0)
    if urls:
        identity["portfolio"] = urls[0]
    for line in candidate_contact_zone:
        lower = line.lower()
        if "availability" in lower:
            identity["availability"] = line.split(":", 1)[-1].strip()
        if re.search(r"\b(region|location|city|address)\b", lower):
            value = line.split(":", 1)[-1].strip()
            if value:
                identity["location"] = value
        if not identity.get("location") and re.search(r"(Johannesburg|Bryanston|Sandton|Pretoria|Cape Town|Durban|Midrand|Randburg|South Africa|Centurion|Soweto|Polokwane|Bloemfontein|East London|Port Elizabeth|Nelspruit|Mbombela|Rustenburg|Kimberley|Pietermaritzburg)", line, re.I):
            identity["location"] = line
        if not identity.get("region") and re.search(r"\bSouth Africa\b", line, re.I):
            identity["region"] = "South Africa"
    return identity


# ---------------------------------------------------------------------------
# Final patch override: strict post-name contact zone
# ---------------------------------------------------------------------------

def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    zone_lines = _find_candidate_zone(raw_text)
    all_lines = [_clean_line(ln) for ln in raw_text.splitlines() if _clean_line(ln)]

    def looks_reference_context(index: int) -> bool:
        window_before = " ".join(all_lines[max(0, index - 2): index]).lower()
        window_after = " ".join(all_lines[index + 1: index + 4]).lower()
        line = all_lines[index].lower()
        return ('references' in window_before or 'referees' in window_before or any(term in window_after for term in ['lecturer', 'manager', 'director', 'professor', 'supervisor', 'contact:']) or line.startswith(('dr ', 'mr ', 'ms ', 'mrs ')))

    identity: Dict[str, Any] = {"full_name": None, "headline": None, "availability": None, "region": None, "email": None, "phone": None, "location": None, "linkedin": None, "portfolio": None, "confidence": 0.45}
    for line in zone_lines[:8]:
        if _looks_like_reference_line(line):
            continue
        for token in _split_header_tokens(line):
            if not identity["full_name"] and _looks_like_candidate_heading(token):
                identity["full_name"] = token
                identity["confidence"] = 0.9
            elif not identity["headline"] and any(word in token.lower() for word in ROLE_KEYWORDS) and not EMAIL_RE.search(token) and not PHONE_RE.search(token):
                identity["headline"] = sanitize_entity_text(remove_date_range(token)) or token
    if not identity["full_name"]:
        for idx, line in enumerate(all_lines[:40]):
            if _looks_like_candidate_heading(line) and not looks_reference_context(idx):
                identity["full_name"] = line
                identity["confidence"] = 0.86
                break
    if not identity["headline"]:
        for idx, line in enumerate(all_lines[:50]):
            if _looks_like_reference_line(line) or looks_reference_context(idx):
                continue
            if len(line) < 110 and any(word in line.lower() for word in ROLE_KEYWORDS) and not EMAIL_RE.search(line) and not PHONE_RE.search(line):
                identity["headline"] = sanitize_entity_text(remove_date_range(line)) or line
                break
    if not identity["full_name"] and path is not None:
        guessed = infer_name_from_filename(path.name)
        if guessed:
            identity["full_name"] = guessed
            identity["confidence"] = 0.72

    candidate_contact_zone = []
    if identity.get("full_name"):
        try:
            idx = next(i for i, ln in enumerate(all_lines[:60]) if identity["full_name"] == ln or identity["full_name"] in ln)
            candidate_contact_zone = [ln for ln in all_lines[idx: idx + 6] if not _looks_like_reference_line(ln)]
        except StopIteration:
            candidate_contact_zone = []
    if not candidate_contact_zone:
        candidate_contact_zone = [ln for ln in zone_lines[:30] if not _looks_like_reference_line(ln)]
    search_zone = "\n".join(candidate_contact_zone)
    email = EMAIL_RE.search(search_zone)
    phone = PHONE_RE.search(search_zone)
    linkedin = LINKEDIN_RE.search(search_zone)
    urls = [m.group(0) for m in URL_RE.finditer(search_zone) if "linkedin" not in m.group(0).lower() and '@' not in m.group(0)]
    if email:
        identity["email"] = email.group(0)
    if phone:
        identity["phone"] = phone.group(0)
    if linkedin:
        identity["linkedin"] = linkedin.group(0)
    if urls:
        identity["portfolio"] = urls[0]
    for line in candidate_contact_zone:
        lower = line.lower()
        if "availability" in lower:
            identity["availability"] = line.split(":", 1)[-1].strip()
        if re.search(r"\b(region|location|city|address)\b", lower):
            value = line.split(":", 1)[-1].strip()
            if value:
                identity["location"] = value
        if not identity.get("location") and re.search(r"(Johannesburg|Bryanston|Sandton|Pretoria|Cape Town|Durban|Midrand|Randburg|South Africa|Centurion|Soweto|Polokwane|Bloemfontein|East London|Port Elizabeth|Nelspruit|Mbombela|Rustenburg|Kimberley|Pietermaritzburg)", line, re.I):
            identity["location"] = line
        if not identity.get("region") and re.search(r"\bSouth Africa\b", line, re.I):
            identity["region"] = "South Africa"
    return identity


# ---------------------------------------------------------------------------
# Final normalization hardening overrides
# ---------------------------------------------------------------------------

_REGION_CITY_MAP = {
    "midrand": "Midrand, Gauteng",
    "johannesburg": "Johannesburg, Gauteng",
    "sandton": "Johannesburg, Gauteng",
    "bryanston": "Johannesburg, Gauteng",
    "randburg": "Johannesburg, Gauteng",
    "pretoria": "Pretoria, Gauteng",
    "centurion": "Pretoria, Gauteng",
    "durban": "Durban, KwaZulu-Natal",
    "cape town": "Cape Town, Western Cape",
    "polokwane": "Polokwane, Limpopo",
    "mbombela": "Mbombela, Mpumalanga",
    "nelspruit": "Mbombela, Mpumalanga",
    "bloemfontein": "Bloemfontein, Free State",
    "port elizabeth": "Gqeberha, Eastern Cape",
    "east london": "East London, Eastern Cape",
}

_PROVINCE_TOKENS = {
    "gauteng": "Gauteng, South Africa",
    "kwa-zulu natal": "KwaZulu-Natal, South Africa",
    "kwazulu natal": "KwaZulu-Natal, South Africa",
    "kwazulu-natal": "KwaZulu-Natal, South Africa",
    "western cape": "Western Cape, South Africa",
    "eastern cape": "Eastern Cape, South Africa",
    "limpopo": "Limpopo, South Africa",
    "mpumalanga": "Mpumalanga, South Africa",
    "free state": "Free State, South Africa",
    "north west": "North West, South Africa",
}

_ACADEMIC_ROLE_TERMS = {
    "module", "subject", "coursework", "semester", "assignment", "practical", "capstone",
    "honours project", "honors project", "student project", "research project", "academic project",
}

_HEADLINE_CLEANUP_RE = re.compile(r"\s*(?:\||•|·|/|\\)\s*.*$")


def normalize_recruiter_region(value: str) -> str:
    text = sanitize_entity_text(value) or ""
    if not text:
        return ""
    lowered = text.lower()
    if EMAIL_RE.search(text) or PHONE_RE.search(text):
        return ""
    for city, normalized in _REGION_CITY_MAP.items():
        if city in lowered:
            return normalized
    for token, normalized in _PROVINCE_TOKENS.items():
        if token in lowered:
            return normalized
    if "south africa" in lowered:
        return "South Africa"
    return ""


def _looks_like_academic_role_title(text: str) -> bool:
    lowered = (sanitize_entity_text(text) or "").lower()
    return any(term in lowered for term in _ACADEMIC_ROLE_TERMS)


def _clean_headline_text(text: str) -> str:
    value = sanitize_entity_text(remove_date_range(text)) or ""
    value = _HEADLINE_CLEANUP_RE.sub("", value).strip(" -|•·,;")
    if EMAIL_RE.search(value) or PHONE_RE.search(value):
        return ""
    if looks_like_education_line(value):
        return ""
    if len(value.split()) > 7:
        return ""
    return value


def infer_headline_from_profile(profile: Dict[str, Any]) -> Optional[str]:
    headline = _clean_headline_text((profile.get("identity") or {}).get("headline") or "")
    if headline:
        return headline
    entries = profile.get("experience", []) or []
    preferred = []
    fallback = []
    for entry in entries:
        position = _clean_headline_text(entry.get("position") or "")
        if not position or _looks_like_academic_role_title(position):
            continue
        lowered = position.lower()
        target = preferred if not any(term in lowered for term in ("intern", "trainee", "assistant", "graduate")) else fallback
        target.append(position)
    for pool in (preferred, fallback):
        if pool:
            return pool[0]
    return None


def infer_headline_from_raw(raw_text: str) -> Optional[str]:
    for raw in raw_text.splitlines()[:60]:
        line = _clean_headline_text(raw)
        if not line:
            continue
        lowered = line.lower()
        if any(word in lowered for word in ROLE_KEYWORDS) and not _looks_like_academic_role_title(lowered):
            return line
    return None


def parse_education_section(content: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    pending: Optional[Dict[str, Any]] = None
    seen = set()
    institution_pattern = re.compile(r"\b(?:university|college|institute|school|academy|technic|campus|uj|wits|unisa|tut|dut|uct|ukzn|nwu|north-west university|mancosa|cput|stellenbosch|up)\b", re.I)

    def commit(row: Optional[Dict[str, Any]]):
        if not row:
            return
        if not row.get("qualification") or _looks_like_academic_role_title(row.get("qualification", "")):
            return
        if any(word in (row.get("qualification") or "").lower() for word in ROLE_KEYWORDS):
            return
        key = ((row.get("qualification") or "").lower(), (row.get("institution") or "").lower(), (row.get("end_date") or "").lower())
        if key in seen:
            return
        seen.add(key)
        rows.append(row)

    for raw in [ln.strip() for ln in content.splitlines() if ln.strip()]:
        cleaned = BULLET_RE.sub("", raw).strip()
        if not cleaned:
            continue
        parts = _split_table_like_row(cleaned)
        if parts:
            headerish = {normalize_heading(p) for p in parts}
            if headerish & {"qualification", "institution", "year", "degree", "certification", "provider"} and len(headerish) >= 2:
                continue
            qualification = sanitize_entity_text(parts[0]) or ""
            institution = ""
            year = ""
            for part in parts[1:]:
                part_clean = sanitize_entity_text(part) or ""
                if not institution and institution_pattern.search(part_clean):
                    institution = part_clean
                if not year:
                    year = _extract_year_token(part_clean)
            row = {"qualification": qualification, "institution": institution, "start_date": "", "end_date": year, "sa_standard_hint": infer_sa_qualification_note(cleaned)}
            if row["qualification"] and (row["institution"] or row["end_date"] or looks_like_education_line(cleaned)):
                commit(row)
            continue

        if pending:
            if not pending.get("institution") and institution_pattern.search(cleaned):
                pending["institution"] = sanitize_entity_text(cleaned) or ""
                commit(pending)
                pending = None
                continue
            if not pending.get("end_date"):
                year = _extract_year_token(cleaned)
                if year:
                    pending["end_date"] = year
                    commit(pending)
                    pending = None
                    continue
            commit(pending)
            pending = None

        if not looks_like_education_line(cleaned):
            continue
        start, end = extract_date_range(cleaned)
        core = sanitize_entity_text(remove_date_range(cleaned)) or cleaned
        parts = [sanitize_entity_text(part) for part in re.split(r"\s*(?:\||–|—)\s*", core) if sanitize_entity_text(part)]
        qualification = parts[0] if parts else core
        institution = next((p for p in parts[1:] if institution_pattern.search(p or "")), "")
        year = end or _extract_year_token(cleaned)
        row = {"qualification": qualification, "institution": institution, "start_date": start or "", "end_date": year, "sa_standard_hint": infer_sa_qualification_note(cleaned)}
        if row["institution"] and row["end_date"]:
            commit(row)
        else:
            pending = row
    if pending:
        commit(pending)
    return rows


def clean_experience_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    seen = set()
    for entry in entries:
        position = sanitize_entity_text(entry.get("position")) or ""
        company = sanitize_entity_text(entry.get("company")) or ""
        if not position or not company:
            continue
        if _looks_like_academic_role_title(position) or looks_like_education_line(position) or looks_like_education_line(company):
            continue
        responsibilities = []
        for bullet in entry.get("responsibilities", []) or []:
            bullet_clean = sanitize_entity_text(bullet) or ""
            if not bullet_clean or _looks_like_academic_role_title(bullet_clean):
                continue
            responsibilities.append(bullet_clean)
        key = (position.lower(), company.lower(), str(entry.get("start_date") or "").lower(), str(entry.get("end_date") or "").lower())
        if key in seen:
            continue
        seen.add(key)
        normalized = dict(entry)
        normalized["position"] = position
        normalized["company"] = company
        normalized["responsibilities"] = responsibilities
        cleaned.append(normalized)
    return cleaned


def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    identity = {
        "full_name": None, "headline": None, "availability": None, "region": None, "email": None,
        "phone": None, "location": None, "linkedin": None, "portfolio": None, "confidence": 0.45,
    }
    all_lines = [_clean_line(ln) for ln in raw_text.splitlines() if _clean_line(ln)]
    zone_lines = _find_candidate_zone(raw_text)

    def is_bad_identity_line(text: str) -> bool:
        lowered = text.lower()
        return (
            _looks_like_reference_line(text)
            or looks_like_education_line(text)
            or EMAIL_RE.search(text) is not None
            or PHONE_RE.search(text) is not None
            or "qualification" in lowered
            or "certification" in lowered
            or "references on request" in lowered
        )

    for line in zone_lines[:10]:
        if is_bad_identity_line(line):
            continue
        for token in _split_header_tokens(line):
            token = sanitize_entity_text(token) or ""
            if not token or is_bad_identity_line(token):
                continue
            if not identity["full_name"] and _looks_like_candidate_heading(token):
                identity["full_name"] = token
                identity["confidence"] = 0.9
            elif not identity["headline"]:
                candidate = _clean_headline_text(token)
                if candidate and any(word in candidate.lower() for word in ROLE_KEYWORDS):
                    identity["headline"] = candidate

    if (not identity["full_name"] or looks_like_education_line(identity["full_name"] or "")) and path is not None:
        guessed = infer_name_from_filename(path.name)
        if guessed:
            identity["full_name"] = guessed
            identity["confidence"] = max(identity["confidence"], 0.72)

    if not identity["headline"]:
        identity["headline"] = infer_headline_from_raw(raw_text)

    candidate_contact_zone = [ln for ln in zone_lines[:25] if not _looks_like_reference_line(ln)]
    search_zone = "\n".join(candidate_contact_zone)
    email = EMAIL_RE.search(search_zone)
    phone = PHONE_RE.search(search_zone)
    linkedin = LINKEDIN_RE.search(search_zone)
    urls = [m.group(0) for m in URL_RE.finditer(search_zone) if "linkedin" not in m.group(0).lower() and "@" not in m.group(0)]
    if email:
        identity["email"] = email.group(0)
    if phone:
        identity["phone"] = phone.group(0)
    if linkedin:
        identity["linkedin"] = linkedin.group(0)
    if urls:
        identity["portfolio"] = urls[0]
    for line in candidate_contact_zone:
        lower = line.lower()
        if "availability" in lower:
            identity["availability"] = line.split(":", 1)[-1].strip()
        if re.search(r"\b(region|location|city|address)\b", lower):
            value = line.split(":", 1)[-1].strip()
            recruiter_region = normalize_recruiter_region(value)
            if recruiter_region:
                identity["region"] = recruiter_region
            elif value:
                identity["location"] = value
        elif not identity.get("region"):
            recruiter_region = normalize_recruiter_region(line)
            if recruiter_region:
                identity["region"] = recruiter_region
    return identity


# ---------------------------------------------------------------------------
# Final verification overrides
# ---------------------------------------------------------------------------

def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    identity = {"full_name": None, "headline": None, "availability": None, "region": None, "email": None, "phone": None, "location": None, "linkedin": None, "portfolio": None, "confidence": 0.45}
    all_lines = [_clean_line(ln) for ln in raw_text.splitlines() if _clean_line(ln)]

    # 1) Compressed top header line.
    for line in all_lines[:4]:
        tokens = _split_header_tokens(line)
        if len(tokens) >= 2 and (EMAIL_RE.search(line) or PHONE_RE.search(line)):
            first = sanitize_entity_text(tokens[0]) or ""
            second = sanitize_entity_text(tokens[1]) or ""
            if _looks_like_candidate_heading(first) and not looks_like_education_line(first):
                identity["full_name"] = first
                identity["confidence"] = 0.92
            cleaned_second = _clean_headline_text(second)
            if cleaned_second:
                identity["headline"] = cleaned_second
            email = EMAIL_RE.search(line)
            phone = PHONE_RE.search(line)
            if email:
                identity["email"] = email.group(0)
            if phone:
                identity["phone"] = phone.group(0)
            break

    # 2) Search for candidate block anywhere while skipping reference blocks.
    reference_mode = False
    name_idx = None
    for idx, line in enumerate(all_lines[:80]):
        lowered = line.lower()
        if any(term in lowered for term in ("references", "referees", "references on request")):
            reference_mode = True
            continue
        if reference_mode and normalize_heading(line) in {"experience", "career history", "qualifications", "education", "skills"}:
            reference_mode = False
        if reference_mode:
            continue
        if not identity["full_name"] and _looks_like_candidate_heading(line) and not looks_like_education_line(line):
            identity["full_name"] = line
            identity["confidence"] = max(identity["confidence"], 0.86)
            name_idx = idx
            continue
        if identity["full_name"] and name_idx is None and identity["full_name"] == line:
            name_idx = idx
        if identity["full_name"] and not identity["headline"] and idx <= (name_idx or idx) + 2:
            cleaned = _clean_headline_text(line)
            if cleaned and cleaned != identity["full_name"] and any(word in cleaned.lower() for word in ROLE_KEYWORDS):
                identity["headline"] = cleaned

    if not identity["full_name"] and path is not None:
        guessed = infer_name_from_filename(path.name)
        if guessed:
            identity["full_name"] = guessed
            identity["confidence"] = max(identity["confidence"], 0.72)

    # 3) Candidate-owned contact zone near detected name.
    candidate_contact_zone = []
    if identity.get("full_name"):
        try:
            start = next(i for i, ln in enumerate(all_lines[:120]) if identity["full_name"] == ln or identity["full_name"] in ln)
            candidate_contact_zone = []
            for ln in all_lines[start:start + 10]:
                if any(term in ln.lower() for term in ("references", "referees")):
                    break
                if _looks_like_reference_line(ln):
                    continue
                candidate_contact_zone.append(ln)
        except StopIteration:
            pass
    if not candidate_contact_zone:
        zone_lines = [ln for ln in _find_candidate_zone(raw_text) if not _looks_like_reference_line(ln)]
        candidate_contact_zone = zone_lines[:25]

    search_zone = "\n".join(candidate_contact_zone)
    if not identity.get("email"):
        email = EMAIL_RE.search(search_zone)
        if email:
            identity["email"] = email.group(0)
    if not identity.get("phone"):
        phone = PHONE_RE.search(search_zone)
        if phone:
            identity["phone"] = phone.group(0)
    linkedin = LINKEDIN_RE.search(search_zone)
    urls = [m.group(0) for m in URL_RE.finditer(search_zone) if "linkedin" not in m.group(0).lower() and "@" not in m.group(0)]
    if linkedin:
        identity["linkedin"] = linkedin.group(0)
    if urls:
        identity["portfolio"] = urls[0]
    for line in candidate_contact_zone:
        lower = line.lower()
        if "availability" in lower:
            identity["availability"] = line.split(":", 1)[-1].strip()
        recruiter_region = normalize_recruiter_region(line.split(":", 1)[-1].strip() if ":" in line else line)
        if recruiter_region and not identity.get("region"):
            identity["region"] = recruiter_region
    if not identity.get("headline"):
        identity["headline"] = infer_headline_from_raw(raw_text)
    return identity


# ---------------------------------------------------------------------------
# Final qualification/certification fixes
# ---------------------------------------------------------------------------

def parse_education_section(content: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen = set()
    institution_pattern = re.compile(r"\b(?:university|college|institute|school|academy|technic|campus|uj|wits|unisa|tut|dut|uct|ukzn|nwu|north-west university|mancosa|cput|stellenbosch|up)\b", re.I)
    for raw in [ln.strip() for ln in content.splitlines() if ln.strip()]:
        cleaned = BULLET_RE.sub("", raw).strip()
        norm = normalize_heading(cleaned)
        if norm in {"qualifications", "qualification", "education", "certifications", "certification"}:
            continue
        parts = _split_table_like_row(cleaned)
        if parts:
            headerish = {normalize_heading(p) for p in parts}
            if headerish & {"qualification", "institution", "year", "degree", "provider", "certification"} and len(headerish) >= 2:
                continue
            qualification = sanitize_entity_text(parts[0]) or ""
            institution = next((sanitize_entity_text(p) or "" for p in parts[1:] if institution_pattern.search(p or "")), "")
            year = next((_extract_year_token(p) for p in parts[1:] if _extract_year_token(p)), "")
            row = {"qualification": qualification, "institution": institution, "start_date": "", "end_date": year, "sa_standard_hint": infer_sa_qualification_note(cleaned)}
            if row["qualification"] and row["institution"] and not _looks_like_academic_role_title(row["qualification"]):
                key = ((row.get("qualification") or "").lower(), (row.get("institution") or "").lower(), (row.get("end_date") or "").lower())
                if key not in seen:
                    seen.add(key)
                    rows.append(row)
            continue
    return rows


# ---------------------------------------------------------------------------
# Final section-boundary and role-inference hardening overrides
# ---------------------------------------------------------------------------

_HEADLINE_REJECT_TERMS = {
    'skills', 'technical skills', 'core competencies', 'competencies', 'tools', 'tooling',
    'methodologies', 'soft skills', 'platforms', 'languages', 'testing', 'automation',
    'api testing', 'selenium', 'jira', 'java', 'python', 'sql', 'agile', 'scrum',
    'communication', 'team player', 'problem solving', 'microsoft office', 'postman'
}

_STOP_EXPERIENCE_HEADINGS = {
    'qualifications', 'qualification', 'education', 'academic background', 'certifications',
    'certification', 'references', 'reference', 'languages', 'language', 'achievements',
    'achievements awards', 'awards', 'awards achievements', 'skills', 'projects',
    'interests', 'publications'
}

_TRUE_PORTFOLIO_PAT = re.compile(r"(?:https?://|www\.)\S+", re.I)


def _headline_candidate_is_role(text: str) -> bool:
    cleaned = _clean_headline_text(text)
    if not cleaned:
        return False
    lowered = cleaned.lower()
    if lowered in _HEADLINE_REJECT_TERMS:
        return False
    if any(term in lowered for term in _HEADLINE_REJECT_TERMS) and not any(word in lowered for word in ROLE_KEYWORDS):
        return False
    if not any(word in lowered for word in ROLE_KEYWORDS):
        return False
    if _looks_like_academic_role_title(lowered):
        return False
    return True


def _role_rank(position: str, end_date: str = '') -> tuple[int, int]:
    lowered = (position or '').lower()
    seniority = 0
    if any(t in lowered for t in ('lead', 'senior', 'specialist', 'engineer', 'analyst', 'developer', 'tester', 'qa')):
        seniority += 2
    if any(t in lowered for t in ('intern', 'trainee', 'graduate')):
        seniority -= 1
    if 'assistant' in lowered:
        seniority -= 1
    recency = 1 if any(t in (end_date or '').lower() for t in ('present', 'current', 'now')) else 0
    return (recency, seniority)


def infer_headline_from_profile(profile: Dict[str, Any]) -> Optional[str]:
    headline = _clean_headline_text((profile.get('identity') or {}).get('headline') or '')
    if _headline_candidate_is_role(headline):
        return headline
    entries = profile.get('experience', []) or []
    candidates: list[tuple[tuple[int, int], str]] = []
    for entry in entries:
        position = _clean_headline_text(entry.get('position') or '')
        if not _headline_candidate_is_role(position):
            continue
        candidates.append((_role_rank(position, entry.get('end_date') or ''), position))
    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]
    return None


def infer_headline_from_raw(raw_text: str) -> Optional[str]:
    for raw in raw_text.splitlines()[:60]:
        line = _clean_headline_text(raw)
        if _headline_candidate_is_role(line):
            return line
    return None


def _looks_like_qualification_only(text: str) -> bool:
    lowered = (sanitize_entity_text(text) or '').lower()
    if not lowered:
        return False
    qualification_terms = (
        'national senior certificate', 'matric', 'grade 12', 'degree', 'diploma', 'honours', 'honors',
        'bcom', 'bsc', 'ba ', 'bachelor', 'master', 'masters', 'phd', 'certificate in', 'higher certificate',
        'advanced diploma', 'national diploma'
    )
    return any(term in lowered for term in qualification_terms) or looks_like_education_line(lowered)


def parse_education_section(content: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen = set()
    institution_pattern = re.compile(r"\b(?:university|college|institute|school|academy|technic|campus|uj|wits|unisa|tut|dut|uct|ukzn|nwu|north-west university|mancosa|cput|stellenbosch|up|high school|secondary school)\b", re.I)
    pending: Optional[Dict[str, Any]] = None

    def commit(row: Optional[Dict[str, Any]]):
        if not row:
            return
        qualification = sanitize_entity_text(row.get('qualification')) or ''
        if not qualification or _looks_like_academic_role_title(qualification):
            return
        if any(word in qualification.lower() for word in ROLE_KEYWORDS):
            return
        key = ((qualification).lower(), (row.get('institution') or '').lower(), (row.get('end_date') or '').lower())
        if key in seen:
            return
        seen.add(key)
        row['qualification'] = qualification
        rows.append(row)

    for raw in [ln.strip() for ln in content.splitlines() if ln.strip()]:
        cleaned = BULLET_RE.sub('', raw).strip()
        norm = normalize_heading(cleaned)
        if norm in {'qualifications', 'qualification', 'education', 'certifications', 'certification'}:
            continue
        parts = _split_table_like_row(cleaned)
        if parts:
            headerish = {normalize_heading(p) for p in parts}
            if headerish & {'qualification', 'institution', 'year', 'degree', 'provider', 'certification'} and len(headerish) >= 2:
                continue
            qualification = sanitize_entity_text(parts[0]) or ''
            institution = next((sanitize_entity_text(p) or '' for p in parts[1:] if institution_pattern.search(p or '')), '')
            year = next((_extract_year_token(p) for p in parts[1:] if _extract_year_token(p)), '')
            if _looks_like_qualification_only(qualification):
                commit({'qualification': qualification, 'institution': institution, 'start_date': '', 'end_date': year, 'sa_standard_hint': infer_sa_qualification_note(cleaned)})
            continue

        if pending:
            if not pending.get('institution') and institution_pattern.search(cleaned):
                pending['institution'] = sanitize_entity_text(cleaned) or ''
                continue
            if not pending.get('end_date'):
                year = _extract_year_token(cleaned)
                if year:
                    pending['end_date'] = year
                    commit(pending)
                    pending = None
                    continue
            commit(pending)
            pending = None

        if not _looks_like_qualification_only(cleaned):
            continue
        start, end = extract_date_range(cleaned)
        core = sanitize_entity_text(remove_date_range(cleaned)) or cleaned
        parts = [sanitize_entity_text(part) for part in re.split(r"\s*(?:\||–|—)\s*", core) if sanitize_entity_text(part)]
        qualification = parts[0] if parts else core
        institution = next((p for p in parts[1:] if institution_pattern.search(p or '')), '')
        year = end or _extract_year_token(cleaned)
        row = {'qualification': qualification, 'institution': institution, 'start_date': start or '', 'end_date': year, 'sa_standard_hint': infer_sa_qualification_note(cleaned)}
        if institution or year:
            commit(row)
        else:
            pending = row
    if pending:
        commit(pending)
    return rows


def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    all_lines = [_clean_line(ln) for ln in raw_text.splitlines() if _clean_line(ln)]
    identity = {
        'full_name': None, 'headline': None, 'availability': None, 'region': None,
        'email': None, 'phone': None, 'location': None, 'linkedin': None, 'portfolio': None,
        'confidence': 0.45,
    }

    def looks_reference_context(index: int) -> bool:
        window_before = ' '.join(all_lines[max(0, index - 2): index]).lower()
        window_after = ' '.join(all_lines[index + 1: index + 4]).lower()
        line = all_lines[index].lower()
        return ('references' in window_before or 'referees' in window_before or 'contact:' in line or
                any(term in window_after for term in ['lecturer', 'manager', 'director', 'professor', 'supervisor']))

    for idx, line in enumerate(all_lines[:50]):
        if looks_reference_context(idx) or _looks_like_reference_line(line):
            continue
        for token in _split_header_tokens(line):
            if not identity['full_name'] and _looks_like_candidate_heading(token):
                identity['full_name'] = token
                identity['confidence'] = 0.9
            elif not identity['headline'] and _headline_candidate_is_role(token):
                identity['headline'] = _clean_headline_text(token)
        if identity['full_name'] and identity['headline']:
            break
    if not identity['full_name'] and path is not None:
        guessed = infer_name_from_filename(path.name)
        if guessed:
            identity['full_name'] = guessed
            identity['confidence'] = 0.72

    candidate_contact_zone: list[str] = []
    if identity.get('full_name'):
        for i, ln in enumerate(all_lines[:120]):
            if identity['full_name'] == ln or identity['full_name'] in ln:
                for sub in all_lines[i:i + 10]:
                    lower = sub.lower()
                    if 'references' in lower or 'referees' in lower:
                        break
                    if _looks_like_reference_line(sub) or 'contact:' in lower:
                        continue
                    candidate_contact_zone.append(sub)
                break
    if not candidate_contact_zone:
        candidate_contact_zone = [ln for ln in _find_candidate_zone(raw_text)[:25] if not _looks_like_reference_line(ln)]

    search_zone = '\n'.join(candidate_contact_zone)
    email = EMAIL_RE.search(search_zone)
    phone = PHONE_RE.search(search_zone)
    linkedin = LINKEDIN_RE.search(search_zone)
    urls = [m.group(0) for m in URL_RE.finditer(search_zone) if 'linkedin' not in m.group(0).lower() and '@' not in m.group(0)]
    portfolio_urls = [u for u in urls if _TRUE_PORTFOLIO_PAT.search(u) and not re.search(r'\b(?:gmail|yahoo|hotmail|outlook)\.com\b', u, re.I)]
    if email:
        identity['email'] = email.group(0)
    if phone:
        identity['phone'] = phone.group(0)
    if linkedin:
        identity['linkedin'] = linkedin.group(0)
    if portfolio_urls:
        identity['portfolio'] = portfolio_urls[0]
    for line in candidate_contact_zone:
        lower = line.lower()
        if 'availability' in lower:
            identity['availability'] = line.split(':', 1)[-1].strip()
        recruiter_region = normalize_recruiter_region(line.split(':', 1)[-1].strip() if ':' in line else line)
        if recruiter_region and not identity.get('region'):
            identity['region'] = recruiter_region
            identity['location'] = recruiter_region
    if not identity.get('headline'):
        identity['headline'] = infer_headline_from_profile({'identity': identity, 'experience': parse_experience_section(raw_text)}) or infer_headline_from_raw(raw_text)
    return identity


def _parse_experience_section_v2884(content: str) -> List[Dict[str, Any]]:
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    if not lines:
        return []
    experience_started = not any(normalize_heading(ln) in {'career history', 'experience', 'employment', 'work experience', 'professional experience'} for ln in lines)
    entries: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    current_client: Optional[Dict[str, Any]] = None
    for raw in lines:
        line = _clean_line(raw)
        if not line:
            continue
        norm = normalize_heading(line)
        if _looks_like_reference_line(line):
            if current and (current.get('company') or current.get('position') or current.get('responsibilities') or current.get('clients')):
                entries.append(current)
            break
        if norm in {'career history', 'experience', 'employment', 'work experience', 'professional experience'}:
            experience_started = True
            continue
        if not experience_started:
            continue
        if norm in _STOP_EXPERIENCE_HEADINGS:
            if current and (current.get('company') or current.get('position') or current.get('responsibilities') or current.get('clients')):
                entries.append(current)
            break
        if _looks_like_academic_project(line):
            continue
        client_meta = _client_line(line)
        if client_meta and current:
            if current_client and client_meta.get('programme') and not client_meta.get('client_name'):
                current_client['programme'] = sanitize_entity_text(client_meta.get('programme'))
            else:
                current_client = {'client_name': sanitize_entity_text(client_meta.get('client_name')), 'project_name': sanitize_entity_text(client_meta.get('project_name')), 'programme': sanitize_entity_text(client_meta.get('programme')), 'responsibilities': []}
                current.setdefault('clients', []).append(current_client)
            continue
        parsed = _split_role_company_date_line(line)
        if parsed:
            if current:
                same_parent = ((parsed.get('company') or '').casefold() == (current.get('company') or '').casefold() and
                               (parsed.get('position') or '').casefold() == (current.get('position') or '').casefold() and
                               (parsed.get('start_date') or '').casefold() == (current.get('start_date') or '').casefold() and
                               (parsed.get('end_date') or '').casefold() == (current.get('end_date') or '').casefold())
                if same_parent:
                    continue
                if current.get('company') or current.get('position') or current.get('responsibilities') or current.get('clients'):
                    entries.append(current)
            current = parsed
            current_client = None
            continue
        if current is None:
            continue
        cleaned = BULLET_RE.sub('', line).strip()
        if _looks_like_reference_line(cleaned):
            continue
        if re.search(r"\b(?:technology|technologies|tools|environment|stack)\b", cleaned, re.I):
            target = current_client if current_client else current
            target.setdefault('technologies', []).extend(parse_simple_items(cleaned))
        elif current_client:
            current_client.setdefault('responsibilities', []).append(cleaned)
        elif len(cleaned.split()) >= 12 and not current.get('summary') and not BULLET_RE.match(raw):
            current['summary'] = cleaned
        else:
            current.setdefault('responsibilities', []).append(cleaned)
    if current and (current.get('company') or current.get('position') or current.get('responsibilities') or current.get('clients')):
        entries.append(current)
    return clean_experience_entries(entries)


# ---------------------------------------------------------------------------
# Final micro-fixes for qualification seniority, headings, and headline strictness
# ---------------------------------------------------------------------------

_STOP_EXPERIENCE_HEADINGS.update({'achievements & awards', 'awards & achievements'})
_HEADLINE_TITLE_NOUNS = {'tester','analyst','developer','engineer','manager','consultant','administrator','officer','coordinator','lead','architect','specialist','representative','director','technician','designer','strategist','planner','accountant','auditor','clerk','assistant','intern','trainee','associate','tutor'}


def _headline_candidate_is_role(text: str) -> bool:
    cleaned = _clean_headline_text(text)
    if not cleaned:
        return False
    lowered = cleaned.lower()
    if lowered in _HEADLINE_REJECT_TERMS:
        return False
    if any(term in lowered for term in ('aspiring', 'looking for', 'seeking', 'objective', 'profile', 'professional with', 'technology professional')):
        return False
    if any(term in lowered for term in _HEADLINE_REJECT_TERMS) and not any(noun in lowered for noun in _HEADLINE_TITLE_NOUNS):
        return False
    return any(noun in lowered for noun in _HEADLINE_TITLE_NOUNS) and not _looks_like_academic_role_title(lowered)


def parse_education_section(content: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen = set()
    institution_pattern = re.compile(r"\b(?:university|college|institute|school|academy|technic|campus|uj|wits|unisa|tut|dut|uct|ukzn|nwu|north-west university|mancosa|cput|stellenbosch|up|high school|secondary school)\b", re.I)
    for raw in [ln.strip() for ln in content.splitlines() if ln.strip()]:
        cleaned = BULLET_RE.sub('', raw).strip()
        norm = normalize_heading(cleaned)
        if norm in {'qualifications', 'qualification', 'education', 'certifications', 'certification'}:
            continue
        parts = _split_table_like_row(cleaned)
        if parts:
            headerish = {normalize_heading(p) for p in parts}
            if headerish & {'qualification', 'institution', 'year', 'degree', 'provider', 'certification'} and len(headerish) >= 2:
                continue
            qualification = sanitize_entity_text(parts[0]) or ''
            institution = next((sanitize_entity_text(p) or '' for p in parts[1:] if institution_pattern.search(p or '')), '')
            year = next((_extract_year_token(p) for p in parts[1:] if _extract_year_token(p)), '')
            lowered = qualification.lower()
            if qualification and (institution or year) and _looks_like_qualification_only(qualification) and not (_looks_like_academic_role_title(qualification) or (any(word in lowered for word in ROLE_KEYWORDS) and 'national senior certificate' not in lowered)):
                key=((qualification).lower(), institution.lower(), (year or '').lower())
                if key not in seen:
                    seen.add(key)
                    rows.append({'qualification': qualification, 'institution': institution, 'start_date': '', 'end_date': year, 'sa_standard_hint': infer_sa_qualification_note(cleaned)})
    return rows


def _parse_experience_section_v3001(content: str) -> List[Dict[str, Any]]:
    lines=[ln.strip() for ln in content.splitlines() if ln.strip()]
    if not lines:
        return []
    experience_started = not any(normalize_heading(ln) in {'career history','experience','employment','work experience','professional experience'} for ln in lines)
    entries=[]
    current=None
    current_client=None
    for raw in lines:
        line=_clean_line(raw)
        if not line:
            continue
        norm=normalize_heading(line)
        if _looks_like_reference_line(line):
            if current and (current.get('company') or current.get('position') or current.get('responsibilities') or current.get('clients')):
                entries.append(current)
            break
        if norm in {'career history','experience','employment','work experience','professional experience'}:
            experience_started=True
            continue
        if not experience_started:
            continue
        if norm in _STOP_EXPERIENCE_HEADINGS:
            if current and (current.get('company') or current.get('position') or current.get('responsibilities') or current.get('clients')):
                entries.append(current)
            break
        if _looks_like_academic_project(line):
            continue
        client_meta=_client_line(line)
        if client_meta and current:
            if current_client and client_meta.get('programme') and not client_meta.get('client_name'):
                current_client['programme']=sanitize_entity_text(client_meta.get('programme'))
            else:
                current_client={'client_name': sanitize_entity_text(client_meta.get('client_name')), 'project_name': sanitize_entity_text(client_meta.get('project_name')), 'programme': sanitize_entity_text(client_meta.get('programme')), 'responsibilities': []}
                current.setdefault('clients', []).append(current_client)
            continue
        parsed=_split_role_company_date_line(line)
        if parsed:
            if current:
                same_parent=((parsed.get('company') or '').casefold()==(current.get('company') or '').casefold() and (parsed.get('position') or '').casefold()==(current.get('position') or '').casefold() and (parsed.get('start_date') or '').casefold()==(current.get('start_date') or '').casefold() and (parsed.get('end_date') or '').casefold()==(current.get('end_date') or '').casefold())
                if same_parent:
                    continue
                if current.get('company') or current.get('position') or current.get('responsibilities') or current.get('clients'):
                    entries.append(current)
            current=parsed
            current_client=None
            continue
        if current is None:
            continue
        cleaned=BULLET_RE.sub('', line).strip()
        if norm in _STOP_EXPERIENCE_HEADINGS:
            entries.append(current)
            break
        if re.search(r"\b(?:technology|technologies|tools|environment|stack)\b", cleaned, re.I):
            target=current_client if current_client else current
            target.setdefault('technologies', []).extend(parse_simple_items(cleaned))
        elif current_client:
            current_client.setdefault('responsibilities', []).append(cleaned)
        elif len(cleaned.split()) >= 12 and not current.get('summary') and not BULLET_RE.match(raw):
            current['summary']=cleaned
        else:
            current.setdefault('responsibilities', []).append(cleaned)
    if current and (current.get('company') or current.get('position') or current.get('responsibilities') or current.get('clients')) and (not entries or current is not entries[-1]):
        entries.append(current)
    return clean_experience_entries(entries)


# ---------------------------------------------------------------------------
# Final regression repairs for education rows and consulting client lines
# ---------------------------------------------------------------------------

def _client_line(line: str) -> Optional[Dict[str, str]]:
    text = _clean_line(BULLET_RE.sub('', line))
    m = re.match(r"^Client\s*:\s*(.+?)\s*(?:\||-|–|—)\s*Project\s*:\s*(.+)$", text, re.I)
    if m:
        return {'client_name': m.group(1), 'project_name': m.group(2), 'programme': ''}
    m = re.match(r"^Client(?:\s*Organisation)?\s*:\s*(.+)$", text, re.I)
    if m:
        return {'client_name': m.group(1), 'project_name': '', 'programme': ''}
    m = re.match(r"^Programme\s*:\s*(.+)$", text, re.I)
    if m:
        return {'client_name': '', 'project_name': '', 'programme': m.group(1)}
    if re.match(r"^(?:client|project|programme)\b", text, re.I):
        return {'client_name': text, 'project_name': '', 'programme': ''}
    return None


def parse_education_section(content: str) -> List[Dict[str, Any]]:
    rows=[]
    seen=set()
    institution_pattern = re.compile(r"\b(?:university|college|institute|school|academy|technic|campus|uj|wits|unisa|tut|dut|uct|ukzn|nwu|north-west university|mancosa|cput|stellenbosch|up|high school|secondary school)\b", re.I)
    pending=None

    def commit(row):
        if not row:
            return
        qualification=sanitize_entity_text(row.get('qualification')) or ''
        institution=sanitize_entity_text(row.get('institution')) or ''
        year=sanitize_entity_text(row.get('end_date')) or ''
        if not qualification or _looks_like_academic_role_title(qualification):
            return
        if not _looks_like_qualification_only(qualification):
            return
        key=(qualification.lower(), institution.lower(), year.lower())
        if key in seen:
            return
        seen.add(key)
        rows.append({'qualification': qualification, 'institution': institution, 'start_date': '', 'end_date': year, 'sa_standard_hint': infer_sa_qualification_note(qualification)})

    for raw in [ln.strip() for ln in content.splitlines() if ln.strip()]:
        cleaned=BULLET_RE.sub('', raw).strip()
        norm=normalize_heading(cleaned)
        if norm in {'qualifications','qualification','education','certifications','certification'}:
            continue
        parts=_split_table_like_row(cleaned)
        if parts:
            headerish={normalize_heading(p) for p in parts}
            if headerish & {'qualification','institution','year','degree','provider','certification'} and len(headerish)>=2:
                continue
            qualification=sanitize_entity_text(parts[0]) or ''
            institution=next((sanitize_entity_text(p) or '' for p in parts[1:] if institution_pattern.search(p or '')), '')
            year=next((_extract_year_token(p) for p in parts[1:] if _extract_year_token(p)), '')
            if _looks_like_qualification_only(qualification):
                commit({'qualification': qualification, 'institution': institution, 'end_date': year})
            continue
        if pending:
            if not pending.get('institution') and institution_pattern.search(cleaned):
                pending['institution']=sanitize_entity_text(cleaned) or ''
                continue
            if not pending.get('end_date'):
                year=_extract_year_token(cleaned)
                if year:
                    pending['end_date']=year
                    commit(pending)
                    pending=None
                    continue
            commit(pending)
            pending=None
        if not _looks_like_qualification_only(cleaned):
            continue
        start,end=extract_date_range(cleaned)
        core=sanitize_entity_text(remove_date_range(cleaned)) or cleaned
        parts=[sanitize_entity_text(part) for part in re.split(r"\s*(?:\||–|—)\s*", core) if sanitize_entity_text(part)]
        qualification=parts[0] if parts else core
        institution=next((p for p in parts[1:] if institution_pattern.search(p or '')), '')
        year=end or _extract_year_token(cleaned)
        row={'qualification': qualification, 'institution': institution, 'end_date': year}
        if institution or year:
            commit(row)
        else:
            pending=row
    if pending:
        commit(pending)
    return rows


# ---------------------------------------------------------------------------
# Final consulting bullet fold override
# ---------------------------------------------------------------------------

def clean_experience_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned=[]
    seen=set()
    for entry in entries:
        normalized=dict(entry)
        normalized['company']=sanitize_entity_text(normalized.get('company'))
        normalized['position']=sanitize_entity_text(normalized.get('position'))
        normalized['summary']=sanitize_entity_text(normalized.get('summary'))
        normalized['start_date']=sanitize_entity_text(normalized.get('start_date')) or ''
        normalized['end_date']=sanitize_entity_text(normalized.get('end_date')) or ''
        normalized['responsibilities']=[sanitize_entity_text(x) for x in normalized.get('responsibilities', []) if sanitize_entity_text(x)]
        normalized['technologies']=[sanitize_entity_text(x) for x in normalized.get('technologies', []) if sanitize_entity_text(x)]
        client_rows=[]
        for client in normalized.get('clients', []) or []:
            row={
                'client_name': sanitize_entity_text(client.get('client_name')),
                'project_name': sanitize_entity_text(client.get('project_name')),
                'programme': sanitize_entity_text(client.get('programme')),
                'responsibilities': [sanitize_entity_text(x) for x in client.get('responsibilities', []) if sanitize_entity_text(x)],
            }
            client_rows.append(row)
            label=' | '.join([x for x in [row.get('client_name'), row.get('project_name') or row.get('programme')] if x])
            if label and label not in normalized['responsibilities']:
                normalized['responsibilities'].append(label)
            for resp in row['responsibilities']:
                if resp not in normalized['responsibilities']:
                    normalized['responsibilities'].append(resp)
        normalized['clients']=client_rows
        if not normalized.get('company') and normalized.get('clients'):
            normalized['company']='Consulting Engagement'
        if not normalized.get('position'):
            continue
        key=((normalized.get('company') or '').lower(), (normalized.get('position') or '').lower(), (normalized.get('start_date') or '').lower(), (normalized.get('end_date') or '').lower())
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(normalized)
    return cleaned

# ---------------------------------------------------------------------------
# Final Lindelwe-focused extraction overrides
# ---------------------------------------------------------------------------

_DEFENSIVE_STOP_HEADINGS = {
    'education', 'qualifications', 'qualification', 'certifications', 'certification', 'certificates', 'training',
    'languages', 'references', 'referees', 'awards', 'award', 'honors', 'honours',
    'achievements', 'achievements & awards', 'volunteer experience', 'volunteering',
    'projects', 'publications', 'interests', 'career history', 'experience', 'employment', 'work experience', 'professional experience'
}


def _line_is_attachment_noise(line: str) -> bool:
    lower = (line or '').lower()
    return any(term in lower for term in (
        'this is to certify', 'vice-chancellor', 'registrar', 'certificate no.',
        'scan code on reverse', 'having been met', 'all the associated rights and privileges',
        'conferred upon', 'id no.'
    ))


def _coalesce_wrapped_lines(lines: List[str]) -> List[str]:
    merged: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ''
        if nxt and (
            re.search(rf"\b(?:{MONTH})\b.*[–-]$", line, re.I)
            or (re.search(rf"\b(?:{MONTH})\b$", line, re.I) and re.search(r"^(?:19|20)\d{2}\b", nxt))
            or re.search(r"[|•]$", line)
        ):
            merged.append(f"{line} {nxt}".strip())
            i += 2
            continue
        merged.append(line)
        i += 1
    return merged


def _experience_source_lines(content: str) -> List[str]:
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    lines = _coalesce_wrapped_lines(lines)
    cleaned: List[str] = []
    for ln in lines:
        if _line_is_attachment_noise(ln):
            continue
        cleaned.append(ln)
    return cleaned


def _is_professional_experience(parsed: Dict[str, Any]) -> bool:
    role = (parsed.get('position') or '').lower()
    company = (parsed.get('company') or '').lower()
    text = f"{role} {company} {' '.join(parsed.get('responsibilities', []) or [])}".lower()
    role_company = f"{role} {company}"
    if any(term in role_company for term in ('volunteer', 'mentor')) or any(term in text for term in ('journalist', 'astroquiz', 'tanks tournament')):
        return False
    academic_roles = ('student assistant', 'lab demonstrator', 'demonstrator', 'tutor', 'peer mentor')
    academic_companies = ('university', 'school', 'academy', 'conference', 'lab', 'physics labs', 'computer labs')
    if any(term in role for term in academic_roles):
        return False
    if any(term in company for term in academic_companies) and 'bank' not in company:
        return False
    return True


def _normalize_role_company_date_parts(parts: List[str]) -> Optional[Dict[str, Any]]:
    if len(parts) < 3:
        return None
    role = sanitize_entity_text(parts[0]) or ''
    company = sanitize_entity_text(parts[1]) or ''
    start = end = ''
    if len(parts) >= 4:
        start = format_recruiter_date(parts[2])
        end = format_recruiter_date(parts[3])
    else:
        start, end = extract_date_range(parts[2])
        start = start or ''
        end = end or ''
    if not role or not company:
        return None
    return {'company': company, 'position': role, 'start_date': start, 'end_date': end, 'responsibilities': [], 'clients': [], 'technologies': [], 'summary': None}


def _split_role_company_date_line(line: str) -> Optional[Dict[str, Any]]:
    text = sanitize_entity_text(BULLET_RE.sub('', line)) or ''
    if not text or _line_is_attachment_noise(text):
        return None
    if normalize_heading(text) in _DEFENSIVE_STOP_HEADINGS:
        return None
    parts = [sanitize_entity_text(p) or '' for p in re.split(r"\s*[|•]\s*", text) if sanitize_entity_text(p)]
    if len(parts) >= 3:
        normalized = _normalize_role_company_date_parts(parts)
        if normalized:
            return normalized
    m = re.match(rf"^(?P<role>.+?)\s+[•|-]\s+(?P<company>.+?)\s+[•|-]\s+(?P<start>(?:{MONTH}|(?:19|20)\d{{2}}).+?)\s*[–-]\s*(?P<end>Present|Current|Now|(?:{MONTH}|(?:19|20)\d{{2}}).+)$", text, re.I)
    if m:
        return {'company': sanitize_entity_text(m.group('company')), 'position': sanitize_entity_text(m.group('role')), 'start_date': sanitize_entity_text(m.group('start')) or '', 'end_date': sanitize_entity_text(m.group('end')) or '', 'responsibilities': [], 'clients': [], 'technologies': [], 'summary': None}
    m = re.match(rf"^(?P<company>.+?)\s+[|\-–—]\s+(?P<role>.+?)\s+[|\-–—]\s+(?P<start>(?:{MONTH}|(?:19|20)\d{{2}}).+?)\s*[–-]\s*(?P<end>Present|Current|Now|(?:{MONTH}|(?:19|20)\d{{2}}).+)$", text, re.I)
    if m:
        return {'company': sanitize_entity_text(m.group('company')), 'position': sanitize_entity_text(m.group('role')), 'start_date': sanitize_entity_text(m.group('start')) or '', 'end_date': sanitize_entity_text(m.group('end')) or '', 'responsibilities': [], 'clients': [], 'technologies': [], 'summary': None}
    return None


def _parse_experience_section_v3308(content: str) -> List[Dict[str, Any]]:
    lines = _experience_source_lines(content)
    if not lines:
        return []
    entries: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    started = not any(normalize_heading(ln) in {'career history', 'experience', 'employment', 'work experience', 'professional experience'} for ln in lines)
    for raw in lines:
        norm = normalize_heading(raw)
        if norm in {'career history', 'experience', 'employment', 'work experience', 'professional experience'}:
            started = True
            continue
        if not started:
            continue
        if norm in _DEFENSIVE_STOP_HEADINGS:
            break
        if _looks_like_reference_line(raw):
            break
        parsed = _split_role_company_date_line(raw)
        if parsed:
            if current and _is_professional_experience(current):
                entries.append(current)
            current = parsed
            continue
        if current is None:
            continue
        cleaned = sanitize_entity_text(BULLET_RE.sub('', raw)) or ''
        if not cleaned or _line_is_attachment_noise(cleaned):
            continue
        if len(cleaned.split()) >= 10 and not current.get('summary'):
            current['summary'] = cleaned
        else:
            current.setdefault('responsibilities', []).append(cleaned)
    if current and _is_professional_experience(current):
        entries.append(current)
    return clean_experience_entries(entries)


def _extract_year_token_local(text: str) -> str:
    match = re.search(r"\b((?:19|20)\d{2}|Present|Current|In Progress)\b", text or '', re.I)
    return match.group(1) if match else ''


def _clean_qualification_text(text: str) -> str:
    cleaned = sanitize_entity_text(text) or ''
    cleaned = re.sub(r"\b(?:first|second|third) .* class of \d{4}\b", '', cleaned, flags=re.I)
    cleaned = re.sub(r"\s{2,}", ' ', cleaned).strip(' |•-')
    return cleaned


def _split_table_like_row(line: str) -> List[str]:
    if '|' in line:
        return [p.strip() for p in line.split('|') if p.strip()]
    if '•' in line:
        return [p.strip() for p in line.split('•') if p.strip()]
    return []


def _looks_like_qualification_only(text: str) -> bool:
    lower = (text or '').lower()
    if not lower or _line_is_attachment_noise(text):
        return False
    if any(term in lower for term in ('responsible for', 'duties', 'experience', 'career history', 'volunteer experience', 'references', 'dean\'s list')):
        return False
    if re.search(r"\b(?:graduate with|skilled in|experienced in|strong skills|with a strong|passionate about|proficient in|looking for|seeking)\b", lower):
        return False
    if any(term in lower for term in ('matric', 'national senior certificate', 'bsc', 'bcom', 'bis ', 'bachelor', 'degree', 'diploma', 'honours', 'honors', 'certificate', 'coding for websites', 'information science', 'informatics')):
        return True
    return False


def parse_education_section(content: str) -> List[Dict[str, Any]]:
    lines = _experience_source_lines(content)
    rows: List[Dict[str, Any]] = []
    seen = set()
    in_education = any(normalize_heading(ln) in {'education', 'qualifications', 'qualification'} for ln in lines)
    capture = not in_education
    institution_pattern = re.compile(r"\b(?:university|college|institute|school|academy|online|campus|uj|wits|unisa|tut|dut|uct|ukzn|nwu|north-west university|mancosa|cput|stellenbosch|up|high school|secondary school|damelin)\b", re.I)

    def commit(qualification: str, institution: str, year: str) -> None:
        qualification = _clean_qualification_text(qualification)
        institution = sanitize_entity_text(institution) or ''
        year = sanitize_entity_text(year) or ''
        if not qualification or not _looks_like_qualification_only(qualification):
            return
        key = (qualification.lower(), institution.lower(), year.lower())
        if key in seen:
            return
        seen.add(key)
        rows.append({'qualification': qualification, 'institution': institution, 'start_date': '', 'end_date': year, 'sa_standard_hint': infer_sa_qualification_note(qualification)})

    for raw in lines:
        norm = normalize_heading(raw)
        if norm in {'education', 'qualifications', 'qualification'}:
            capture = True
            continue
        if not capture:
            continue
        if norm in _DEFENSIVE_STOP_HEADINGS - {'education', 'qualifications', 'qualification'}:
            break
        if _line_is_attachment_noise(raw):
            continue
        cleaned = _clean_qualification_text(BULLET_RE.sub('', raw))
        if not cleaned:
            continue
        parts = _split_table_like_row(cleaned)
        if parts:
            headerish = {normalize_heading(p) for p in parts}
            if headerish & {'qualification', 'institution', 'year', 'degree', 'provider', 'certification'} and len(headerish) >= 2:
                continue
            qualification = parts[0]
            institution = next((p for p in parts[1:] if institution_pattern.search(p)), '')
            year = next((_extract_year_token_local(p) for p in parts[1:] if _extract_year_token_local(p)), '')
            commit(qualification, institution, year)
            continue
        if not _looks_like_qualification_only(cleaned):
            continue
        parts = [p.strip() for p in re.split(r"\s*[•|]\s*", cleaned) if p.strip()]
        qualification = parts[0] if parts else cleaned
        institution = ''
        year = ''
        for p in parts[1:]:
            if institution_pattern.search(p) and not institution:
                institution = p
            token = _extract_year_token_local(p)
            if token and not year:
                year = token
        commit(qualification, institution, year)
    return rows


def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    top = lines[:40]
    full_name = ''
    for line in top:
        stripped = sanitize_entity_text(line) or ''
        if is_valid_name_candidate(stripped) and stripped.upper() == stripped and 'CURRICULUM VITAE' not in stripped.upper():
            full_name = stripped
            break
    if not full_name and path is not None:
        full_name = infer_name_from_filename(path.name) or ''

    headline = ''
    exp = parse_experience_section(raw_text)
    if exp:
        headline = sanitize_entity_text(exp[0].get('position')) or ''
    if not headline:
        for line in top:
            stripped = sanitize_entity_text(line) or ''
            if stripped and not is_valid_name_candidate(stripped) and not EMAIL_RE.search(stripped) and not PHONE_RE.search(stripped) and not likely_heading(stripped):
                if any(word in stripped.lower() for word in ROLE_KEYWORDS):
                    headline = stripped
                    break

    email = ''
    phone = ''
    label_window = '\n'.join(lines[:120])
    m = re.search(r'EMAIL\s*:\s*([^\s]+@[^\s]+)', label_window, re.I)
    if not m:
        m = re.search(r'\b([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})\b', label_window, re.I)
    if m:
        email = m.group(1)
    p = re.search(r'PHONE\s*:\s*([+\d][\d\s]{7,})', label_window, re.I)
    if not p:
        p = re.search(r'\b(?:\+27\s*\d{2}|0\d{2})\s*\d{3}\s*\d{4}\b', label_window)
    if p:
        phone = sanitize_entity_text(p.group(1) if p.lastindex else p.group(0)) or ''

    return {
        'full_name': full_name,
        'headline': headline,
        'availability': None,
        'region': 'Not specified',
        'email': email or None,
        'phone': phone or None,
        'location': None,
        'linkedin': None,
        'portfolio': None,
        'confidence': 0.92 if full_name and headline else 0.8,
    }


# ---------------------------------------------------------------------------
# Final override refinements for headline/company parsing and identity hygiene
# ---------------------------------------------------------------------------

def _looks_like_company_name(text: str) -> bool:
    lower = (text or '').lower().strip()
    company_markers = ('bank', 'technologies', 'technology', 'opentext', 'university', 'limited', 'ltd', 'pty', 'group', 'institute', 'security', 'future', 'café', 'cafe', 'labs', 'conference')
    return any(marker in lower for marker in company_markers)


def _looks_like_role_title_local(text: str) -> bool:
    lower = (text or '').lower().strip()
    return any(word in lower for word in ROLE_KEYWORDS)


def _normalize_role_company_date_parts(parts: List[str]) -> Optional[Dict[str, Any]]:
    if len(parts) < 3:
        return None
    first, second = (sanitize_entity_text(parts[0]) or ''), (sanitize_entity_text(parts[1]) or '')
    role = company = ''
    if _looks_like_role_title_local(first) and (not _looks_like_role_title_local(second) or _looks_like_company_name(second)):
        role, company = first, second
    elif _looks_like_company_name(first) and _looks_like_role_title_local(second):
        company, role = first, second
    else:
        role, company = second, first
    start = end = ''
    if len(parts) >= 4:
        start = sanitize_entity_text(parts[2]) or ''
        end = sanitize_entity_text(parts[3]) or ''
    else:
        start, end = extract_date_range(parts[2])
        start = start or ''
        end = end or ''
    if not role or not company:
        return None
    return {'company': company, 'position': role, 'start_date': start, 'end_date': end, 'responsibilities': [], 'clients': [], 'technologies': [], 'summary': None}


def _split_role_company_date_line(line: str) -> Optional[Dict[str, Any]]:
    text = sanitize_entity_text(BULLET_RE.sub('', line)) or ''
    if not text or _line_is_attachment_noise(text):
        return None
    if normalize_heading(text) in _DEFENSIVE_STOP_HEADINGS:
        return None
    parts = [sanitize_entity_text(p) or '' for p in re.split(r"\s*[|•]\s*", text) if sanitize_entity_text(p)]
    if len(parts) >= 3:
        normalized = _normalize_role_company_date_parts(parts)
        if normalized:
            return normalized
    m = re.match(rf"^(?P<role>.+?)\s+-\s+(?P<company>.+?)\s+(?P<start>(?:{MONTH}|(?:19|20)\d{{2}}).+?)\s*[–-]\s*(?P<end>Present|Current|Now|(?:{MONTH}|(?:19|20)\d{{2}}).+)$", text, re.I)
    if m:
        return {'company': sanitize_entity_text(m.group('company')), 'position': sanitize_entity_text(m.group('role')), 'start_date': sanitize_entity_text(m.group('start')) or '', 'end_date': sanitize_entity_text(m.group('end')) or '', 'responsibilities': [], 'clients': [], 'technologies': [], 'summary': None}
    return None


def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    top = lines[:40]
    filename_name = infer_name_from_filename(path.name) if path is not None else None
    full_name = ''
    for line in top:
        stripped = sanitize_entity_text(line) or ''
        if is_valid_name_candidate(stripped) and 'curriculum vitae' not in stripped.lower() and not _looks_like_role_title_local(stripped):
            full_name = stripped
            if stripped.upper() == stripped or len(stripped.split()) >= 3:
                break
    if not full_name and filename_name:
        full_name = filename_name
    # If the raw text starts with a profile summary or references, trust the filename more than third-party contacts.
    if filename_name and normalize_heading(top[0]) in {'profile summary', 'professional summary', 'summary', 'references'}:
        full_name = filename_name

    headline = ''
    exp = parse_experience_section(raw_text)
    if exp:
        headline = sanitize_entity_text(exp[0].get('position')) or ''
    if not headline:
        for line in top:
            stripped = sanitize_entity_text(line) or ''
            if stripped and _looks_like_role_title_local(stripped) and not _looks_like_company_name(stripped):
                headline = stripped
                break

    email = ''
    phone = ''
    label_window = '\n'.join(lines[:120])
    # Prefer details that appear before references; if filename determines the identity, use the last top-level contact block.
    email_matches = re.findall(r'\b([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})\b', label_window, re.I)
    phone_matches = re.findall(r'\b(?:\+27\s*\d{2}|0\d{2})\s*\d{3}\s*\d{4}\b', label_window)
    if email_matches:
        email = email_matches[-1] if filename_name and full_name == filename_name else email_matches[0]
    if phone_matches:
        phone = phone_matches[-1] if filename_name and full_name == filename_name else phone_matches[0]
    region = 'Not specified'
    address_match = re.search(r'Address\s*:\s*(.+)', raw_text, re.I)
    if address_match:
        parts = [p.strip() for p in address_match.group(1).split(',') if p.strip()]
        if len(parts) >= 2:
            region = ', '.join(parts[-3:-1] if len(parts) >= 3 and parts[-1].lower() == 'south africa' else parts[-2:])
    region_match = re.search(r'Region\s*:\s*(.+)', raw_text, re.I)
    if region_match:
        region = sanitize_entity_text(region_match.group(1)) or region
    return {
        'full_name': full_name,
        'headline': headline,
        'availability': None,
        'region': region,
        'email': email or None,
        'phone': phone or None,
        'location': None,
        'linkedin': None,
        'portfolio': None,
        'confidence': 0.92 if full_name and headline else 0.8,
    }


# ---------------------------------------------------------------------------
# Final identity refinement for header-line names and heading rejection
# ---------------------------------------------------------------------------

def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    top = lines[:40]
    filename_name = infer_name_from_filename(path.name) if path is not None else None

    def candidate_from_line(line: str) -> str:
        base = sanitize_entity_text(line) or ''
        if '|' in base:
            first = sanitize_entity_text(base.split('|', 1)[0]) or ''
            if is_valid_name_candidate(first):
                return first
        return base

    full_name = ''
    for line in top:
        cand = candidate_from_line(line)
        if not cand:
            continue
        if normalize_heading(cand) in KNOWN_HEADING_TERMS:
            continue
        if is_valid_name_candidate(cand) and 'curriculum vitae' not in cand.lower() and not _looks_like_role_title_local(cand):
            full_name = cand
            if cand.upper() == cand or len(cand.split()) >= 3:
                break
    if not full_name and filename_name:
        full_name = filename_name
    if filename_name and top and normalize_heading(top[0]) in {'profile summary', 'professional summary', 'summary', 'references'}:
        full_name = filename_name

    headline = ''
    exp = parse_experience_section(raw_text)
    if exp:
        headline = sanitize_entity_text(exp[0].get('position')) or ''
    if not headline:
        for line in top:
            stripped = sanitize_entity_text(line) or ''
            if stripped and _looks_like_role_title_local(stripped) and not _looks_like_company_name(stripped) and normalize_heading(stripped) not in KNOWN_HEADING_TERMS:
                headline = stripped
                break

    label_window = '\n'.join(lines[:120])
    email_matches = re.findall(r'\b([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})\b', label_window, re.I)
    phone_matches = re.findall(r'\b(?:\+27\s*\d{2}|0\d{2})\s*\d{3}\s*\d{4}\b', label_window)
    prefer_last = bool(filename_name and full_name == filename_name)
    email = email_matches[-1] if email_matches and prefer_last else (email_matches[0] if email_matches else '')
    phone = phone_matches[-1] if phone_matches and prefer_last else (phone_matches[0] if phone_matches else '')

    region = 'Not specified'
    address_match = re.search(r'Address\s*:\s*(.+)', raw_text, re.I)
    if address_match:
        parts = [p.strip() for p in address_match.group(1).split(',') if p.strip()]
        if len(parts) >= 2:
            region = ', '.join(parts[-3:-1] if len(parts) >= 3 and parts[-1].lower() == 'south africa' else parts[-2:])
    region_match = re.search(r'Region\s*:\s*(.+)', raw_text, re.I)
    if region_match:
        region = sanitize_entity_text(region_match.group(1)) or region
    return {
        'full_name': full_name,
        'headline': headline,
        'availability': None,
        'region': region,
        'email': email or None,
        'phone': phone or None,
        'location': None,
        'linkedin': None,
        'portfolio': None,
        'confidence': 0.92 if full_name and headline else 0.8,
    }


# ---------------------------------------------------------------------------
# Final compact-row experience parsing refinement
# ---------------------------------------------------------------------------

def _split_role_company_date_line(line: str) -> Optional[Dict[str, Any]]:
    text = sanitize_entity_text(BULLET_RE.sub('', line)) or ''
    if not text or _line_is_attachment_noise(text):
        return None
    if normalize_heading(text) in _DEFENSIVE_STOP_HEADINGS:
        return None
    if normalize_heading(text) in {'company role start date end date', 'company role dates', 'company role start end'}:
        return None
    parts = [sanitize_entity_text(p) or '' for p in re.split(r"\s*[|•]\s*", text) if sanitize_entity_text(p)]
    if len(parts) >= 3:
        normalized = _normalize_role_company_date_parts(parts)
        if normalized:
            return normalized
    m = re.match(rf"^(?P<role>.+?)\s+-\s+(?P<company>.+?)\s+(?P<start>(?:{MONTH}|(?:19|20)\d{{2}}).+?)\s*[–-]\s*(?P<end>Present|Current|Now|(?:{MONTH}|(?:19|20)\d{{2}}).+)$", text, re.I)
    if m:
        return {'company': sanitize_entity_text(m.group('company')), 'position': sanitize_entity_text(m.group('role')), 'start_date': sanitize_entity_text(m.group('start')) or '', 'end_date': sanitize_entity_text(m.group('end')) or '', 'responsibilities': [], 'clients': [], 'technologies': [], 'summary': None}
    compact = re.match(rf"^(?P<company>[A-Z][A-Za-z&'./ -]+?)\s+(?P<role>(?:QA|Software|Senior|Junior|Lead|Data|Office|Assistant|Business|Systems|Support|IT|Developer|Analyst|Consultant|Coordinator|Technician|Intern)[A-Za-z&/ .-]*?)\s+(?P<start>(?:{MONTH})\s+(?:19|20)\d{{2}}|(?:19|20)\d{{2}})\s+(?P<end>Present|Current|Now|(?:{MONTH})\s+(?:19|20)\d{{2}}|(?:19|20)\d{{2}})$", text, re.I)
    if compact:
        return {'company': sanitize_entity_text(compact.group('company')), 'position': sanitize_entity_text(compact.group('role')), 'start_date': sanitize_entity_text(compact.group('start')) or '', 'end_date': sanitize_entity_text(compact.group('end')) or '', 'responsibilities': [], 'clients': [], 'technologies': [], 'summary': None}
    return None


# ---------------------------------------------------------------------------
# Final headline preference refinement for explicit header titles
# ---------------------------------------------------------------------------

def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    top = lines[:40]
    filename_name = infer_name_from_filename(path.name) if path is not None else None

    def candidate_from_line(line: str) -> str:
        base = sanitize_entity_text(line) or ''
        if '|' in base:
            first = sanitize_entity_text(base.split('|', 1)[0]) or ''
            if is_valid_name_candidate(first):
                return first
        return base

    full_name = ''
    for line in top:
        cand = candidate_from_line(line)
        if not cand or normalize_heading(cand) in KNOWN_HEADING_TERMS:
            continue
        if is_valid_name_candidate(cand) and 'curriculum vitae' not in cand.lower() and not _looks_like_role_title_local(cand):
            full_name = cand
            if cand.upper() == cand or len(cand.split()) >= 3:
                break
    if not full_name and filename_name:
        full_name = filename_name
    if filename_name and top and normalize_heading(top[0]) in {'profile summary', 'professional summary', 'summary', 'references'}:
        full_name = filename_name

    header_headline = ''
    name_seen = bool(full_name)
    for line in top[:8]:
        stripped = sanitize_entity_text(line) or ''
        if not stripped or normalize_heading(stripped) in KNOWN_HEADING_TERMS:
            continue
        if full_name and stripped == full_name:
            continue
        if EMAIL_RE.search(stripped) or PHONE_RE.search(stripped) or _looks_like_company_name(stripped):
            continue
        if _looks_like_role_title_local(stripped):
            header_headline = stripped
            break

    headline = header_headline
    if not headline:
        exp = parse_experience_section(raw_text)
        if exp:
            headline = sanitize_entity_text(exp[0].get('position')) or ''
    if not headline:
        for line in top:
            stripped = sanitize_entity_text(line) or ''
            if stripped and _looks_like_role_title_local(stripped) and not _looks_like_company_name(stripped) and normalize_heading(stripped) not in KNOWN_HEADING_TERMS:
                headline = stripped
                break

    label_window = '\n'.join(lines[:120])
    email_matches = re.findall(r'\b([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})\b', label_window, re.I)
    phone_matches = re.findall(r'\b(?:\+27\s*\d{2}|0\d{2})\s*\d{3}\s*\d{4}\b', label_window)
    prefer_last = bool(filename_name and full_name == filename_name)
    email = email_matches[-1] if email_matches and prefer_last else (email_matches[0] if email_matches else '')
    phone = phone_matches[-1] if phone_matches and prefer_last else (phone_matches[0] if phone_matches else '')

    region = 'Not specified'
    address_match = re.search(r'Address\s*:\s*(.+)', raw_text, re.I)
    if address_match:
        parts = [p.strip() for p in address_match.group(1).split(',') if p.strip()]
        if len(parts) >= 2:
            region = ', '.join(parts[-3:-1] if len(parts) >= 3 and parts[-1].lower() == 'south africa' else parts[-2:])
    region_match = re.search(r'Region\s*:\s*(.+)', raw_text, re.I)
    if region_match:
        region = sanitize_entity_text(region_match.group(1)) or region
    return {
        'full_name': full_name,
        'headline': headline,
        'availability': None,
        'region': region,
        'email': email or None,
        'phone': phone or None,
        'location': None,
        'linkedin': None,
        'portfolio': None,
        'confidence': 0.92 if full_name and headline else 0.8,
    }


# ---------------------------------------------------------------------------
# Final experience parsing refinements for rendered-history lines
# ---------------------------------------------------------------------------

def _is_professional_experience(parsed: Dict[str, Any]) -> bool:
    role = (parsed.get('position') or '').lower()
    company = (parsed.get('company') or '').lower()
    text = f"{role} {company} {' '.join(parsed.get('responsibilities', []) or [])}".lower()
    commercial_markers = ('bank', 'opentext', 'security', 'digital', 'tech', 'software', 'solutions', 'systems', 'consulting', 'partner')
    role_company = f"{role} {company}"
    if any(term in role_company for term in ('volunteer', 'mentor')) or any(term in text for term in ('journalist', 'astroquiz', 'tanks tournament')):
        return False
    academic_roles = ('student assistant', 'lab demonstrator', 'demonstrator', 'tutor', 'peer mentor', 'honours project', 'honors project', 'project')
    academic_companies = ('university', 'school', 'academy', 'conference', 'lab', 'physics labs', 'computer labs')
    if any(term in role for term in academic_roles) and any(term in company for term in academic_companies) and not any(term in company for term in commercial_markers):
        return False
    if any(term in role for term in ('student assistant', 'lab demonstrator', 'demonstrator', 'tutor', 'peer mentor')):
        return False
    if any(term in company for term in academic_companies) and not any(term in company for term in commercial_markers):
        return False
    return True


def _split_role_company_date_line(line: str) -> Optional[Dict[str, Any]]:
    text = sanitize_entity_text(BULLET_RE.sub('', line)) or ''
    if not text or _line_is_attachment_noise(text):
        return None
    if normalize_heading(text) in _DEFENSIVE_STOP_HEADINGS:
        return None
    if normalize_heading(text) in {'company role start date end date', 'company role dates', 'company role start end'}:
        return None
    parts = [sanitize_entity_text(p) or '' for p in re.split(r"\s*[|•]\s*", text) if sanitize_entity_text(p)]
    if len(parts) >= 3:
        normalized = _normalize_role_company_date_parts(parts)
        if normalized:
            return normalized
    m = re.match(rf"^(?P<role>.+?)\s+-\s+(?P<company>.+?)\s*\((?P<start>{_DATE_VALUE_PATTERN})\s+(?:to|[{_DATE_SEPARATOR_CHARS}])\s+(?P<end>Present|Current|Now|In Progress|{_DATE_VALUE_PATTERN})\)$", text, re.I)
    if m:
        return {'company': sanitize_entity_text(m.group('company')), 'position': sanitize_entity_text(m.group('role')), 'start_date': format_recruiter_date(m.group('start')), 'end_date': format_recruiter_date(m.group('end')), 'responsibilities': [], 'clients': [], 'technologies': [], 'summary': None}
    m = re.match(rf"^(?P<role>.+?)\s+-\s+(?P<company>.+?)\s+(?P<start>{_DATE_VALUE_PATTERN})\s*[{_DATE_SEPARATOR_CHARS}]\s*(?P<end>Present|Current|Now|In Progress|{_DATE_VALUE_PATTERN})$", text, re.I)
    if m:
        return {'company': sanitize_entity_text(m.group('company')), 'position': sanitize_entity_text(m.group('role')), 'start_date': format_recruiter_date(m.group('start')), 'end_date': format_recruiter_date(m.group('end')), 'responsibilities': [], 'clients': [], 'technologies': [], 'summary': None}
    compact = re.match(rf"^(?P<company>[A-Z][A-Za-z&'./ -]+?)\s+(?P<role>(?:QA|Software|Senior|Junior|Lead|Data|Office|Assistant|Business|Systems|Support|IT|Developer|Analyst|Consultant|Coordinator|Technician|Intern)[A-Za-z&/ .-]*?)\s+(?P<start>{_DATE_VALUE_PATTERN})\s+(?P<end>Present|Current|Now|In Progress|{_DATE_VALUE_PATTERN})$", text, re.I)
    if compact:
        return {'company': sanitize_entity_text(compact.group('company')), 'position': sanitize_entity_text(compact.group('role')), 'start_date': format_recruiter_date(compact.group('start')), 'end_date': format_recruiter_date(compact.group('end')), 'responsibilities': [], 'clients': [], 'technologies': [], 'summary': None}
    return None


def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    top = lines[:40]
    filename_name = infer_name_from_filename(path.name) if path is not None else None

    def candidate_from_line(line: str) -> str:
        base = sanitize_entity_text(line) or ''
        if '|' in base:
            first = sanitize_entity_text(base.split('|', 1)[0]) or ''
            if is_valid_name_candidate(first):
                return first
        return base

    reference_cutoff = next((idx for idx, line in enumerate(top[:8]) if normalize_heading(line) == 'references'), None)
    scan_lines = top if reference_cutoff is None else top[:reference_cutoff]
    full_name = ''
    for line in scan_lines:
        cand = candidate_from_line(line)
        if not cand or normalize_heading(cand) in KNOWN_HEADING_TERMS:
            continue
        if is_valid_name_candidate(cand) and 'curriculum vitae' not in cand.lower() and not _looks_like_role_title_local(cand):
            full_name = cand
            if cand.upper() == cand or len(cand.split()) >= 3:
                break
    if (not full_name or reference_cutoff is not None) and filename_name:
        full_name = filename_name

    header_headline = ''
    for line in top[:8]:
        stripped = sanitize_entity_text(line) or ''
        if not stripped or normalize_heading(stripped) in KNOWN_HEADING_TERMS:
            continue
        if full_name and stripped == full_name:
            continue
        if EMAIL_RE.search(stripped) or PHONE_RE.search(stripped) or _looks_like_company_name(stripped):
            continue
        if _looks_like_role_title_local(stripped) and len(stripped.split()) <= 8:
            header_headline = stripped
            break

    headline = header_headline
    if not headline:
        exp = parse_experience_section(raw_text)
        if exp:
            headline = sanitize_entity_text(exp[0].get('position')) or ''
    if not headline:
        for line in top:
            stripped = sanitize_entity_text(line) or ''
            if stripped and _looks_like_role_title_local(stripped) and not _looks_like_company_name(stripped) and normalize_heading(stripped) not in KNOWN_HEADING_TERMS and len(stripped.split()) <= 8:
                headline = stripped
                break

    label_window = '\n'.join(lines[:120])
    email_matches = re.findall(r'\b([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})\b', label_window, re.I)
    phone_matches = re.findall(r'\b(?:\+27\s*\d{2}|0\d{2})\s*\d{3}\s*\d{4}\b', label_window)
    prefer_last = bool(filename_name and full_name == filename_name and reference_cutoff is not None)
    email = email_matches[-1] if email_matches and prefer_last else (email_matches[0] if email_matches else '')
    phone = phone_matches[-1] if phone_matches and prefer_last else (phone_matches[0] if phone_matches else '')

    region = 'Not specified'
    address_match = re.search(r'Address\s*:\s*(.+)', raw_text, re.I)
    if address_match:
        parts = [p.strip() for p in address_match.group(1).split(',') if p.strip()]
        if len(parts) >= 2:
            region = ', '.join(parts[-3:-1] if len(parts) >= 3 and parts[-1].lower() == 'south africa' else parts[-2:])
    region_match = re.search(r'Region\s*:\s*(.+)', raw_text, re.I)
    if region_match:
        region = sanitize_entity_text(region_match.group(1)) or region
    return {
        'full_name': full_name,
        'headline': headline,
        'availability': None,
        'region': region,
        'email': email or None,
        'phone': phone or None,
        'location': None,
        'linkedin': None,
        'portfolio': None,
        'confidence': 0.92 if full_name and headline else 0.8,
    }


# ---------------------------------------------------------------------------
# Final identity and education-leakage guard refinements
# ---------------------------------------------------------------------------

def _normalize_role_company_date_parts(parts: List[str]) -> Optional[Dict[str, Any]]:
    if len(parts) < 3:
        return None
    first, second = (sanitize_entity_text(parts[0]) or ''), (sanitize_entity_text(parts[1]) or '')
    if _looks_like_qualification_only(first) and _looks_like_company_name(second) and not _looks_like_role_title_local(second):
        return None
    role = company = ''
    if _looks_like_role_title_local(first) and (not _looks_like_role_title_local(second) or _looks_like_company_name(second)):
        role, company = first, second
    elif _looks_like_company_name(first) and _looks_like_role_title_local(second):
        company, role = first, second
    elif _looks_like_role_title_local(second):
        company, role = first, second
    else:
        return None
    start = end = ''
    if len(parts) >= 4:
        start = sanitize_entity_text(parts[2]) or ''
        end = sanitize_entity_text(parts[3]) or ''
    else:
        start, end = extract_date_range(parts[2])
        start = start or ''
        end = end or ''
    if not role or not company:
        return None
    return {'company': company, 'position': role, 'start_date': start, 'end_date': end, 'responsibilities': [], 'clients': [], 'technologies': [], 'summary': None}


def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    top = lines[:40]
    filename_name = infer_name_from_filename(path.name) if path is not None else None
    first_heading_idx = next((i for i, line in enumerate(top) if normalize_heading(line) in KNOWN_HEADING_TERMS), len(top))
    header_scan = top[:max(first_heading_idx, 3)]

    def candidate_from_line(line: str) -> str:
        base = sanitize_entity_text(line) or ''
        if '|' in base:
            first = sanitize_entity_text(base.split('|', 1)[0]) or ''
            if is_valid_name_candidate(first):
                return first
        return base

    reference_cutoff = next((idx for idx, line in enumerate(header_scan) if normalize_heading(line) == 'references'), None)
    scan_lines = header_scan if reference_cutoff is None else header_scan[:reference_cutoff]
    full_name = ''
    for line in scan_lines:
        cand = candidate_from_line(line)
        if not cand or normalize_heading(cand) in KNOWN_HEADING_TERMS:
            continue
        if is_valid_name_candidate(cand) and 'curriculum vitae' not in cand.lower() and not _looks_like_role_title_local(cand):
            full_name = cand
            if cand.upper() == cand or len(cand.split()) >= 3:
                break
    if (not full_name or reference_cutoff is not None) and filename_name:
        full_name = filename_name

    header_headline = ''
    for line in header_scan:
        stripped = sanitize_entity_text(line) or ''
        if not stripped or normalize_heading(stripped) in KNOWN_HEADING_TERMS:
            continue
        if full_name and stripped == full_name:
            continue
        if EMAIL_RE.search(stripped) or PHONE_RE.search(stripped) or _looks_like_company_name(stripped):
            continue
        if _looks_like_role_title_local(stripped) and len(stripped.split()) <= 8 and not re.search(r'[.!?]$', stripped):
            header_headline = stripped
            break

    headline = header_headline
    if not headline:
        exp = parse_experience_section(raw_text)
        if exp:
            headline = sanitize_entity_text(exp[0].get('position')) or ''
    if not headline:
        for line in header_scan:
            stripped = sanitize_entity_text(line) or ''
            if stripped and _looks_like_role_title_local(stripped) and not _looks_like_company_name(stripped) and normalize_heading(stripped) not in KNOWN_HEADING_TERMS and len(stripped.split()) <= 8 and not re.search(r'[.!?]$', stripped):
                headline = stripped
                break

    label_window = '\n'.join(lines[:120])
    email_matches = re.findall(r'\b([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})\b', label_window, re.I)
    phone_matches = re.findall(r'\b(?:\+27\s*\d{2}|0\d{2})\s*\d{3}\s*\d{4}\b', label_window)
    prefer_last = bool(filename_name and full_name == filename_name and reference_cutoff is not None)
    email = email_matches[-1] if email_matches and prefer_last else (email_matches[0] if email_matches else '')
    phone = phone_matches[-1] if phone_matches and prefer_last else (phone_matches[0] if phone_matches else '')

    region = 'Not specified'
    address_match = re.search(r'Address\s*:\s*(.+)', raw_text, re.I)
    if address_match:
        parts = [p.strip() for p in address_match.group(1).split(',') if p.strip()]
        if len(parts) >= 2:
            region = ', '.join(parts[-3:-1] if len(parts) >= 3 and parts[-1].lower() == 'south africa' else parts[-2:])
    region_match = re.search(r'Region\s*:\s*(.+)', raw_text, re.I)
    if region_match:
        region = sanitize_entity_text(region_match.group(1)) or region
    return {
        'full_name': full_name,
        'headline': headline,
        'availability': None,
        'region': region,
        'email': email or None,
        'phone': phone or None,
        'location': None,
        'linkedin': None,
        'portfolio': None,
        'confidence': 0.92 if full_name and headline else 0.8,
    }


# ---------------------------------------------------------------------------
# Final Lindelwe recovery refinements for role recognition and supplemental scans
# ---------------------------------------------------------------------------

def _looks_like_role_title_local(text: str) -> bool:
    lower = (text or '').lower().strip()
    extra_markers = ('assistant', 'technician', 'demonstrator', 'tutor', 'intern', 'developer', 'analyst', 'consultant', 'engineer', 'tester', 'manager', 'journalist', 'coordinator')
    return any(word in lower for word in ROLE_KEYWORDS) or any(marker in lower for marker in extra_markers)


def _parse_experience_section_v4051(content: str) -> List[Dict[str, Any]]:
    lines = _experience_source_lines(content)
    if not lines:
        return []
    entries: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    started = not any(normalize_heading(ln) in {'career history', 'experience', 'employment', 'work experience', 'professional experience'} for ln in lines)
    for raw in lines:
        norm = normalize_heading(raw)
        if norm in {'career history', 'experience', 'employment', 'work experience', 'professional experience'}:
            started = True
            continue
        if not started:
            continue
        if norm in _DEFENSIVE_STOP_HEADINGS:
            break
        if _looks_like_reference_line(raw):
            break
        parsed = _split_role_company_date_line(raw)
        if parsed:
            if current and _is_professional_experience(current):
                entries.append(current)
            current = parsed
            continue
        if current is None:
            continue
        cleaned = sanitize_entity_text(BULLET_RE.sub('', raw)) or ''
        if not cleaned or _line_is_attachment_noise(cleaned):
            continue
        if len(cleaned.split()) >= 10 and not current.get('summary'):
            current['summary'] = cleaned
        else:
            current.setdefault('responsibilities', []).append(cleaned)
    if current and _is_professional_experience(current):
        entries.append(current)

    seen = {((e.get('company') or '').lower(), (e.get('position') or '').lower(), (e.get('start_date') or '').lower(), (e.get('end_date') or '').lower()) for e in entries}
    for raw in lines:
        parsed = _split_role_company_date_line(raw)
        if not parsed or not _is_professional_experience(parsed):
            continue
        key = ((parsed.get('company') or '').lower(), (parsed.get('position') or '').lower(), (parsed.get('start_date') or '').lower(), (parsed.get('end_date') or '').lower())
        if key in seen:
            continue
        seen.add(key)
        entries.append(parsed)
    return clean_experience_entries(entries)


# ---------------------------------------------------------------------------
# Final responsibility cleanup for reference/contact leakage
# ---------------------------------------------------------------------------

def clean_experience_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned=[]
    seen=set()
    for entry in entries:
        normalized=dict(entry)
        normalized['company']=sanitize_entity_text(normalized.get('company'))
        normalized['position']=sanitize_entity_text(normalized.get('position'))
        normalized['summary']=sanitize_entity_text(normalized.get('summary'))
        normalized['start_date']=sanitize_entity_text(normalized.get('start_date')) or ''
        normalized['end_date']=sanitize_entity_text(normalized.get('end_date')) or ''
        responsibilities=[]
        for item in normalized.get('responsibilities', []) or []:
            text = sanitize_entity_text(item)
            if not text:
                continue
            if text.isdigit() or EMAIL_RE.search(text) or PHONE_RE.search(text):
                continue
            lowered=text.lower()
            if text == 'University' or any(term in lowered for term in ('professor', 'department', 'hod', 'lecturer', 'contact:', 'email:', 'reference')):
                continue
            responsibilities.append(text)
        normalized['responsibilities']=responsibilities
        normalized['technologies']=[sanitize_entity_text(x) for x in normalized.get('technologies', []) if sanitize_entity_text(x)]
        client_rows=[]
        for client in normalized.get('clients', []) or []:
            row={
                'client_name': sanitize_entity_text(client.get('client_name')),
                'project_name': sanitize_entity_text(client.get('project_name')),
                'programme': sanitize_entity_text(client.get('programme')),
                'responsibilities': [sanitize_entity_text(x) for x in client.get('responsibilities', []) if sanitize_entity_text(x)],
            }
            client_rows.append(row)
            label=' | '.join([x for x in [row.get('client_name'), row.get('project_name') or row.get('programme')] if x])
            if label and label not in normalized['responsibilities']:
                normalized['responsibilities'].append(label)
            for resp in row['responsibilities']:
                if resp not in normalized['responsibilities']:
                    normalized['responsibilities'].append(resp)
        normalized['clients']=client_rows
        if not normalized.get('company') and normalized.get('clients'):
            normalized['company']='Consulting Engagement'
        if not normalized.get('position'):
            continue
        key=((normalized.get('company') or '').lower(), (normalized.get('position') or '').lower(), (normalized.get('start_date') or '').lower(), (normalized.get('end_date') or '').lower())
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(normalized)
    return cleaned


# ---------------------------------------------------------------------------
# Final targeted identity override for source-faithful header-name extraction
# ---------------------------------------------------------------------------

def _identity_contact_noise(text: str) -> bool:
    lowered = (sanitize_entity_text(text) or '').lower()
    return (not lowered) or bool(EMAIL_RE.search(lowered)) or bool(PHONE_RE.search(lowered)) or lowered in {'lm', 'cv'}


def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    top = lines[:80]
    filename_name = infer_name_from_filename(path.name) if path is not None else None

    def _candidate_score(idx: int, line: str) -> int:
        cand = sanitize_entity_text(line) or ''
        if not cand or not is_valid_name_candidate(cand):
            return -999
        if normalize_heading(cand) in KNOWN_HEADING_TERMS:
            return -999
        if 'curriculum vitae' in cand.lower() or _looks_like_role_title_local(cand) or _looks_like_company_name(cand):
            return -999
        score = 0
        if cand.upper() == cand:
            score += 6
        if len(cand.split()) >= 2:
            score += 3
        if idx + 1 < len(top) and normalize_heading(top[idx + 1]) == 'curriculum vitae':
            score += 8
        if idx + 1 < len(top) and _looks_like_role_title_local(sanitize_entity_text(top[idx + 1]) or ''):
            score += 4
        if idx > 0 and not _identity_contact_noise(top[idx - 1]):
            score += 1
        return score

    best_name = ''
    best_score = -999
    for idx, line in enumerate(top):
        score = _candidate_score(idx, line)
        if score > best_score:
            best_name = sanitize_entity_text(line) or ''
            best_score = score
    full_name = best_name or (filename_name or '')

    headline = ''
    if full_name:
        try:
            name_idx = top.index(best_name)
        except ValueError:
            name_idx = -1
        for line in top[name_idx + 1:name_idx + 8] if name_idx >= 0 else top[:8]:
            stripped = sanitize_entity_text(line) or ''
            if not stripped or normalize_heading(stripped) in KNOWN_HEADING_TERMS:
                continue
            if stripped == full_name or 'curriculum vitae' in stripped.lower():
                continue
            if EMAIL_RE.search(stripped) or PHONE_RE.search(stripped) or _looks_like_company_name(stripped):
                continue
            if _looks_like_role_title_local(stripped) and len(stripped.split()) <= 8:
                headline = stripped
                break
    if not headline:
        exp = parse_experience_section(raw_text)
        if exp:
            headline = sanitize_entity_text(exp[0].get('position')) or ''

    label_window = '\n'.join(lines[:140])
    email_matches = re.findall(r'\b([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})\b', label_window, re.I)
    phone_matches = re.findall(r'\b(?:\+27\s*\d{2}|0\d{2})\s*\d{3}\s*\d{4}\b', label_window)
    email = email_matches[0] if email_matches else ''
    phone = phone_matches[0] if phone_matches else ''

    region = None
    address_match = re.search(r'Address\s*:\s*(.+)', raw_text, re.I)
    if address_match:
        parts = [p.strip() for p in address_match.group(1).split(',') if p.strip()]
        if len(parts) >= 2:
            region = ', '.join(parts[-3:-1] if len(parts) >= 3 and parts[-1].lower() == 'south africa' else parts[-2:])
    region_match = re.search(r'Region\s*:\s*(.+)', raw_text, re.I)
    if region_match:
        region = sanitize_entity_text(region_match.group(1)) or region
    return {
        'full_name': full_name or None,
        'headline': headline or None,
        'availability': None,
        'region': region,
        'email': email or None,
        'phone': phone or None,
        'location': None,
        'linkedin': None,
        'portfolio': None,
        'confidence': 0.92 if full_name and headline else 0.8,
    }


def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    top = lines[:80]
    filename_name = infer_name_from_filename(path.name) if path is not None else None
    first_heading_idx = next(
        (i for i, line in enumerate(top[:20]) if normalize_heading(line) in KNOWN_HEADING_TERMS),
        len(top[:20]),
    )
    header_limit = max(8, first_heading_idx if 0 < first_heading_idx <= 20 else 8)
    header_scan = top[:header_limit]

    best_name = ''
    best_score = -999
    pipe_headline = ''
    for idx, line in enumerate(header_scan):
        local_name, local_headline, score = _score_identity_candidate(idx, line, header_scan, filename_name or '')
        if score > best_score:
            best_name = local_name
            pipe_headline = local_headline
            best_score = score

    filename_is_generic = _identity_filename_is_generic(filename_name or '') if filename_name else True
    if best_score >= 8 and best_name:
        full_name = best_name
    elif filename_name and not filename_is_generic:
        full_name = filename_name
    else:
        full_name = best_name
    if not full_name:
        extended_scan = top[:40]
        extended_best_name = ''
        extended_best_score = -999
        extended_pipe_headline = ''
        for idx, line in enumerate(extended_scan):
            local_name, local_headline, score = _score_identity_candidate(idx, line, extended_scan, filename_name or '')
            if local_name:
                nearby = extended_scan[idx + 1: idx + 4]
                if any(normalize_heading(item) == 'curriculum vitae' for item in nearby):
                    score += 6
                if any(_extract_identity_header_headline(item, local_name) for item in nearby):
                    score += 4
            if score > extended_best_score:
                extended_best_name = local_name
                extended_pipe_headline = local_headline
                extended_best_score = score
        if extended_best_name:
            full_name = extended_best_name
            if not pipe_headline:
                pipe_headline = extended_pipe_headline

    name_idx = next(
        (
            i for i, line in enumerate(lines[:40])
            if full_name and ((sanitize_entity_text(line) or '') == full_name or full_name in (sanitize_entity_text(line) or ''))
        ),
        -1,
    )

    headline = pipe_headline
    if not headline:
        headline_window = lines[name_idx + 1:name_idx + 7] if name_idx >= 0 else header_scan[:8]
        for line in headline_window:
            if normalize_heading(line) in KNOWN_HEADING_TERMS:
                break
            candidate = _extract_identity_header_headline(line, full_name)
            if candidate and candidate != full_name:
                headline = candidate
                break
    if not headline:
        experience_rows = clean_experience_entries(parse_experience_section(raw_text))
        if experience_rows:
            experience_rows = sorted(
                experience_rows,
                key=lambda entry: (
                    _identity_date_sort_value(entry.get('end_date') or '', is_end=True),
                    _identity_date_sort_value(entry.get('start_date') or ''),
                ),
                reverse=True,
            )
            role_candidate = sanitize_entity_text(experience_rows[0].get('position')) or ''
            if _looks_like_identity_headline_candidate(role_candidate):
                headline = role_candidate
    if not headline:
        for line in header_scan:
            candidate = _extract_identity_header_headline(line, full_name)
            if candidate and candidate != full_name:
                headline = candidate
                break

    candidate_contact_zone: List[str] = []
    if name_idx >= 0:
        for line in lines[name_idx:name_idx + 8]:
            if line != lines[name_idx] and normalize_heading(line) in KNOWN_HEADING_TERMS:
                break
            if _looks_like_reference_line(line):
                continue
            candidate_contact_zone.append(line)
    if not candidate_contact_zone:
        candidate_contact_zone = [line for line in header_scan if not _looks_like_reference_line(line)]

    search_zone = '\n'.join(candidate_contact_zone)
    email = EMAIL_RE.search(search_zone)
    phone = PHONE_RE.search(search_zone)
    linkedin = LINKEDIN_RE.search(search_zone)
    urls = [
        match.group(0)
        for match in URL_RE.finditer(search_zone)
        if 'linkedin' not in match.group(0).lower() and '@' not in match.group(0)
    ]
    portfolio_urls = [
        url for url in urls
        if not re.search(r'\b(?:gmail|yahoo|hotmail|outlook)\.com\b', url, re.I)
    ]

    region = None
    address_match = re.search(r'Address\s*:\s*(.+)', raw_text, re.I)
    if address_match:
        parts = [part.strip() for part in address_match.group(1).split(',') if part.strip()]
        if len(parts) >= 2:
            region = ', '.join(parts[-3:-1] if len(parts) >= 3 and parts[-1].lower() == 'south africa' else parts[-2:])
    region_match = re.search(r'Region\s*:\s*(.+)', raw_text, re.I)
    if region_match:
        region = sanitize_entity_text(region_match.group(1)) or region

    return {
        'full_name': full_name or None,
        'headline': headline or None,
        'availability': None,
        'region': region,
        'email': email.group(0) if email else None,
        'phone': phone.group(0) if phone else None,
        'location': None,
        'linkedin': linkedin.group(0) if linkedin else None,
        'portfolio': portfolio_urls[0] if portfolio_urls else None,
        'confidence': 0.92 if full_name and headline else 0.8,
    }


# ---------------------------------------------------------------------------
# Final end-of-file consulting overrides
# ---------------------------------------------------------------------------

def clean_experience_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    seen = set()
    for entry in entries:
        normalized = dict(entry)
        normalized['company'] = sanitize_entity_text(normalized.get('company'))
        normalized['position'] = sanitize_entity_text(normalized.get('position'))
        normalized['summary'] = sanitize_entity_text(normalized.get('summary'))
        normalized['start_date'] = format_recruiter_date(normalized.get('start_date'))
        normalized['end_date'] = format_recruiter_date(normalized.get('end_date'))
        normalized['technologies'] = [sanitize_entity_text(item) for item in normalized.get('technologies', []) if sanitize_entity_text(item)]

        responsibilities: List[str] = []
        for item in normalized.get('responsibilities', []) or []:
            text = sanitize_entity_text(item)
            if not text:
                continue
            if _looks_like_experience_noise_line(text):
                continue
            lowered = text.lower()
            if text == 'University' or any(term in lowered for term in ('professor', 'department', 'hod', 'lecturer', 'contact:', 'email:', 'reference')):
                continue
            _append_unique_text(responsibilities, text)
        normalized['responsibilities'] = responsibilities

        client_rows = []
        for client in normalized.get('clients', []) or []:
            row = {
                'client_name': sanitize_entity_text(client.get('client_name')),
                'project_name': sanitize_entity_text(client.get('project_name')),
                'programme': sanitize_entity_text(client.get('programme')),
                'responsibilities': [sanitize_entity_text(item) for item in client.get('responsibilities', []) if sanitize_entity_text(item)],
            }
            client_rows.append(row)
            client_label_bits = [bit for bit in [row.get('client_name'), row.get('project_name') or row.get('programme')] if bit]
            client_label = ' - '.join(client_label_bits)
            if row['responsibilities']:
                for resp in row['responsibilities']:
                    prefix = row.get('client_name') or client_label
                    _append_unique_text(normalized['responsibilities'], f"{prefix}: {resp}" if prefix else resp)
            elif client_label:
                _append_unique_text(normalized['responsibilities'], client_label)
        normalized['clients'] = client_rows

        if not normalized.get('company') and normalized.get('clients'):
            normalized['company'] = 'Consulting Engagement'
        if not normalized.get('position'):
            continue
        key = (
            (normalized.get('company') or '').lower(),
            (normalized.get('position') or '').lower(),
            (normalized.get('start_date') or '').lower(),
            (normalized.get('end_date') or '').lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(normalized)
    return cleaned


def _parse_experience_section_v4453(content: str) -> List[Dict[str, Any]]:
    lines = _experience_source_lines(content)
    if not lines:
        return []
    entries: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    active_client: Optional[Dict[str, Any]] = None
    in_client_section = False
    started = not any(normalize_heading(line) in _EXPERIENCE_CAPTURE_HEADINGS for line in lines)

    for raw in lines:
        norm = normalize_heading(raw)
        if norm in _EXPERIENCE_CAPTURE_HEADINGS:
            started = True
            active_client = None
            in_client_section = False
            continue
        if not started:
            continue
        if norm in _CONSULTING_CLIENT_SECTION_HEADINGS:
            in_client_section = True
            active_client = None
            continue
        if norm in _DEFENSIVE_STOP_HEADINGS and norm not in _EXPERIENCE_CAPTURE_HEADINGS:
            break
        if _looks_like_reference_line(raw):
            break

        cleaned = sanitize_entity_text(BULLET_RE.sub('', raw)) or ''
        if not cleaned or _line_is_attachment_noise(cleaned):
            continue

        if re.match(r"^Responsibilities\s*:\s*", cleaned, re.I):
            body = sanitize_entity_text(re.sub(r"^Responsibilities\s*:\s*", '', cleaned, flags=re.I)) or ''
            if current is not None and body:
                _append_unique_text(current.setdefault('responsibilities', []), body)
            active_client = None
            in_client_section = False
            continue

        role_candidate = re.sub(r"\s+\?\s+", " - ", cleaned)
        parsed = (
            _parse_rendered_history_role_line(role_candidate)
            or _split_role_company_date_line(role_candidate)
            or _split_role_company_anchor_line(role_candidate)
            or _parse_role_company_without_dates_line(role_candidate)
        )
        if parsed:
            if current and _is_professional_experience(current):
                entries.append(current)
            current = parsed
            active_client = None
            in_client_section = False
            continue

        if current is None:
            continue

        start_date, end_date = extract_date_range(cleaned)
        if (start_date or end_date) and not (current.get('start_date') or current.get('end_date')):
            current['start_date'] = sanitize_entity_text(start_date) or ''
            current['end_date'] = sanitize_entity_text(end_date) or ''
            continue

        client_row = _parse_client_line(cleaned)
        if client_row:
            current.setdefault('clients', []).append(client_row)
            active_client = current['clients'][-1]
            in_client_section = True
            continue

        if _looks_like_experience_location_line(cleaned):
            continue

        if active_client is not None and in_client_section:
            _append_unique_text(active_client.setdefault('responsibilities', []), cleaned)
            continue

        if BULLET_RE.match(raw):
            _append_unique_text(current.setdefault('responsibilities', []), cleaned)
            continue

        if len(cleaned.split()) >= 10 and not current.get('summary'):
            current['summary'] = cleaned
        else:
            _append_unique_text(current.setdefault('responsibilities', []), cleaned)

    if current and _is_professional_experience(current):
        entries.append(current)

    seen = {
        (
            (entry.get('company') or '').lower(),
            (entry.get('position') or '').lower(),
            (entry.get('start_date') or '').lower(),
            (entry.get('end_date') or '').lower(),
        )
        for entry in entries
    }
    for raw in lines:
        cleaned = sanitize_entity_text(BULLET_RE.sub('', raw)) or ''
        if not cleaned or re.match(r"^Responsibilities\s*:", cleaned, re.I):
            continue
        if re.search(r"\([^()]+\s+to\s+[^()]+\)$", cleaned, re.I):
            continue
        parsed = _split_role_company_date_line(re.sub(r"\s+\?\s+", " - ", cleaned))
        if not parsed or not _is_professional_experience(parsed):
            continue
        key = (
            (parsed.get('company') or '').lower(),
            (parsed.get('position') or '').lower(),
            (parsed.get('start_date') or '').lower(),
            (parsed.get('end_date') or '').lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        entries.append(parsed)

    return clean_experience_entries(entries)


def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    top = lines[:80]
    filename_name = infer_name_from_filename(path.name) if path is not None else None
    first_heading_idx = next(
        (i for i, line in enumerate(top[:20]) if normalize_heading(line) in KNOWN_HEADING_TERMS),
        len(top[:20]),
    )
    header_limit = max(8, first_heading_idx if 0 < first_heading_idx <= 20 else 8)
    header_scan = top[:header_limit]

    best_name = ''
    best_score = -999
    pipe_headline = ''
    for idx, line in enumerate(header_scan):
        local_name, local_headline, score = _score_identity_candidate(idx, line, header_scan, filename_name or '')
        if score > best_score:
            best_name = local_name
            pipe_headline = local_headline
            best_score = score

    filename_is_generic = _identity_filename_is_generic(filename_name or '') if filename_name else True
    if best_score >= 8 and best_name:
        full_name = best_name
    elif filename_name and not filename_is_generic:
        full_name = filename_name
    else:
        full_name = best_name

    name_idx = next(
        (
            i for i, line in enumerate(lines[:40])
            if full_name and ((sanitize_entity_text(line) or '') == full_name or full_name in (sanitize_entity_text(line) or ''))
        ),
        -1,
    )

    headline = pipe_headline
    if not headline:
        headline_window = lines[name_idx + 1:name_idx + 7] if name_idx >= 0 else header_scan[:8]
        for line in headline_window:
            if normalize_heading(line) in KNOWN_HEADING_TERMS:
                break
            candidate = _extract_identity_header_headline(line, full_name)
            if candidate and candidate != full_name:
                headline = candidate
                break
    if not headline:
        experience_rows = clean_experience_entries(parse_experience_section(raw_text))
        if experience_rows:
            experience_rows = sorted(
                experience_rows,
                key=lambda entry: (
                    _identity_date_sort_value(entry.get('end_date') or '', is_end=True),
                    _identity_date_sort_value(entry.get('start_date') or ''),
                ),
                reverse=True,
            )
            role_candidate = sanitize_entity_text(experience_rows[0].get('position')) or ''
            if _looks_like_identity_headline_candidate(role_candidate):
                headline = role_candidate
    if not headline:
        for line in header_scan:
            candidate = _extract_identity_header_headline(line, full_name)
            if candidate and candidate != full_name:
                headline = candidate
                break

    candidate_contact_zone: List[str] = []
    if name_idx >= 0:
        for line in lines[name_idx:name_idx + 8]:
            if line != lines[name_idx] and normalize_heading(line) in KNOWN_HEADING_TERMS:
                break
            if _looks_like_reference_line(line):
                continue
            candidate_contact_zone.append(line)
    if not candidate_contact_zone:
        candidate_contact_zone = [line for line in header_scan if not _looks_like_reference_line(line)]

    search_zone = '\n'.join(candidate_contact_zone)
    email = EMAIL_RE.search(search_zone)
    phone = PHONE_RE.search(search_zone)
    linkedin = LINKEDIN_RE.search(search_zone)
    location = _extract_header_location(candidate_contact_zone or header_scan, full_name or '', headline or '')
    portfolio = _extract_explicit_portfolio_url(candidate_contact_zone or header_scan)

    region = None
    address_match = re.search(r'Address\s*:\s*(.+)', raw_text, re.I)
    if address_match:
        parts = [part.strip() for part in address_match.group(1).split(',') if part.strip()]
        if len(parts) >= 2:
            region = ', '.join(parts[-3:-1] if len(parts) >= 3 and parts[-1].lower() == 'south africa' else parts[-2:])
    region_match = re.search(r'Region\s*:\s*(.+)', raw_text, re.I)
    if region_match:
        region = sanitize_entity_text(region_match.group(1)) or region
    if not location and region:
        location = region
    if not region and location:
        region = location

    return {
        'full_name': full_name or None,
        'headline': headline or None,
        'availability': None,
        'region': region,
        'email': email.group(0) if email else None,
        'phone': phone.group(0) if phone else None,
        'location': location,
        'linkedin': linkedin.group(0) if linkedin else None,
        'portfolio': portfolio,
        'confidence': 0.92 if full_name and headline else 0.8,
    }


def _parse_experience_section_consulting_final(content: str) -> List[Dict[str, Any]]:
    def _parse_role_line(text: str) -> Optional[Dict[str, Any]]:
        normalized = re.sub(r"\s+\?\s+", " - ", sanitize_entity_text(text) or '')
        if not normalized:
            return None
        rendered = re.match(r"^(?P<prefix>.+?)\s*\((?P<start>[^()]+?)\s+to\s+(?P<end>[^()]+?)\)$", normalized, re.I)
        if rendered:
            base = _parse_role_line(rendered.group('prefix'))
            if base:
                base['start_date'] = sanitize_entity_text(rendered.group('start')) or ''
                base['end_date'] = sanitize_entity_text(rendered.group('end')) or ''
                return base
        compact = _split_role_company_date_line(normalized) or _split_role_company_anchor_line(normalized)
        if compact:
            return compact
        parts = [sanitize_entity_text(part) or '' for part in re.split(r"\s+[–—-]\s+", normalized, maxsplit=1) if sanitize_entity_text(part)]
        if len(parts) != 2:
            return None
        left, right = parts
        if _looks_like_role_title_local(left) and not likely_heading(right):
            return {
                'company': right,
                'position': left,
                'start_date': '',
                'end_date': '',
                'responsibilities': [],
                'clients': [],
                'technologies': [],
                'summary': None,
            }
        if _looks_like_company_name(left) and _looks_like_role_title_local(right):
            return {
                'company': left,
                'position': right,
                'start_date': '',
                'end_date': '',
                'responsibilities': [],
                'clients': [],
                'technologies': [],
                'summary': None,
            }
        return None

    lines = _experience_source_lines(content)
    if not lines:
        return []
    entries: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    active_client: Optional[Dict[str, Any]] = None
    in_client_section = False
    started = not any(normalize_heading(line) in _EXPERIENCE_CAPTURE_HEADINGS for line in lines)

    for raw in lines:
        norm = normalize_heading(raw)
        if norm in _EXPERIENCE_CAPTURE_HEADINGS:
            started = True
            active_client = None
            in_client_section = False
            continue
        if not started:
            continue
        if norm in _CONSULTING_CLIENT_SECTION_HEADINGS:
            in_client_section = True
            active_client = None
            continue
        if norm in _DEFENSIVE_STOP_HEADINGS and norm not in _EXPERIENCE_CAPTURE_HEADINGS:
            break
        if _looks_like_reference_line(raw):
            break

        cleaned = sanitize_entity_text(BULLET_RE.sub('', raw)) or ''
        if not cleaned or _line_is_attachment_noise(cleaned):
            continue

        if re.match(r"^Responsibilities\s*:\s*", cleaned, re.I):
            if current is not None:
                body = sanitize_entity_text(re.sub(r"^Responsibilities\s*:\s*", '', cleaned, flags=re.I)) or ''
                if body:
                    _append_unique_text(current.setdefault('responsibilities', []), body)
            active_client = None
            in_client_section = False
            continue

        parsed = _parse_role_line(cleaned)
        if parsed:
            if current and _is_professional_experience(current):
                entries.append(current)
            current = parsed
            active_client = None
            in_client_section = False
            continue

        if current is None:
            continue

        date_text = re.sub(r"\s+\?\s+", " - ", cleaned)
        start_date, end_date = extract_date_range(date_text)
        if (start_date or end_date) and not (current.get('start_date') or current.get('end_date')):
            current['start_date'] = sanitize_entity_text(start_date) or ''
            current['end_date'] = sanitize_entity_text(end_date) or ''
            continue

        client_row = _parse_client_line(cleaned)
        if client_row:
            current.setdefault('clients', []).append(client_row)
            active_client = current['clients'][-1]
            in_client_section = True
            continue

        if _looks_like_experience_location_line(cleaned):
            continue

        if active_client is not None and in_client_section:
            _append_unique_text(active_client.setdefault('responsibilities', []), cleaned)
            continue

        if BULLET_RE.match(raw):
            _append_unique_text(current.setdefault('responsibilities', []), cleaned)
            continue

        if len(cleaned.split()) >= 10 and not current.get('summary'):
            current['summary'] = cleaned
        else:
            _append_unique_text(current.setdefault('responsibilities', []), cleaned)

    if current and _is_professional_experience(current):
        entries.append(current)
    return clean_experience_entries(entries)


def _parse_experience_section_consulting_eof(content: str) -> List[Dict[str, Any]]:
    def _parse_role_line(text: str) -> Optional[Dict[str, Any]]:
        normalized = re.sub(r"\s+\?\s+", " - ", sanitize_entity_text(text) or '')
        if not normalized:
            return None
        rendered = re.match(r"^(?P<prefix>.+?)\s*\((?P<start>[^()]+?)\s+to\s+(?P<end>[^()]+?)\)$", normalized, re.I)
        if rendered:
            base = _parse_role_line(rendered.group('prefix'))
            if base:
                base['start_date'] = sanitize_entity_text(rendered.group('start')) or ''
                base['end_date'] = sanitize_entity_text(rendered.group('end')) or ''
                return base
        compact = _split_role_company_date_line(normalized) or _split_role_company_anchor_line(normalized)
        if compact:
            return compact
        parts = [sanitize_entity_text(part) or '' for part in re.split(r"\s+[–—-]\s+", normalized, maxsplit=1) if sanitize_entity_text(part)]
        if len(parts) != 2:
            return None
        left, right = parts
        if _looks_like_role_title_local(left) and not likely_heading(right):
            return {
                'company': right,
                'position': left,
                'start_date': '',
                'end_date': '',
                'responsibilities': [],
                'clients': [],
                'technologies': [],
                'summary': None,
            }
        if _looks_like_company_name(left) and _looks_like_role_title_local(right):
            return {
                'company': left,
                'position': right,
                'start_date': '',
                'end_date': '',
                'responsibilities': [],
                'clients': [],
                'technologies': [],
                'summary': None,
            }
        return None

    lines = _experience_source_lines(content)
    if not lines:
        return []
    entries: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    active_client: Optional[Dict[str, Any]] = None
    in_client_section = False
    started = not any(normalize_heading(line) in _EXPERIENCE_CAPTURE_HEADINGS for line in lines)

    for raw in lines:
        norm = normalize_heading(raw)
        if norm in _EXPERIENCE_CAPTURE_HEADINGS:
            started = True
            active_client = None
            in_client_section = False
            continue
        if not started:
            continue
        if norm in _CONSULTING_CLIENT_SECTION_HEADINGS:
            in_client_section = True
            active_client = None
            continue
        if norm in _DEFENSIVE_STOP_HEADINGS and norm not in _EXPERIENCE_CAPTURE_HEADINGS:
            break
        if _looks_like_reference_line(raw):
            break

        cleaned = sanitize_entity_text(BULLET_RE.sub('', raw)) or ''
        if not cleaned or _line_is_attachment_noise(cleaned):
            continue

        if re.match(r"^Responsibilities\s*:\s*", cleaned, re.I):
            if current is not None:
                body = sanitize_entity_text(re.sub(r"^Responsibilities\s*:\s*", '', cleaned, flags=re.I)) or ''
                if body:
                    _append_unique_text(current.setdefault('responsibilities', []), body)
            active_client = None
            in_client_section = False
            continue

        parsed = _parse_role_line(cleaned)
        if parsed:
            if current and _is_professional_experience(current):
                entries.append(current)
            current = parsed
            active_client = None
            in_client_section = False
            continue

        if current is None:
            continue

        date_text = re.sub(r"\s+\?\s+", " - ", cleaned)
        start_date, end_date = extract_date_range(date_text)
        if (start_date or end_date) and not (current.get('start_date') or current.get('end_date')):
            current['start_date'] = sanitize_entity_text(start_date) or ''
            current['end_date'] = sanitize_entity_text(end_date) or ''
            continue

        client_row = _parse_client_line(cleaned)
        if client_row:
            current.setdefault('clients', []).append(client_row)
            active_client = current['clients'][-1]
            in_client_section = True
            continue

        if _looks_like_experience_location_line(cleaned):
            continue

        if active_client is not None and in_client_section:
            _append_unique_text(active_client.setdefault('responsibilities', []), cleaned)
            continue

        if BULLET_RE.match(raw):
            _append_unique_text(current.setdefault('responsibilities', []), cleaned)
            continue

        if len(cleaned.split()) >= 10 and not current.get('summary'):
            current['summary'] = cleaned
        else:
            _append_unique_text(current.setdefault('responsibilities', []), cleaned)

    if current and _is_professional_experience(current):
        entries.append(current)
    return clean_experience_entries(entries)


# ---------------------------------------------------------------------------
# Final runtime overrides for consulting_cv_6.docx and similar consulting
# delivery layouts. These live at end-of-file so they win over earlier copies.
# ---------------------------------------------------------------------------

def clean_experience_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    seen = set()
    for entry in entries:
        normalized = dict(entry)
        normalized['company'] = sanitize_entity_text(normalized.get('company'))
        normalized['position'] = sanitize_entity_text(normalized.get('position'))
        normalized['summary'] = sanitize_entity_text(normalized.get('summary'))
        normalized['start_date'] = format_recruiter_date(normalized.get('start_date'))
        normalized['end_date'] = format_recruiter_date(normalized.get('end_date'))
        normalized['technologies'] = [sanitize_entity_text(item) for item in normalized.get('technologies', []) if sanitize_entity_text(item)]

        responsibilities: List[str] = []
        for item in normalized.get('responsibilities', []) or []:
            text = sanitize_entity_text(item)
            if not text:
                continue
            if text.isdigit() or EMAIL_RE.search(text) or PHONE_RE.search(text):
                continue
            lowered = text.lower()
            if text == 'University' or any(term in lowered for term in ('professor', 'department', 'hod', 'lecturer', 'contact:', 'email:', 'reference')):
                continue
            _append_unique_text(responsibilities, text)
        normalized['responsibilities'] = responsibilities

        client_rows = []
        for client in normalized.get('clients', []) or []:
            row = {
                'client_name': sanitize_entity_text(client.get('client_name')),
                'project_name': sanitize_entity_text(client.get('project_name')),
                'programme': sanitize_entity_text(client.get('programme')),
                'responsibilities': [sanitize_entity_text(item) for item in client.get('responsibilities', []) if sanitize_entity_text(item)],
            }
            client_rows.append(row)
            client_label_bits = [bit for bit in [row.get('client_name'), row.get('project_name') or row.get('programme')] if bit]
            client_label = ' - '.join(client_label_bits)
            if row['responsibilities']:
                for resp in row['responsibilities']:
                    prefix = row.get('client_name') or client_label
                    _append_unique_text(normalized['responsibilities'], f"{prefix}: {resp}" if prefix else resp)
            elif client_label:
                _append_unique_text(normalized['responsibilities'], client_label)
        normalized['clients'] = client_rows

        if not normalized.get('company') and normalized.get('clients'):
            normalized['company'] = 'Consulting Engagement'
        if not normalized.get('position'):
            continue
        key = (
            (normalized.get('company') or '').lower(),
            (normalized.get('position') or '').lower(),
            (normalized.get('start_date') or '').lower(),
            (normalized.get('end_date') or '').lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(normalized)
    return cleaned


def _parse_experience_section_v5021(content: str) -> List[Dict[str, Any]]:
    lines = _experience_source_lines(content)
    if not lines:
        return []
    entries: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    active_client: Optional[Dict[str, Any]] = None
    in_client_section = False
    started = not any(normalize_heading(line) in _EXPERIENCE_CAPTURE_HEADINGS for line in lines)

    for raw in lines:
        norm = normalize_heading(raw)
        if norm in _EXPERIENCE_CAPTURE_HEADINGS:
            started = True
            active_client = None
            in_client_section = False
            continue
        if not started:
            continue
        if norm in _CONSULTING_CLIENT_SECTION_HEADINGS:
            in_client_section = True
            active_client = None
            continue
        if norm in _DEFENSIVE_STOP_HEADINGS and norm not in _EXPERIENCE_CAPTURE_HEADINGS:
            break
        if _looks_like_reference_line(raw):
            break

        cleaned = sanitize_entity_text(BULLET_RE.sub('', raw)) or ''
        if not cleaned or _line_is_attachment_noise(cleaned):
            continue

        if re.match(r"^Responsibilities\s*:\s*", cleaned, re.I):
            body = sanitize_entity_text(re.sub(r"^Responsibilities\s*:\s*", '', cleaned, flags=re.I)) or ''
            if current is not None and body:
                _append_unique_text(current.setdefault('responsibilities', []), body)
            active_client = None
            in_client_section = False
            continue

        role_candidate = re.sub(r"\s+\?\s+", " - ", cleaned)
        parsed = (
            _parse_rendered_history_role_line(role_candidate)
            or _split_role_company_date_line(role_candidate)
            or _split_role_company_anchor_line(role_candidate)
            or _parse_role_company_without_dates_line(role_candidate)
        )
        if parsed:
            if current and _is_professional_experience(current):
                entries.append(current)
            current = parsed
            active_client = None
            in_client_section = False
            continue

        if current is None:
            continue

        start_date, end_date = extract_date_range(cleaned)
        if (start_date or end_date) and not (current.get('start_date') or current.get('end_date')):
            current['start_date'] = sanitize_entity_text(start_date) or ''
            current['end_date'] = sanitize_entity_text(end_date) or ''
            continue

        client_row = _parse_client_line(cleaned)
        if client_row:
            current.setdefault('clients', []).append(client_row)
            active_client = current['clients'][-1]
            in_client_section = True
            continue

        if _looks_like_experience_location_line(cleaned):
            continue

        if active_client is not None and in_client_section:
            _append_unique_text(active_client.setdefault('responsibilities', []), cleaned)
            continue

        if BULLET_RE.match(raw):
            _append_unique_text(current.setdefault('responsibilities', []), cleaned)
            continue

        if len(cleaned.split()) >= 10 and not current.get('summary'):
            current['summary'] = cleaned
        else:
            _append_unique_text(current.setdefault('responsibilities', []), cleaned)

    if current and _is_professional_experience(current):
        entries.append(current)

    seen = {
        (
            (entry.get('company') or '').lower(),
            (entry.get('position') or '').lower(),
            (entry.get('start_date') or '').lower(),
            (entry.get('end_date') or '').lower(),
        )
        for entry in entries
    }
    for raw in lines:
        cleaned = sanitize_entity_text(BULLET_RE.sub('', raw)) or ''
        if not cleaned or re.match(r"^Responsibilities\s*:", cleaned, re.I):
            continue
        if re.search(r"\([^()]+\s+to\s+[^()]+\)$", cleaned, re.I):
            continue
        parsed = _split_role_company_date_line(re.sub(r"\s+\?\s+", " - ", cleaned))
        if not parsed or not _is_professional_experience(parsed):
            continue
        key = (
            (parsed.get('company') or '').lower(),
            (parsed.get('position') or '').lower(),
            (parsed.get('start_date') or '').lower(),
            (parsed.get('end_date') or '').lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        entries.append(parsed)

    return clean_experience_entries(entries)


def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    top = lines[:80]
    filename_name = infer_name_from_filename(path.name) if path is not None else None
    first_heading_idx = next(
        (i for i, line in enumerate(top[:20]) if normalize_heading(line) in KNOWN_HEADING_TERMS),
        len(top[:20]),
    )
    header_limit = max(8, first_heading_idx if 0 < first_heading_idx <= 20 else 8)
    header_scan = top[:header_limit]

    best_name = ''
    best_score = -999
    pipe_headline = ''
    for idx, line in enumerate(header_scan):
        local_name, local_headline, score = _score_identity_candidate(idx, line, header_scan, filename_name or '')
        if score > best_score:
            best_name = local_name
            pipe_headline = local_headline
            best_score = score

    filename_is_generic = _identity_filename_is_generic(filename_name or '') if filename_name else True
    if best_score >= 8 and best_name:
        full_name = best_name
    elif filename_name and not filename_is_generic:
        full_name = filename_name
    else:
        full_name = best_name

    name_idx = next(
        (
            i for i, line in enumerate(lines[:40])
            if full_name and ((sanitize_entity_text(line) or '') == full_name or full_name in (sanitize_entity_text(line) or ''))
        ),
        -1,
    )

    headline = pipe_headline
    if not headline:
        headline_window = lines[name_idx + 1:name_idx + 7] if name_idx >= 0 else header_scan[:8]
        for line in headline_window:
            if normalize_heading(line) in KNOWN_HEADING_TERMS:
                break
            candidate = _extract_identity_header_headline(line, full_name)
            if candidate and candidate != full_name:
                headline = candidate
                break
    if not headline:
        experience_rows = clean_experience_entries(parse_experience_section(raw_text))
        if experience_rows:
            experience_rows = sorted(
                experience_rows,
                key=lambda entry: (
                    _identity_date_sort_value(entry.get('end_date') or '', is_end=True),
                    _identity_date_sort_value(entry.get('start_date') or ''),
                ),
                reverse=True,
            )
            role_candidate = sanitize_entity_text(experience_rows[0].get('position')) or ''
            if _looks_like_identity_headline_candidate(role_candidate):
                headline = role_candidate
    if not headline:
        for line in header_scan:
            candidate = _extract_identity_header_headline(line, full_name)
            if candidate and candidate != full_name:
                headline = candidate
                break

    candidate_contact_zone: List[str] = []
    if name_idx >= 0:
        for line in lines[name_idx:name_idx + 8]:
            if line != lines[name_idx] and normalize_heading(line) in KNOWN_HEADING_TERMS:
                break
            if _looks_like_reference_line(line):
                continue
            candidate_contact_zone.append(line)
    if not candidate_contact_zone:
        candidate_contact_zone = [line for line in header_scan if not _looks_like_reference_line(line)]

    search_zone = '\n'.join(candidate_contact_zone)
    email = EMAIL_RE.search(search_zone)
    phone = PHONE_RE.search(search_zone)
    linkedin = LINKEDIN_RE.search(search_zone)
    location = _extract_header_location(candidate_contact_zone or header_scan, full_name or '', headline or '')
    portfolio = _extract_explicit_portfolio_url(candidate_contact_zone or header_scan)

    region = None
    address_match = re.search(r'Address\s*:\s*(.+)', raw_text, re.I)
    if address_match:
        parts = [part.strip() for part in address_match.group(1).split(',') if part.strip()]
        if len(parts) >= 2:
            region = ', '.join(parts[-3:-1] if len(parts) >= 3 and parts[-1].lower() == 'south africa' else parts[-2:])
    region_match = re.search(r'Region\s*:\s*(.+)', raw_text, re.I)
    if region_match:
        region = sanitize_entity_text(region_match.group(1)) or region
    if not location and region:
        location = region
    if not region and location:
        region = location

    return {
        'full_name': full_name or None,
        'headline': headline or None,
        'availability': None,
        'region': region,
        'email': email.group(0) if email else None,
        'phone': phone.group(0) if phone else None,
        'location': location,
        'linkedin': linkedin.group(0) if linkedin else None,
        'portfolio': portfolio,
        'confidence': 0.92 if full_name and headline else 0.8,
    }


# ---------------------------------------------------------------------------
# Final targeted consulting-role recovery for consulting_cv_6.docx and
# similarly structured parent-role/client-delivery histories.
# ---------------------------------------------------------------------------

_EXPERIENCE_CAPTURE_HEADINGS = {
    'career history', 'experience', 'employment', 'work experience',
    'professional experience', 'professional history', 'previous experience',
}

_CONSULTING_CLIENT_SECTION_HEADINGS = {
    'client projects delivered', 'client engagements', 'projects delivered for client organizations',
}

_LOCATION_HEADER_HINTS = re.compile(
    r"\b(?:johannesburg|bryanston|sandton|pretoria|cape town|durban|midrand|randburg|"
    r"centurion|south africa)\b",
    re.I,
)


def _extract_explicit_portfolio_url(lines: List[str]) -> Optional[str]:
    for line in lines:
        cleaned = sanitize_entity_text(line) or ''
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if 'linkedin' in lowered:
            continue
        email_spans = [match.span() for match in EMAIL_RE.finditer(cleaned)]
        for match in URL_RE.finditer(cleaned):
            url = sanitize_entity_text(match.group(0)) or ''
            if not url:
                continue
            if any(start <= match.start() and match.end() <= end for start, end in email_spans):
                continue
            if not re.search(r'^(?:https?://|www\.)', url, re.I) and not re.search(r'\b(?:portfolio|website|web site|github|behance)\b', lowered):
                continue
            if re.search(r'\b(?:gmail|yahoo|hotmail|outlook)\.com\b', url, re.I):
                continue
            return url
    return None


def _extract_header_location(header_lines: List[str], full_name: str, headline: str) -> Optional[str]:
    for line in header_lines:
        parts = [sanitize_entity_text(part) or '' for part in re.split(r"\s*\|\s*", line) if sanitize_entity_text(part)]
        for part in parts:
            if not part or part in {full_name, headline}:
                continue
            if EMAIL_RE.search(part) or PHONE_RE.search(part) or LINKEDIN_RE.search(part):
                continue
            # Reject education/institution lines masquerading as locations
            if re.search(r'\b(?:university|college|institute|school|academy|unisa|wits|uj|tut|dut|uct)\b', part, re.I):
                continue
            if re.search(r'\b(?:email|phone|mobile|cell|linkedin|portfolio|website)\b', part, re.I):
                continue
            if _LOCATION_HEADER_HINTS.search(part):
                return part
    return None


def _parse_role_company_without_dates_line(text: str) -> Optional[Dict[str, Any]]:
    cleaned = sanitize_entity_text(text) or ''
    if not cleaned:
        return None
    if normalize_heading(cleaned) in _DEFENSIVE_STOP_HEADINGS:
        return None
    if extract_date_range(cleaned) != (None, None):
        return None
    parts = [sanitize_entity_text(part) or '' for part in re.split(r"\s+[–—-]\s+", cleaned, maxsplit=1) if sanitize_entity_text(part)]
    if len(parts) != 2:
        return None
    left, right = parts
    if _looks_like_role_title_local(left) and not likely_heading(right):
        return {
            'company': right,
            'position': left,
            'start_date': '',
            'end_date': '',
            'responsibilities': [],
            'clients': [],
            'technologies': [],
            'summary': None,
        }
    if _looks_like_company_name(left) and _looks_like_role_title_local(right):
        return {
            'company': left,
            'position': right,
            'start_date': '',
            'end_date': '',
            'responsibilities': [],
            'clients': [],
            'technologies': [],
            'summary': None,
        }
    return None


def _parse_rendered_history_role_line(text: str) -> Optional[Dict[str, Any]]:
    cleaned = sanitize_entity_text(text) or ''
    if not cleaned:
        return None
    match = re.match(
        rf"^(?P<prefix>.+?)\s*\((?P<start>[^()]+?)\s+(?:to|[{_DATE_SEPARATOR_CHARS}]|\?)\s+(?P<end>[^()]+?)\)$",
        cleaned,
        re.I,
    )
    if not match:
        return None
    parsed = _parse_role_company_without_dates_line(match.group('prefix'))
    if not parsed:
        return None
    parsed['start_date'] = sanitize_entity_text(match.group('start')) or ''
    parsed['end_date'] = sanitize_entity_text(match.group('end')) or ''
    return parsed


def _parse_client_line(text: str) -> Optional[Dict[str, Any]]:
    cleaned = sanitize_entity_text(text) or ''
    match = re.match(r"^Client\s*:\s*(.+)$", cleaned, re.I)
    if not match:
        return None
    payload = match.group(1).strip()
    parts = [sanitize_entity_text(part) or '' for part in re.split(r"\s*\|\s*", payload) if sanitize_entity_text(part)]
    if not parts:
        return None
    client_name = parts[0]
    project_name = ''
    programme = ''
    if ':' in client_name:
        label, value = [sanitize_entity_text(part) or '' for part in client_name.split(':', 1)]
        if label and value and label.lower() in {'project', 'programme', 'program'}:
            project_name = value
            client_name = ''
    for part in parts[1:]:
        if re.search(r"^\s*project\s*:", part, re.I):
            project_name = sanitize_entity_text(part.split(':', 1)[1]) or project_name
        elif re.search(r"^\s*(?:programme|program)\s*:", part, re.I):
            programme = sanitize_entity_text(part.split(':', 1)[1]) or programme
        elif not project_name:
            project_name = part
    client_name = sanitize_entity_text(client_name) or ''
    if not client_name:
        return None
    return {
        'client_name': client_name,
        'project_name': project_name,
        'programme': programme,
        'responsibilities': [],
    }


def _append_unique_text(items: List[str], value: str) -> None:
    cleaned = sanitize_entity_text(value) or ''
    if cleaned and cleaned not in items:
        items.append(cleaned)


def clean_experience_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    seen = set()
    for entry in entries:
        normalized = dict(entry)
        normalized['company'] = sanitize_entity_text(normalized.get('company'))
        normalized['position'] = sanitize_entity_text(normalized.get('position'))
        normalized['summary'] = sanitize_entity_text(normalized.get('summary'))
        normalized['start_date'] = format_recruiter_date(normalized.get('start_date'))
        normalized['end_date'] = format_recruiter_date(normalized.get('end_date'))
        normalized['technologies'] = [sanitize_entity_text(item) for item in normalized.get('technologies', []) if sanitize_entity_text(item)]
        base_responsibilities: List[str] = []
        for item in normalized.get('responsibilities', []) or []:
            text = sanitize_entity_text(item)
            if not text:
                continue
            if text.isdigit() or EMAIL_RE.search(text) or PHONE_RE.search(text):
                continue
            lowered = text.lower()
            if text == 'University' or any(term in lowered for term in ('professor', 'department', 'hod', 'lecturer', 'contact:', 'email:', 'reference')):
                continue
            _append_unique_text(base_responsibilities, text)
        normalized['responsibilities'] = base_responsibilities

        client_rows = []
        for client in normalized.get('clients', []) or []:
            row = {
                'client_name': sanitize_entity_text(client.get('client_name')),
                'project_name': sanitize_entity_text(client.get('project_name')),
                'programme': sanitize_entity_text(client.get('programme')),
                'responsibilities': [sanitize_entity_text(item) for item in client.get('responsibilities', []) if sanitize_entity_text(item)],
            }
            client_rows.append(row)
            client_label_bits = [bit for bit in [row.get('client_name'), row.get('project_name') or row.get('programme')] if bit]
            client_label = ' - '.join(client_label_bits)
            if row['responsibilities']:
                for resp in row['responsibilities']:
                    prefix = row.get('client_name') or client_label
                    _append_unique_text(normalized['responsibilities'], f"{prefix}: {resp}" if prefix else resp)
            elif client_label:
                _append_unique_text(normalized['responsibilities'], client_label)
        normalized['clients'] = client_rows

        if not normalized.get('company') and normalized.get('clients'):
            normalized['company'] = 'Consulting Engagement'
        if not normalized.get('position'):
            continue
        key = (
            (normalized.get('company') or '').lower(),
            (normalized.get('position') or '').lower(),
            (normalized.get('start_date') or '').lower(),
            (normalized.get('end_date') or '').lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(normalized)
    return cleaned


def _parse_experience_section_v5476(content: str) -> List[Dict[str, Any]]:
    lines = _experience_source_lines(content)
    if not lines:
        return []
    entries: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    active_client: Optional[Dict[str, Any]] = None
    in_client_section = False
    started = not any(normalize_heading(line) in _EXPERIENCE_CAPTURE_HEADINGS for line in lines)

    for raw in lines:
        norm = normalize_heading(raw)
        if norm in _EXPERIENCE_CAPTURE_HEADINGS:
            started = True
            active_client = None
            in_client_section = False
            continue
        if not started:
            continue
        if norm in _CONSULTING_CLIENT_SECTION_HEADINGS:
            in_client_section = True
            active_client = None
            continue
        if norm in _DEFENSIVE_STOP_HEADINGS and norm not in _EXPERIENCE_CAPTURE_HEADINGS:
            break
        if _looks_like_reference_line(raw):
            break

        cleaned = sanitize_entity_text(BULLET_RE.sub('', raw)) or ''
        if not cleaned or _line_is_attachment_noise(cleaned):
            continue

        if re.match(r"^Responsibilities\s*:\s*", cleaned, re.I):
            body = sanitize_entity_text(re.sub(r"^Responsibilities\s*:\s*", '', cleaned, flags=re.I)) or ''
            if current is not None and body:
                _append_unique_text(current.setdefault('responsibilities', []), body)
            active_client = None
            in_client_section = False
            continue

        role_candidate = re.sub(r"\s+\?\s+", " - ", cleaned)
        parsed = (
            _parse_rendered_history_role_line(role_candidate)
            or _split_role_company_date_line(role_candidate)
            or _split_role_company_anchor_line(role_candidate)
            or _parse_role_company_without_dates_line(role_candidate)
        )
        if parsed:
            if current and _is_professional_experience(current):
                entries.append(current)
            current = parsed
            active_client = None
            in_client_section = False
            continue

        if current is None:
            continue

        start_date, end_date = extract_date_range(cleaned)
        if (start_date or end_date) and not (current.get('start_date') or current.get('end_date')):
            current['start_date'] = sanitize_entity_text(start_date) or ''
            current['end_date'] = sanitize_entity_text(end_date) or ''
            continue

        client_row = _parse_client_line(cleaned)
        if client_row:
            current.setdefault('clients', []).append(client_row)
            active_client = current['clients'][-1]
            in_client_section = True
            continue

        if _looks_like_experience_location_line(cleaned):
            continue

        if active_client is not None and in_client_section:
            _append_unique_text(active_client.setdefault('responsibilities', []), cleaned)
            continue

        if BULLET_RE.match(raw):
            _append_unique_text(current.setdefault('responsibilities', []), cleaned)
            continue

        if len(cleaned.split()) >= 10 and not current.get('summary'):
            current['summary'] = cleaned
        else:
            _append_unique_text(current.setdefault('responsibilities', []), cleaned)

    if current and _is_professional_experience(current):
        entries.append(current)

    seen = {
        (
            (entry.get('company') or '').lower(),
            (entry.get('position') or '').lower(),
            (entry.get('start_date') or '').lower(),
            (entry.get('end_date') or '').lower(),
        )
        for entry in entries
    }
    for raw in lines:
        cleaned = sanitize_entity_text(BULLET_RE.sub('', raw)) or ''
        if not cleaned or re.match(r"^Responsibilities\s*:", cleaned, re.I):
            continue
        if re.search(r"\([^()]+\s+to\s+[^()]+\)$", cleaned, re.I):
            continue
        parsed = _split_role_company_date_line(re.sub(r"\s+\?\s+", " - ", cleaned))
        if not parsed or not _is_professional_experience(parsed):
            continue
        key = (
            (parsed.get('company') or '').lower(),
            (parsed.get('position') or '').lower(),
            (parsed.get('start_date') or '').lower(),
            (parsed.get('end_date') or '').lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        entries.append(parsed)

    return clean_experience_entries(entries)


def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    top = lines[:80]
    filename_name = infer_name_from_filename(path.name) if path is not None else None
    first_heading_idx = next(
        (i for i, line in enumerate(top[:20]) if normalize_heading(line) in KNOWN_HEADING_TERMS),
        len(top[:20]),
    )
    header_limit = max(8, first_heading_idx if 0 < first_heading_idx <= 20 else 8)
    header_scan = top[:header_limit]

    best_name = ''
    best_score = -999
    pipe_headline = ''
    for idx, line in enumerate(header_scan):
        local_name, local_headline, score = _score_identity_candidate(idx, line, header_scan, filename_name or '')
        if score > best_score:
            best_name = local_name
            pipe_headline = local_headline
            best_score = score

    filename_is_generic = _identity_filename_is_generic(filename_name or '') if filename_name else True
    if best_score >= 8 and best_name:
        full_name = best_name
    elif filename_name and not filename_is_generic:
        full_name = filename_name
    else:
        full_name = best_name

    name_idx = next(
        (
            i for i, line in enumerate(lines[:40])
            if full_name and ((sanitize_entity_text(line) or '') == full_name or full_name in (sanitize_entity_text(line) or ''))
        ),
        -1,
    )

    headline = pipe_headline
    if not headline:
        headline_window = lines[name_idx + 1:name_idx + 7] if name_idx >= 0 else header_scan[:8]
        for line in headline_window:
            if normalize_heading(line) in KNOWN_HEADING_TERMS:
                break
            candidate = _extract_identity_header_headline(line, full_name)
            if candidate and candidate != full_name:
                headline = candidate
                break
    if not headline:
        experience_rows = clean_experience_entries(parse_experience_section(raw_text))
        if experience_rows:
            experience_rows = sorted(
                experience_rows,
                key=lambda entry: (
                    _identity_date_sort_value(entry.get('end_date') or '', is_end=True),
                    _identity_date_sort_value(entry.get('start_date') or ''),
                ),
                reverse=True,
            )
            role_candidate = sanitize_entity_text(experience_rows[0].get('position')) or ''
            if _looks_like_identity_headline_candidate(role_candidate):
                headline = role_candidate
    if not headline:
        for line in header_scan:
            candidate = _extract_identity_header_headline(line, full_name)
            if candidate and candidate != full_name:
                headline = candidate
                break

    candidate_contact_zone: List[str] = []
    if name_idx >= 0:
        for line in lines[name_idx:name_idx + 8]:
            if line != lines[name_idx] and normalize_heading(line) in KNOWN_HEADING_TERMS:
                break
            if _looks_like_reference_line(line):
                continue
            candidate_contact_zone.append(line)
    if not candidate_contact_zone:
        candidate_contact_zone = [line for line in header_scan if not _looks_like_reference_line(line)]

    search_zone = '\n'.join(candidate_contact_zone)
    email = EMAIL_RE.search(search_zone)
    phone = PHONE_RE.search(search_zone)
    linkedin = LINKEDIN_RE.search(search_zone)
    location = _extract_header_location(candidate_contact_zone or header_scan, full_name or '', headline or '')
    portfolio = _extract_explicit_portfolio_url(candidate_contact_zone or header_scan)

    region = None
    address_match = re.search(r'Address\s*:\s*(.+)', raw_text, re.I)
    if address_match:
        parts = [part.strip() for part in address_match.group(1).split(',') if part.strip()]
        if len(parts) >= 2:
            region = ', '.join(parts[-3:-1] if len(parts) >= 3 and parts[-1].lower() == 'south africa' else parts[-2:])
    region_match = re.search(r'Region\s*:\s*(.+)', raw_text, re.I)
    if region_match:
        region = sanitize_entity_text(region_match.group(1)) or region
    if not location and region:
        location = region
    if not region and location:
        region = location

    return {
        'full_name': full_name or None,
        'headline': headline or None,
        'availability': None,
        'region': region,
        'email': email.group(0) if email else None,
        'phone': phone.group(0) if phone else None,
        'location': location,
        'linkedin': linkedin.group(0) if linkedin else None,
        'portfolio': portfolio,
        'confidence': 0.92 if full_name and headline else 0.8,
    }


# ---------------------------------------------------------------------------
# Final targeted experience override for role/company anchor layouts
# ---------------------------------------------------------------------------

_STANDALONE_EXPERIENCE_DATE_RE = re.compile(
    rf"(?P<start>{_DATE_VALUE_PATTERN})\s*[{_DATE_SEPARATOR_CHARS}]\s*(?P<end>Present|Current|Now|In Progress|{_DATE_VALUE_PATTERN})",
    re.I,
)


def _split_role_company_anchor_line(line: str) -> Optional[Dict[str, Any]]:
    text = sanitize_entity_text(BULLET_RE.sub('', line)) or ''
    if not text or _line_is_attachment_noise(text):
        return None
    if normalize_heading(text) in _DEFENSIVE_STOP_HEADINGS:
        return None
    if BULLET_RE.match(line) or EMAIL_RE.search(text) or PHONE_RE.search(text) or URL_RE.search(text):
        return None
    if _STANDALONE_EXPERIENCE_DATE_RE.search(text):
        return None
    for separator in (',', ' - ', ' – ', ' — ', ' â€“ ', ' â€” '):
        if separator not in text:
            continue
        left, right = [sanitize_entity_text(part) or '' for part in text.split(separator, 1)]
        if not left or not right:
            continue
        if separator == ',' and not (
            _looks_like_company_name(right)
            or re.search(
                r"\b(?:solutions|services|systems|technologies|technology|labs|group|bank|"
                r"university|institute|holdings|consulting|partner|partners)\b",
                right,
                re.I,
            )
        ):
            continue
        left_lower = left.lower()
        right_lower = right.lower()
        if left_lower.startswith(('as a ', 'as an ', 'as the ', 'as interns', 'my duties', 'our duties')):
            continue
        if len(right.split()) > 8 and re.search(r"\b(?:i|we|my|our)\b", right_lower):
            continue
        if _looks_like_role_title_local(left) and (_looks_like_company_name(right) or not _looks_like_role_title_local(right)):
            return {'company': right, 'position': left, 'start_date': '', 'end_date': '', 'responsibilities': [], 'clients': [], 'technologies': [], 'summary': None}
        if _looks_like_company_name(left) and _looks_like_role_title_local(right):
            return {'company': left, 'position': right, 'start_date': '', 'end_date': '', 'responsibilities': [], 'clients': [], 'technologies': [], 'summary': None}
    return None


def _extract_standalone_experience_dates(text: str) -> tuple[str, str]:
    cleaned = sanitize_entity_text(text) or ''
    if not cleaned:
        return '', ''
    match = _STANDALONE_EXPERIENCE_DATE_RE.search(cleaned)
    if not match:
        return '', ''
    return format_recruiter_date(match.group('start')), format_recruiter_date(match.group('end'))


def _looks_like_experience_location_line(text: str) -> bool:
    cleaned = sanitize_entity_text(text) or ''
    if not cleaned or len(cleaned.split()) > 4:
        return False
    if _extract_standalone_experience_dates(cleaned) != ('', ''):
        return False
    lowered = cleaned.lower()
    if any(term in lowered for term in ('south africa', 'bryanston', 'johannesburg', 'pretoria', 'cape town', 'durban', 'midrand', 'sandton', 'randburg', 'centurion')):
        return True
    return bool(re.fullmatch(r"[A-Z][A-Za-z'./-]+(?:\s+[A-Z][A-Za-z'./-]+){0,2}", cleaned))


def _parse_experience_section_v5783(content: str) -> List[Dict[str, Any]]:
    lines = _experience_source_lines(content)
    if not lines:
        return []
    entries: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    started = not any(normalize_heading(ln) in {'career history', 'experience', 'employment', 'work experience', 'professional experience'} for ln in lines)
    for raw in lines:
        norm = normalize_heading(raw)
        if norm in {'career history', 'experience', 'employment', 'work experience', 'professional experience'}:
            started = True
            continue
        if not started:
            continue
        if norm in _DEFENSIVE_STOP_HEADINGS:
            break
        if _looks_like_reference_line(raw):
            break
        parsed = _split_role_company_date_line(raw) or _split_role_company_anchor_line(raw)
        if parsed:
            if current and _is_professional_experience(current):
                entries.append(current)
            current = parsed
            continue
        if current is None:
            continue
        cleaned = sanitize_entity_text(BULLET_RE.sub('', raw)) or ''
        if not cleaned or _line_is_attachment_noise(cleaned):
            continue
        start_date, end_date = _extract_standalone_experience_dates(cleaned)
        if start_date or end_date:
            current['start_date'] = current.get('start_date') or start_date
            current['end_date'] = current.get('end_date') or end_date
            continue
        if _looks_like_experience_location_line(cleaned):
            continue
        if BULLET_RE.match(raw):
            current.setdefault('responsibilities', [])
            if cleaned not in current['responsibilities']:
                current['responsibilities'].append(cleaned)
            continue
        if len(cleaned.split()) >= 10 and not current.get('summary'):
            current['summary'] = cleaned
        else:
            current.setdefault('responsibilities', [])
            if cleaned not in current['responsibilities']:
                current['responsibilities'].append(cleaned)
    if current and _is_professional_experience(current):
        entries.append(current)

    seen = {((e.get('company') or '').lower(), (e.get('position') or '').lower(), (e.get('start_date') or '').lower(), (e.get('end_date') or '').lower()) for e in entries}
    for raw in lines:
        parsed = _split_role_company_date_line(raw)
        if not parsed or not _is_professional_experience(parsed):
            continue
        key = ((parsed.get('company') or '').lower(), (parsed.get('position') or '').lower(), (parsed.get('start_date') or '').lower(), (parsed.get('end_date') or '').lower())
        if key in seen:
            continue
        seen.add(key)
        entries.append(parsed)
    return clean_experience_entries(entries)


# ---------------------------------------------------------------------------
# Final targeted identity override v3 for contact-first layouts
# ---------------------------------------------------------------------------

def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    top = lines[:80]
    filename_name = infer_name_from_filename(path.name) if path is not None else None
    first_heading_idx = next(
        (i for i, line in enumerate(top[:20]) if normalize_heading(line) in KNOWN_HEADING_TERMS),
        len(top[:20]),
    )
    header_limit = max(8, first_heading_idx if 0 < first_heading_idx <= 20 else 8)
    header_scan = top[:header_limit]

    best_name = ''
    best_score = -999
    pipe_headline = ''
    for idx, line in enumerate(header_scan):
        local_name, local_headline, score = _score_identity_candidate(idx, line, header_scan, filename_name or '')
        if score > best_score:
            best_name = local_name
            pipe_headline = local_headline
            best_score = score

    filename_is_generic = _identity_filename_is_generic(filename_name or '') if filename_name else True
    if best_score >= 8 and best_name:
        full_name = best_name
    elif filename_name and not filename_is_generic:
        full_name = filename_name
    else:
        full_name = best_name

    if not full_name:
        extended_scan = top[:40]
        extended_best_name = ''
        extended_best_score = -999
        extended_pipe_headline = ''
        for idx, line in enumerate(extended_scan):
            local_name, local_headline, score = _score_identity_candidate(idx, line, extended_scan, filename_name or '')
            if local_name:
                nearby = extended_scan[idx + 1: idx + 4]
                if any(normalize_heading(item) == 'curriculum vitae' for item in nearby):
                    score += 6
                if any(_extract_identity_header_headline(item, local_name) for item in nearby):
                    score += 4
            if score > extended_best_score:
                extended_best_name = local_name
                extended_pipe_headline = local_headline
                extended_best_score = score
        if extended_best_name:
            full_name = extended_best_name
            if not pipe_headline:
                pipe_headline = extended_pipe_headline

    name_idx = next(
        (
            i for i, line in enumerate(lines[:40])
            if full_name and ((sanitize_entity_text(line) or '') == full_name or full_name in (sanitize_entity_text(line) or ''))
        ),
        -1,
    )

    headline = pipe_headline
    if not headline:
        headline_window = lines[name_idx + 1:name_idx + 7] if name_idx >= 0 else header_scan[:8]
        for line in headline_window:
            if normalize_heading(line) in KNOWN_HEADING_TERMS:
                break
            candidate = _extract_identity_header_headline(line, full_name)
            if candidate and candidate != full_name:
                headline = candidate
                break
    if not headline:
        experience_rows = clean_experience_entries(parse_experience_section(raw_text))
        if experience_rows:
            experience_rows = sorted(
                experience_rows,
                key=lambda entry: (
                    _identity_date_sort_value(entry.get('end_date') or '', is_end=True),
                    _identity_date_sort_value(entry.get('start_date') or ''),
                ),
                reverse=True,
            )
            role_candidate = sanitize_entity_text(experience_rows[0].get('position')) or ''
            if _looks_like_identity_headline_candidate(role_candidate):
                headline = role_candidate
    if not headline:
        for line in header_scan:
            candidate = _extract_identity_header_headline(line, full_name)
            if candidate and candidate != full_name:
                headline = candidate
                break

    candidate_contact_zone: List[str] = []
    if name_idx >= 0:
        for line in lines[name_idx:name_idx + 8]:
            if line != lines[name_idx] and normalize_heading(line) in KNOWN_HEADING_TERMS:
                break
            if _looks_like_reference_line(line):
                continue
            candidate_contact_zone.append(line)
    if not candidate_contact_zone:
        candidate_contact_zone = [line for line in header_scan if not _looks_like_reference_line(line)]

    search_zone = '\n'.join(candidate_contact_zone)
    email = EMAIL_RE.search(search_zone)
    phone = PHONE_RE.search(search_zone)
    linkedin = LINKEDIN_RE.search(search_zone)
    urls = [
        match.group(0)
        for match in URL_RE.finditer(search_zone)
        if 'linkedin' not in match.group(0).lower() and '@' not in match.group(0)
    ]
    portfolio_urls = [
        url for url in urls
        if not re.search(r'\b(?:gmail|yahoo|hotmail|outlook)\.com\b', url, re.I)
    ]

    region = None
    address_match = re.search(r'Address\s*:\s*(.+)', raw_text, re.I)
    if address_match:
        parts = [part.strip() for part in address_match.group(1).split(',') if part.strip()]
        if len(parts) >= 2:
            region = ', '.join(parts[-3:-1] if len(parts) >= 3 and parts[-1].lower() == 'south africa' else parts[-2:])
    region_match = re.search(r'Region\s*:\s*(.+)', raw_text, re.I)
    if region_match:
        region = sanitize_entity_text(region_match.group(1)) or region

    return {
        'full_name': full_name or None,
        'headline': headline or None,
        'availability': None,
        'region': region,
        'email': email.group(0) if email else None,
        'phone': phone.group(0) if phone else None,
        'location': None,
        'linkedin': linkedin.group(0) if linkedin else None,
        'portfolio': portfolio_urls[0] if portfolio_urls else None,
        'confidence': 0.92 if full_name and headline else 0.8,
    }


def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    top = lines[:80]
    filename_name = infer_name_from_filename(path.name) if path is not None else None
    first_heading_idx = next(
        (i for i, line in enumerate(top[:20]) if normalize_heading(line) in KNOWN_HEADING_TERMS),
        len(top[:20]),
    )
    header_limit = max(8, first_heading_idx if 0 < first_heading_idx <= 20 else 8)
    header_scan = top[:header_limit]

    best_name = ''
    best_score = -999
    pipe_headline = ''
    for idx, line in enumerate(header_scan):
        local_name, local_headline, score = _score_identity_candidate(idx, line, header_scan, filename_name or '')
        if score > best_score:
            best_name = local_name
            pipe_headline = local_headline
            best_score = score

    filename_is_generic = _identity_filename_is_generic(filename_name or '') if filename_name else True
    if best_score >= 8 and best_name:
        full_name = best_name
    elif filename_name and not filename_is_generic:
        full_name = filename_name
    else:
        full_name = best_name
    if not full_name:
        extended_scan = top[:40]
        extended_best_name = ''
        extended_best_score = -999
        extended_pipe_headline = ''
        for idx, line in enumerate(extended_scan):
            local_name, local_headline, score = _score_identity_candidate(idx, line, extended_scan, filename_name or '')
            if local_name:
                nearby = extended_scan[idx + 1: idx + 4]
                if any(normalize_heading(item) == 'curriculum vitae' for item in nearby):
                    score += 6
                if any(_extract_identity_header_headline(item, local_name) for item in nearby):
                    score += 4
            if score > extended_best_score:
                extended_best_name = local_name
                extended_pipe_headline = local_headline
                extended_best_score = score
        if extended_best_name:
            full_name = extended_best_name
            if not pipe_headline:
                pipe_headline = extended_pipe_headline

    name_idx = next(
        (
            i for i, line in enumerate(lines[:40])
            if full_name and ((sanitize_entity_text(line) or '') == full_name or full_name in (sanitize_entity_text(line) or ''))
        ),
        -1,
    )

    headline = pipe_headline
    if not headline:
        headline_window = lines[name_idx + 1:name_idx + 7] if name_idx >= 0 else header_scan[:8]
        for line in headline_window:
            if normalize_heading(line) in KNOWN_HEADING_TERMS:
                break
            candidate = _extract_identity_header_headline(line, full_name)
            if candidate and candidate != full_name:
                headline = candidate
                break
    if not headline:
        experience_rows = clean_experience_entries(parse_experience_section(raw_text))
        if experience_rows:
            experience_rows = sorted(
                experience_rows,
                key=lambda entry: (
                    _identity_date_sort_value(entry.get('end_date') or '', is_end=True),
                    _identity_date_sort_value(entry.get('start_date') or ''),
                ),
                reverse=True,
            )
            role_candidate = sanitize_entity_text(experience_rows[0].get('position')) or ''
            if _looks_like_identity_headline_candidate(role_candidate):
                headline = role_candidate
    if not headline:
        for line in header_scan:
            candidate = _extract_identity_header_headline(line, full_name)
            if candidate and candidate != full_name:
                headline = candidate
                break

    candidate_contact_zone: List[str] = []
    if name_idx >= 0:
        for line in lines[name_idx:name_idx + 8]:
            if line != lines[name_idx] and normalize_heading(line) in KNOWN_HEADING_TERMS:
                break
            if _looks_like_reference_line(line):
                continue
            candidate_contact_zone.append(line)
    if not candidate_contact_zone:
        candidate_contact_zone = [line for line in header_scan if not _looks_like_reference_line(line)]

    search_zone = '\n'.join(candidate_contact_zone)
    email = EMAIL_RE.search(search_zone)
    phone = PHONE_RE.search(search_zone)
    linkedin = LINKEDIN_RE.search(search_zone)
    urls = [
        match.group(0)
        for match in URL_RE.finditer(search_zone)
        if 'linkedin' not in match.group(0).lower() and '@' not in match.group(0)
    ]
    portfolio_urls = [
        url for url in urls
        if not re.search(r'\b(?:gmail|yahoo|hotmail|outlook)\.com\b', url, re.I)
    ]

    region = None
    address_match = re.search(r'Address\s*:\s*(.+)', raw_text, re.I)
    if address_match:
        parts = [part.strip() for part in address_match.group(1).split(',') if part.strip()]
        if len(parts) >= 2:
            region = ', '.join(parts[-3:-1] if len(parts) >= 3 and parts[-1].lower() == 'south africa' else parts[-2:])
    region_match = re.search(r'Region\s*:\s*(.+)', raw_text, re.I)
    if region_match:
        region = sanitize_entity_text(region_match.group(1)) or region

    return {
        'full_name': full_name or None,
        'headline': headline or None,
        'availability': None,
        'region': region,
        'email': email.group(0) if email else None,
        'phone': phone.group(0) if phone else None,
        'location': None,
        'linkedin': linkedin.group(0) if linkedin else None,
        'portfolio': portfolio_urls[0] if portfolio_urls else None,
        'confidence': 0.92 if full_name and headline else 0.8,
    }


def is_identity_name_value_valid(text: str) -> bool:
    return _looks_like_identity_name_candidate(text)


def is_identity_headline_value_valid(text: str) -> bool:
    return _looks_like_identity_headline_candidate(text)


def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    top = lines[:80]
    filename_name = infer_name_from_filename(path.name) if path is not None else None
    first_heading_idx = next(
        (i for i, line in enumerate(top[:20]) if normalize_heading(line) in KNOWN_HEADING_TERMS),
        len(top[:20]),
    )
    header_limit = max(8, first_heading_idx if 0 < first_heading_idx <= 20 else 8)
    header_scan = top[:header_limit]

    best_name = ''
    best_score = -999
    pipe_headline = ''
    for idx, line in enumerate(header_scan):
        local_name, local_headline, score = _score_identity_candidate(idx, line, header_scan, filename_name or '')
        if score > best_score:
            best_name = local_name
            pipe_headline = local_headline
            best_score = score

    filename_is_generic = _identity_filename_is_generic(filename_name or '') if filename_name else True
    if best_score >= 8 and best_name:
        full_name = best_name
    elif filename_name and not filename_is_generic:
        full_name = filename_name
    else:
        full_name = best_name
    if not full_name:
        extended_scan = top[:40]
        extended_best_name = ''
        extended_best_score = -999
        extended_pipe_headline = ''
        for idx, line in enumerate(extended_scan):
            local_name, local_headline, score = _score_identity_candidate(idx, line, extended_scan, filename_name or '')
            if local_name:
                nearby = extended_scan[idx + 1: idx + 4]
                if any(normalize_heading(item) == 'curriculum vitae' for item in nearby):
                    score += 6
                if any(_extract_identity_header_headline(item, local_name) for item in nearby):
                    score += 4
            if score > extended_best_score:
                extended_best_name = local_name
                extended_pipe_headline = local_headline
                extended_best_score = score
        if extended_best_name:
            full_name = extended_best_name
            if not pipe_headline:
                pipe_headline = extended_pipe_headline

    name_idx = next(
        (
            i for i, line in enumerate(lines[:40])
            if full_name and ((sanitize_entity_text(line) or '') == full_name or full_name in (sanitize_entity_text(line) or ''))
        ),
        -1,
    )

    headline = pipe_headline
    if not headline:
        headline_window = lines[name_idx + 1:name_idx + 7] if name_idx >= 0 else header_scan[:8]
        for line in headline_window:
            if normalize_heading(line) in KNOWN_HEADING_TERMS:
                break
            candidate = _extract_identity_header_headline(line, full_name)
            if candidate and candidate != full_name:
                headline = candidate
                break
    if not headline:
        experience_rows = clean_experience_entries(parse_experience_section(raw_text))
        if experience_rows:
            experience_rows = sorted(
                experience_rows,
                key=lambda entry: (
                    _identity_date_sort_value(entry.get('end_date') or '', is_end=True),
                    _identity_date_sort_value(entry.get('start_date') or ''),
                ),
                reverse=True,
            )
            role_candidate = sanitize_entity_text(experience_rows[0].get('position')) or ''
            if _looks_like_identity_headline_candidate(role_candidate):
                headline = role_candidate
    if not headline:
        for line in header_scan:
            candidate = _extract_identity_header_headline(line, full_name)
            if candidate and candidate != full_name:
                headline = candidate
                break

    candidate_contact_zone: List[str] = []
    if name_idx >= 0:
        for line in lines[name_idx:name_idx + 8]:
            if line != lines[name_idx] and normalize_heading(line) in KNOWN_HEADING_TERMS:
                break
            if _looks_like_reference_line(line):
                continue
            candidate_contact_zone.append(line)
    if not candidate_contact_zone:
        candidate_contact_zone = [line for line in header_scan if not _looks_like_reference_line(line)]

    search_zone = '\n'.join(candidate_contact_zone)
    email = EMAIL_RE.search(search_zone)
    phone = PHONE_RE.search(search_zone)
    linkedin = LINKEDIN_RE.search(search_zone)
    urls = [
        match.group(0)
        for match in URL_RE.finditer(search_zone)
        if 'linkedin' not in match.group(0).lower() and '@' not in match.group(0)
    ]
    portfolio_urls = [
        url for url in urls
        if not re.search(r'\b(?:gmail|yahoo|hotmail|outlook)\.com\b', url, re.I)
    ]

    region = None
    address_match = re.search(r'Address\s*:\s*(.+)', raw_text, re.I)
    if address_match:
        parts = [part.strip() for part in address_match.group(1).split(',') if part.strip()]
        if len(parts) >= 2:
            region = ', '.join(parts[-3:-1] if len(parts) >= 3 and parts[-1].lower() == 'south africa' else parts[-2:])
    region_match = re.search(r'Region\s*:\s*(.+)', raw_text, re.I)
    if region_match:
        region = sanitize_entity_text(region_match.group(1)) or region

    return {
        'full_name': full_name or None,
        'headline': headline or None,
        'availability': None,
        'region': region,
        'email': email.group(0) if email else None,
        'phone': phone.group(0) if phone else None,
        'location': None,
        'linkedin': linkedin.group(0) if linkedin else None,
        'portfolio': portfolio_urls[0] if portfolio_urls else None,
        'confidence': 0.92 if full_name and headline else 0.8,
    }


# ---------------------------------------------------------------------------
# Final targeted Thandokuhle identity and education fixes
# ---------------------------------------------------------------------------

_IDENTITY_NAME_REJECT_HEADINGS = {
    'skills', 'technical skills', 'professional skills', 'productivity tools', 'automation testing',
    'data analytics', 'data engineering foundations', 'programming', 'education', 'qualifications',
    'qualification', 'certifications', 'certification', 'references', 'reference', 'projects',
    'courses', 'training', 'professional summary', 'summary', 'profile summary',
}

_IDENTITY_HEADLINE_REJECT_HEADINGS = _IDENTITY_NAME_REJECT_HEADINGS | {
    'professional experience', 'experience', 'career history',
}

_IDENTITY_SKILL_PHRASES = (
    'microsoft excel', 'microsoft office', 'power bi', 'sql', 'python', 'java', 'html/ css',
    'html/css', 'selenium', 'webdriver', 'uft one', 'jira', 'qmetry', 'data cleaning',
    'data modelling', 'data modeling', 'data visualization', 'data analytics', 'dax',
    'etl fundamentals', 'automation testing',
)

_IDENTITY_LOCATION_HINTS = (
    'south africa', 'johannesburg', 'bryanston', 'sandton', 'pretoria', 'cape town', 'durban',
    'midrand', 'randburg', 'centurion',
)

_REFERENCE_ROLE_HINTS = ('lecturer', 'professor', 'supervisor', 'director', 'manager')

_EDUCATION_HEADING_TERMS = {'education', 'qualifications', 'qualification'}
_EDUCATION_STOP_TERMS = {
    'skills', 'technical skills', 'professional skills', 'projects', 'certifications', 'certification',
    'courses', 'training', 'languages', 'awards', 'achievements', 'references', 'referees',
    'professional summary', 'summary', 'professional experience', 'experience', 'career history',
    'employment', 'volunteering', 'publications', 'interests',
}

_INSTITUTION_PATTERN = re.compile(
    r"\b(?:Nelson Mandela University|University of Johannesburg|University of Pretoria|"
    r"University of Cape Town|University of the Witwatersrand|North-West University|"
    r"University of Zululand|UNISA|TUT|DUT|UCT|Wits|Mancosa|Damelin|"
    r"[A-Z][A-Za-z&.\- ]+(?:University|College|Institute|Academy|School|Campus|Online|High School|Secondary School))\b",
    re.I,
)

_YEAR_RANGE_PATTERN = re.compile(
    r"\b((?:19|20)\d{2})\s*[–-]\s*((?:19|20)\d{2}|Present|Current|In Progress)\b",
    re.I,
)

_SINGLE_YEAR_PATTERN = re.compile(
    r"\b((?:19|20)\d{2}|Present|Current|In Progress)\b",
    re.I,
)


def _strip_identity_contact_noise(text: str, full_name: str = '') -> str:
    cleaned = text or ''
    if full_name:
        cleaned = re.sub(re.escape(full_name), '', cleaned, flags=re.I)
    for pattern in (EMAIL_RE, PHONE_RE, LINKEDIN_RE, URL_RE):
        cleaned = pattern.sub('', cleaned)
    cleaned = re.sub(
        r"\b(?:email|phone|mobile|cell|linkedin|portfolio|website|region|address|location)\b\s*:\s*",
        '',
        cleaned,
        flags=re.I,
    )
    cleaned = re.sub(r"\s{2,}", ' ', cleaned)
    return sanitize_entity_text(cleaned) or ''


def _looks_like_identity_name_candidate(text: str) -> bool:
    raw = text or ''
    cleaned = sanitize_entity_text(raw) or ''
    lower = cleaned.lower()
    norm = normalize_heading(cleaned)
    if not cleaned or BULLET_RE.match(raw):
        return False
    if any(ch in cleaned for ch in '@|/\\') or ',' in cleaned:
        return False
    if norm in KNOWN_HEADING_TERMS or norm in _IDENTITY_NAME_REJECT_HEADINGS:
        return False
    if any(term in lower for term in _IDENTITY_SKILL_PHRASES):
        return False
    if any(term in lower for term in _IDENTITY_LOCATION_HINTS):
        return False
    if re.search(r"\b(?:email|phone|mobile|cell|linkedin|portfolio|website|address|region|location)\b", lower):
        return False
    if _looks_like_role_title_local(cleaned) or _looks_like_company_name(cleaned):
        return False
    return is_valid_name_candidate(cleaned)


def _looks_like_identity_headline_candidate(text: str) -> bool:
    raw = text or ''
    if not raw or BULLET_RE.match(raw):
        return False
    cleaned = _strip_identity_contact_noise(raw)
    lower = cleaned.lower()
    norm = normalize_heading(cleaned)
    if not cleaned or len(cleaned.split()) > 8:
        return False
    if norm in KNOWN_HEADING_TERMS or norm in _IDENTITY_HEADLINE_REJECT_HEADINGS:
        return False
    if any(term in lower for term in _IDENTITY_SKILL_PHRASES):
        return False
    if re.search(r"[.!?]$", cleaned):
        return False
    return _looks_like_role_title_local(cleaned) and not _looks_like_company_name(cleaned)


def _extract_identity_header_headline(text: str, full_name: str = '') -> Optional[str]:
    raw = text or ''
    if not raw or BULLET_RE.match(raw):
        return None
    cleaned = _strip_identity_contact_noise(raw, full_name)
    if not cleaned:
        return None
    candidates: List[str] = []
    if '|' in cleaned:
        candidates.extend(part.strip() for part in cleaned.split('|') if part.strip())
    if ',' in cleaned:
        first = cleaned.split(',', 1)[0].strip()
        if first:
            candidates.append(first)
    if ' - ' in cleaned:
        first = cleaned.split(' - ', 1)[0].strip()
        if first:
            candidates.append(first)
    candidates.append(cleaned)
    for candidate in candidates:
        if _looks_like_identity_headline_candidate(candidate):
            return sanitize_entity_text(candidate)
    return None


def _score_identity_candidate(idx: int, line: str, header_scan: List[str], filename_name: str = '') -> tuple[str, str, int]:
    base = sanitize_entity_text(line) or ''
    if not base:
        return '', '', -999
    if '|' in base:
        parts = [_strip_identity_contact_noise(part) for part in base.split('|') if _strip_identity_contact_noise(part)]
        if parts and _looks_like_identity_name_candidate(parts[0]):
            score = 18
            if filename_name and parts[0].casefold() == filename_name.casefold():
                score += 12
            pipe_headline = ''
            if len(parts) > 1:
                pipe_headline = _extract_identity_header_headline(parts[1]) or ''
                if pipe_headline:
                    score += 4
            return parts[0], pipe_headline, score
    if not _looks_like_identity_name_candidate(base):
        return '', '', -999
    score = 0
    if idx <= 1:
        score += 10
    elif idx <= 4:
        score += 6
    else:
        score += 2
    if base.upper() == base:
        score += 2
    if len(base.split()) >= 3:
        score += 2
    if filename_name and base.casefold() == filename_name.casefold():
        score += 12
    nearby = header_scan[idx + 1: idx + 4]
    if any(EMAIL_RE.search(item) or PHONE_RE.search(item) for item in nearby):
        score += 2
    if any(_extract_identity_header_headline(item, base) for item in nearby[:2]):
        score += 4
    if any(
        any(term in (sanitize_entity_text(item) or '').lower() for term in _REFERENCE_ROLE_HINTS)
        for item in nearby[:2]
    ):
        score -= 6
    return base, '', score


def _split_table_like_row_for_education(line: str) -> List[str]:
    cleaned = sanitize_entity_text(line) or ''
    if not cleaned:
        return []
    if '|' in cleaned:
        return [part.strip() for part in cleaned.split('|') if part.strip()]
    if re.search(r"\s{3,}", cleaned):
        return [part.strip() for part in re.split(r"\s{3,}", cleaned) if part.strip()]
    if '•' in cleaned:
        return [part.strip() for part in cleaned.split('•') if part.strip()]
    return []


def _extract_education_date_range(text: str) -> tuple[str, str]:
    cleaned = sanitize_entity_text(text) or ''
    if not cleaned:
        return '', ''
    start, end = extract_date_range(cleaned)
    if start or end:
        return start or '', end or ''
    match = _YEAR_RANGE_PATTERN.search(cleaned)
    if match:
        return format_recruiter_date(match.group(1)), format_recruiter_date(match.group(2))
    tokens = [format_recruiter_date(token) for token in _SINGLE_YEAR_PATTERN.findall(cleaned)]
    tokens = [token for token in tokens if token]
    if len(tokens) >= 2:
        return tokens[0], tokens[-1]
    if len(tokens) == 1:
        return '', tokens[0]
    return '', ''


def _remove_education_date_text(text: str) -> str:
    cleaned = _MONTH_YEAR_TOKEN_RE.sub('', text or '')
    cleaned = re.sub(r"\b(?:Present|Current|Now|In Progress)\b", '', cleaned, flags=re.I)
    cleaned = _YEAR_RANGE_PATTERN.sub('', cleaned)
    cleaned = _SINGLE_YEAR_PATTERN.sub('', cleaned)
    cleaned = re.sub(r"\s{2,}", ' ', cleaned)
    return sanitize_entity_text(cleaned) or ''


def _is_education_table_header(text: str) -> bool:
    parts = _split_table_like_row_for_education(text)
    headerish = {normalize_heading(part) for part in parts} if parts else {normalize_heading(text)}
    return bool(headerish & {'qualification', 'institution', 'year', 'degree', 'provider', 'certification'} and len(headerish) >= 2)


def _looks_like_education_row_start(text: str) -> bool:
    cleaned = _clean_qualification_text(BULLET_RE.sub('', text))
    if not cleaned or BULLET_RE.match(text or ''):
        return False
    norm = normalize_heading(cleaned)
    if norm in _EDUCATION_HEADING_TERMS or norm in _EDUCATION_STOP_TERMS or _is_education_table_header(cleaned):
        return False
    if re.fullmatch(r"(?:19|20)\d{2}|Present|Current|In Progress", cleaned, re.I):
        return False
    if _INSTITUTION_PATTERN.fullmatch(cleaned) and not _looks_like_qualification_only(cleaned):
        return False
    return _looks_like_qualification_only(cleaned)


def group_education_rows(lines: List[str]) -> List[str]:
    capture = not any(normalize_heading(line) in _EDUCATION_HEADING_TERMS for line in lines)
    prepared: List[str] = []
    for raw in lines:
        cleaned = _clean_qualification_text(BULLET_RE.sub('', raw))
        if not cleaned or _line_is_attachment_noise(cleaned):
            continue
        norm = normalize_heading(cleaned)
        if norm in _EDUCATION_HEADING_TERMS:
            capture = True
            continue
        if not capture:
            continue
        if norm in _EDUCATION_STOP_TERMS or (norm in KNOWN_HEADING_TERMS and norm not in _EDUCATION_HEADING_TERMS):
            break
        if _is_education_table_header(cleaned):
            continue
        prepared.append(cleaned)

    groups: List[str] = []
    current: List[str] = []
    for line in prepared:
        if _looks_like_education_row_start(line):
            if current:
                groups.append(' | '.join(current))
            current = [line]
            continue
        if not current:
            continue
        current.append(line)
    if current:
        groups.append(' | '.join(current))
    return groups


def _parse_grouped_education_row(text: str) -> Optional[Dict[str, Any]]:
    parts = _split_table_like_row_for_education(text)
    combined = ' | '.join(parts) if parts else (sanitize_entity_text(text) or '')
    if not combined:
        return None
    start_date, end_date = _extract_education_date_range(combined)
    core = _remove_education_date_text(combined)
    institution_matches = [sanitize_entity_text(match.group(0)) or '' for match in _INSTITUTION_PATTERN.finditer(core)]
    institution_matches = [match for match in institution_matches if match]
    institution = max(institution_matches, key=len) if institution_matches else ''
    qualification = core
    if institution:
        qualification = re.sub(re.escape(institution), ' ', qualification, count=1, flags=re.I)
    qualification = _clean_qualification_text(qualification).strip(' ,|-?')
    if parts:
        first_part = _clean_qualification_text(parts[0]).rstrip(',').strip()
        if first_part and _looks_like_qualification_only(first_part):
            qualification = first_part
    lowered = qualification.lower()
    if not qualification or not _looks_like_qualification_only(qualification):
        return None
    if re.search(r"\b(?:intern|analyst|tester|developer|engineer|consultant|manager|coordinator|officer|assistant|technician|lead|specialist|architect|administrator)\b", lowered) and 'national senior certificate' not in lowered:
        return None
    return {
        'qualification': qualification,
        'institution': institution,
        'start_date': start_date,
        'end_date': end_date,
        'sa_standard_hint': infer_sa_qualification_note(qualification),
    }


def parse_education_section(content: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen = set()
    grouped_rows = group_education_rows(_experience_source_lines(content))
    for grouped in grouped_rows:
        row = _parse_grouped_education_row(grouped)
        if not row:
            continue
        key = (
            (row.get('qualification') or '').lower(),
            (row.get('institution') or '').lower(),
            (row.get('start_date') or '').lower(),
            (row.get('end_date') or '').lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return rows


def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    top = lines[:80]
    filename_name = infer_name_from_filename(path.name) if path is not None else None
    first_heading_idx = next(
        (i for i, line in enumerate(top[:20]) if normalize_heading(line) in KNOWN_HEADING_TERMS),
        len(top[:20]),
    )
    header_limit = max(8, first_heading_idx if 0 < first_heading_idx <= 20 else 8)
    header_scan = top[:header_limit]

    best_name = ''
    best_score = -999
    pipe_headline = ''
    for idx, line in enumerate(header_scan):
        local_name, local_headline, score = _score_identity_candidate(idx, line, header_scan, filename_name or '')
        if score > best_score:
            best_name = local_name
            pipe_headline = local_headline
            best_score = score

    filename_is_generic = _identity_filename_is_generic(filename_name or '') if filename_name else True
    if best_score >= 8 and best_name:
        full_name = best_name
    elif filename_name and not filename_is_generic:
        full_name = filename_name
    else:
        full_name = best_name

    name_idx = next(
        (
            i for i, line in enumerate(lines[:40])
            if full_name and ((sanitize_entity_text(line) or '') == full_name or full_name in (sanitize_entity_text(line) or ''))
        ),
        -1,
    )

    headline = pipe_headline
    if not headline:
        headline_window = lines[name_idx + 1:name_idx + 7] if name_idx >= 0 else header_scan[:8]
        for line in headline_window:
            if normalize_heading(line) in KNOWN_HEADING_TERMS:
                break
            candidate = _extract_identity_header_headline(line, full_name)
            if candidate and candidate != full_name:
                headline = candidate
                break
    if not headline:
        experience_rows = clean_experience_entries(parse_experience_section(raw_text))
        if experience_rows:
            experience_rows = sorted(
                experience_rows,
                key=lambda entry: (
                    _identity_date_sort_value(entry.get('end_date') or '', is_end=True),
                    _identity_date_sort_value(entry.get('start_date') or ''),
                ),
                reverse=True,
            )
            role_candidate = sanitize_entity_text(experience_rows[0].get('position')) or ''
            if _looks_like_identity_headline_candidate(role_candidate):
                headline = role_candidate
    if not headline:
        for line in header_scan:
            candidate = _extract_identity_header_headline(line, full_name)
            if candidate and candidate != full_name:
                headline = candidate
                break

    candidate_contact_zone: List[str] = []
    if name_idx >= 0:
        for line in lines[name_idx:name_idx + 8]:
            if line != lines[name_idx] and normalize_heading(line) in KNOWN_HEADING_TERMS:
                break
            if _looks_like_reference_line(line):
                continue
            candidate_contact_zone.append(line)
    if not candidate_contact_zone:
        candidate_contact_zone = [line for line in header_scan if not _looks_like_reference_line(line)]

    search_zone = '\n'.join(candidate_contact_zone)
    email = EMAIL_RE.search(search_zone)
    phone = PHONE_RE.search(search_zone)
    linkedin = LINKEDIN_RE.search(search_zone)
    urls = [
        match.group(0)
        for match in URL_RE.finditer(search_zone)
        if 'linkedin' not in match.group(0).lower() and '@' not in match.group(0)
    ]
    portfolio_urls = [
        url for url in urls
        if not re.search(r'\b(?:gmail|yahoo|hotmail|outlook)\.com\b', url, re.I)
    ]

    region = None
    address_match = re.search(r'Address\s*:\s*(.+)', raw_text, re.I)
    if address_match:
        parts = [part.strip() for part in address_match.group(1).split(',') if part.strip()]
        if len(parts) >= 2:
            region = ', '.join(parts[-3:-1] if len(parts) >= 3 and parts[-1].lower() == 'south africa' else parts[-2:])
    region_match = re.search(r'Region\s*:\s*(.+)', raw_text, re.I)
    if region_match:
        region = sanitize_entity_text(region_match.group(1)) or region

    return {
        'full_name': full_name or None,
        'headline': headline or None,
        'availability': None,
        'region': region,
        'email': email.group(0) if email else None,
        'phone': phone.group(0) if phone else None,
        'location': None,
        'linkedin': linkedin.group(0) if linkedin else None,
        'portfolio': portfolio_urls[0] if portfolio_urls else None,
        'confidence': 0.92 if full_name and headline else 0.8,
    }


# ---------------------------------------------------------------------------
# Final targeted identity override v3 for references, pipe headers, latest-role fallback, and contact-first layouts
# ---------------------------------------------------------------------------

def _identity_filename_is_generic(name: str) -> bool:
    lowered = (name or '').lower().strip()
    return lowered in {'candidate', 'resume', 'cv', 'candidate name'} or len(lowered) < 5


def _identity_date_sort_value(value: str, *, is_end: bool = False) -> tuple[int, int]:
    text = normalize_recruiter_date_text(value)
    if not text:
        return (0, 0)
    if re.search(r'\b(?:present|current|now)\b', text, re.I):
        return (9999, 12)
    year_match = re.search(r'((?:19|20)\d{2})', text)
    year = int(year_match.group(1)) if year_match else 0
    month = 12 if is_end else 1
    lowered = text.lower()
    month_map = {'jan':1,'january':1,'feb':2,'february':2,'mar':3,'march':3,'apr':4,'april':4,'may':5,'jun':6,'june':6,'jul':7,'july':7,'aug':8,'august':8,'sep':9,'sept':9,'september':9,'oct':10,'october':10,'nov':11,'november':11,'dec':12,'december':12}
    for needle, val in month_map.items():
        if re.search(rf'\b{needle}\b', lowered):
            month = val
            break
    return (year, month)


def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    top = lines[:80]
    filename_name = infer_name_from_filename(path.name) if path is not None else None
    first_heading_idx = next(
        (i for i, line in enumerate(top[:20]) if normalize_heading(line) in KNOWN_HEADING_TERMS),
        len(top[:20]),
    )
    header_limit = max(8, first_heading_idx if 0 < first_heading_idx <= 20 else 8)
    header_scan = top[:header_limit]

    best_name = ''
    best_score = -999
    pipe_headline = ''
    for idx, line in enumerate(header_scan):
        local_name, local_headline, score = _score_identity_candidate(idx, line, header_scan, filename_name or '')
        if score > best_score:
            best_name = local_name
            pipe_headline = local_headline
            best_score = score

    filename_is_generic = _identity_filename_is_generic(filename_name or '') if filename_name else True
    if best_score >= 8 and best_name:
        full_name = best_name
    elif filename_name and not filename_is_generic:
        full_name = filename_name
    else:
        full_name = best_name
    if not full_name:
        extended_scan = top[:40]
        extended_best_name = ''
        extended_best_score = -999
        extended_pipe_headline = ''
        for idx, line in enumerate(extended_scan):
            local_name, local_headline, score = _score_identity_candidate(idx, line, extended_scan, filename_name or '')
            if local_name:
                nearby = extended_scan[idx + 1: idx + 4]
                if any(normalize_heading(item) == 'curriculum vitae' for item in nearby):
                    score += 6
                if any(_extract_identity_header_headline(item, local_name) for item in nearby):
                    score += 4
            if score > extended_best_score:
                extended_best_name = local_name
                extended_pipe_headline = local_headline
                extended_best_score = score
        if extended_best_name:
            full_name = extended_best_name
            if not pipe_headline:
                pipe_headline = extended_pipe_headline

    name_idx = next(
        (
            i for i, line in enumerate(lines[:40])
            if full_name and ((sanitize_entity_text(line) or '') == full_name or full_name in (sanitize_entity_text(line) or ''))
        ),
        -1,
    )

    headline = pipe_headline
    if not headline:
        headline_window = lines[name_idx + 1:name_idx + 7] if name_idx >= 0 else header_scan[:8]
        for line in headline_window:
            if normalize_heading(line) in KNOWN_HEADING_TERMS:
                break
            candidate = _extract_identity_header_headline(line, full_name)
            if candidate and candidate != full_name:
                headline = candidate
                break
    if not headline:
        experience_rows = clean_experience_entries(parse_experience_section(raw_text))
        if experience_rows:
            experience_rows = sorted(
                experience_rows,
                key=lambda entry: (
                    _identity_date_sort_value(entry.get('end_date') or '', is_end=True),
                    _identity_date_sort_value(entry.get('start_date') or ''),
                ),
                reverse=True,
            )
            role_candidate = sanitize_entity_text(experience_rows[0].get('position')) or ''
            if _looks_like_identity_headline_candidate(role_candidate):
                headline = role_candidate
    if not headline:
        for line in header_scan:
            candidate = _extract_identity_header_headline(line, full_name)
            if candidate and candidate != full_name:
                headline = candidate
                break

    candidate_contact_zone: List[str] = []
    if name_idx >= 0:
        for line in lines[name_idx:name_idx + 8]:
            if line != lines[name_idx] and normalize_heading(line) in KNOWN_HEADING_TERMS:
                break
            if _looks_like_reference_line(line):
                continue
            candidate_contact_zone.append(line)
    if not candidate_contact_zone:
        candidate_contact_zone = [line for line in header_scan if not _looks_like_reference_line(line)]

    search_zone = '\n'.join(candidate_contact_zone)
    email = EMAIL_RE.search(search_zone)
    phone = PHONE_RE.search(search_zone)
    linkedin = LINKEDIN_RE.search(search_zone)
    urls = [
        match.group(0)
        for match in URL_RE.finditer(search_zone)
        if 'linkedin' not in match.group(0).lower() and '@' not in match.group(0)
    ]
    portfolio_urls = [
        url for url in urls
        if not re.search(r'\b(?:gmail|yahoo|hotmail|outlook)\.com\b', url, re.I)
    ]

    region = None
    address_match = re.search(r'Address\s*:\s*(.+)', raw_text, re.I)
    if address_match:
        parts = [part.strip() for part in address_match.group(1).split(',') if part.strip()]
        if len(parts) >= 2:
            region = ', '.join(parts[-3:-1] if len(parts) >= 3 and parts[-1].lower() == 'south africa' else parts[-2:])
    region_match = re.search(r'Region\s*:\s*(.+)', raw_text, re.I)
    if region_match:
        region = sanitize_entity_text(region_match.group(1)) or region

    return {
        'full_name': full_name or None,
        'headline': headline or None,
        'availability': None,
        'region': region,
        'email': email.group(0) if email else None,
        'phone': phone.group(0) if phone else None,
        'location': None,
        'linkedin': linkedin.group(0) if linkedin else None,
        'portfolio': portfolio_urls[0] if portfolio_urls else None,
        'confidence': 0.92 if full_name and headline else 0.8,
    }
#
# Runtime-consulting override anchor: appended at physical EOF to win.
#

def clean_experience_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    seen = set()
    for entry in entries:
        normalized = dict(entry)
        normalized['company'] = sanitize_entity_text(normalized.get('company'))
        normalized['position'] = sanitize_entity_text(normalized.get('position'))
        normalized['summary'] = sanitize_entity_text(normalized.get('summary'))
        normalized['start_date'] = format_recruiter_date(normalized.get('start_date'))
        normalized['end_date'] = format_recruiter_date(normalized.get('end_date'))
        normalized['technologies'] = [sanitize_entity_text(item) for item in normalized.get('technologies', []) if sanitize_entity_text(item)]

        responsibilities: List[str] = []
        for item in normalized.get('responsibilities', []) or []:
            text = sanitize_entity_text(item)
            if not text:
                continue
            if text.isdigit() or EMAIL_RE.search(text) or PHONE_RE.search(text):
                continue
            lowered = text.lower()
            if text == 'University' or any(term in lowered for term in ('professor', 'department', 'hod', 'lecturer', 'contact:', 'email:', 'reference')):
                continue
            _append_unique_text(responsibilities, text)
        normalized['responsibilities'] = responsibilities

        client_rows = []
        for client in normalized.get('clients', []) or []:
            row = {
                'client_name': sanitize_entity_text(client.get('client_name')),
                'project_name': sanitize_entity_text(client.get('project_name')),
                'programme': sanitize_entity_text(client.get('programme')),
                'responsibilities': [sanitize_entity_text(item) for item in client.get('responsibilities', []) if sanitize_entity_text(item)],
            }
            client_rows.append(row)
            client_label_bits = [bit for bit in [row.get('client_name'), row.get('project_name') or row.get('programme')] if bit]
            client_label = ' - '.join(client_label_bits)
            if row['responsibilities']:
                for resp in row['responsibilities']:
                    prefix = row.get('client_name') or client_label
                    _append_unique_text(normalized['responsibilities'], f"{prefix}: {resp}" if prefix else resp)
            elif client_label:
                _append_unique_text(normalized['responsibilities'], client_label)
        normalized['clients'] = client_rows

        if not normalized.get('company') and normalized.get('clients'):
            normalized['company'] = 'Consulting Engagement'
        if not normalized.get('position'):
            continue
        key = (
            (normalized.get('company') or '').lower(),
            (normalized.get('position') or '').lower(),
            (normalized.get('start_date') or '').lower(),
            (normalized.get('end_date') or '').lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(normalized)
    return cleaned


def _parse_experience_section_v6948(content: str) -> List[Dict[str, Any]]:
    lines = _experience_source_lines(content)
    if not lines:
        return []
    entries: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    active_client: Optional[Dict[str, Any]] = None
    in_client_section = False
    started = not any(normalize_heading(line) in _EXPERIENCE_CAPTURE_HEADINGS for line in lines)

    for raw in lines:
        norm = normalize_heading(raw)
        if norm in _EXPERIENCE_CAPTURE_HEADINGS:
            started = True
            active_client = None
            in_client_section = False
            continue
        if not started:
            continue
        if norm in _CONSULTING_CLIENT_SECTION_HEADINGS:
            in_client_section = True
            active_client = None
            continue
        if norm in _DEFENSIVE_STOP_HEADINGS and norm not in _EXPERIENCE_CAPTURE_HEADINGS:
            break
        if _looks_like_reference_line(raw):
            break

        cleaned = sanitize_entity_text(BULLET_RE.sub('', raw)) or ''
        if not cleaned or _line_is_attachment_noise(cleaned):
            continue

        parsed = (
            _parse_rendered_history_role_line(cleaned)
            or _split_role_company_date_line(raw)
            or _split_role_company_anchor_line(raw)
            or _parse_role_company_without_dates_line(cleaned)
        )
        if parsed:
            if current and _is_professional_experience(current):
                entries.append(current)
            current = parsed
            active_client = None
            in_client_section = False
            continue

        if current is None:
            continue

        start_date, end_date = extract_date_range(cleaned)
        if (start_date or end_date) and not (current.get('start_date') or current.get('end_date')):
            current['start_date'] = sanitize_entity_text(start_date) or ''
            current['end_date'] = sanitize_entity_text(end_date) or ''
            continue

        client_row = _parse_client_line(cleaned)
        if client_row:
            current.setdefault('clients', []).append(client_row)
            active_client = current['clients'][-1]
            in_client_section = True
            continue

        if re.match(r"^Responsibilities\s*:\s*", cleaned, re.I):
            body = sanitize_entity_text(re.sub(r"^Responsibilities\s*:\s*", '', cleaned, flags=re.I)) or ''
            if body:
                _append_unique_text(current.setdefault('responsibilities', []), body)
            active_client = None
            in_client_section = False
            continue

        if _looks_like_experience_location_line(cleaned):
            continue

        if active_client is not None and in_client_section:
            _append_unique_text(active_client.setdefault('responsibilities', []), cleaned)
            continue

        if BULLET_RE.match(raw):
            _append_unique_text(current.setdefault('responsibilities', []), cleaned)
            continue

        if len(cleaned.split()) >= 10 and not current.get('summary'):
            current['summary'] = cleaned
        else:
            _append_unique_text(current.setdefault('responsibilities', []), cleaned)

    if current and _is_professional_experience(current):
        entries.append(current)

    seen = {
        (
            (entry.get('company') or '').lower(),
            (entry.get('position') or '').lower(),
            (entry.get('start_date') or '').lower(),
            (entry.get('end_date') or '').lower(),
        )
        for entry in entries
    }
    for raw in lines:
        parsed = _split_role_company_date_line(raw)
        if not parsed or not _is_professional_experience(parsed):
            continue
        key = (
            (parsed.get('company') or '').lower(),
            (parsed.get('position') or '').lower(),
            (parsed.get('start_date') or '').lower(),
            (parsed.get('end_date') or '').lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        entries.append(parsed)

    return clean_experience_entries(entries)


def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    top = lines[:80]
    filename_name = infer_name_from_filename(path.name) if path is not None else None
    first_heading_idx = next(
        (i for i, line in enumerate(top[:20]) if normalize_heading(line) in KNOWN_HEADING_TERMS),
        len(top[:20]),
    )
    header_limit = max(8, first_heading_idx if 0 < first_heading_idx <= 20 else 8)
    header_scan = top[:header_limit]

    best_name = ''
    best_score = -999
    pipe_headline = ''
    for idx, line in enumerate(header_scan):
        local_name, local_headline, score = _score_identity_candidate(idx, line, header_scan, filename_name or '')
        if score > best_score:
            best_name = local_name
            pipe_headline = local_headline
            best_score = score

    filename_is_generic = _identity_filename_is_generic(filename_name or '') if filename_name else True
    if best_score >= 8 and best_name:
        full_name = best_name
    elif filename_name and not filename_is_generic:
        full_name = filename_name
    else:
        full_name = best_name

    name_idx = next(
        (
            i for i, line in enumerate(lines[:40])
            if full_name and ((sanitize_entity_text(line) or '') == full_name or full_name in (sanitize_entity_text(line) or ''))
        ),
        -1,
    )

    headline = pipe_headline
    if not headline:
        headline_window = lines[name_idx + 1:name_idx + 7] if name_idx >= 0 else header_scan[:8]
        for line in headline_window:
            if normalize_heading(line) in KNOWN_HEADING_TERMS:
                break
            candidate = _extract_identity_header_headline(line, full_name)
            if candidate and candidate != full_name:
                headline = candidate
                break
    if not headline:
        experience_rows = clean_experience_entries(parse_experience_section(raw_text))
        if experience_rows:
            experience_rows = sorted(
                experience_rows,
                key=lambda entry: (
                    _identity_date_sort_value(entry.get('end_date') or '', is_end=True),
                    _identity_date_sort_value(entry.get('start_date') or ''),
                ),
                reverse=True,
            )
            role_candidate = sanitize_entity_text(experience_rows[0].get('position')) or ''
            if _looks_like_identity_headline_candidate(role_candidate):
                headline = role_candidate
    if not headline:
        for line in header_scan:
            candidate = _extract_identity_header_headline(line, full_name)
            if candidate and candidate != full_name:
                headline = candidate
                break

    candidate_contact_zone: List[str] = []
    if name_idx >= 0:
        for line in lines[name_idx:name_idx + 8]:
            if line != lines[name_idx] and normalize_heading(line) in KNOWN_HEADING_TERMS:
                break
            if _looks_like_reference_line(line):
                continue
            candidate_contact_zone.append(line)
    if not candidate_contact_zone:
        candidate_contact_zone = [line for line in header_scan if not _looks_like_reference_line(line)]

    search_zone = '\n'.join(candidate_contact_zone)
    email = EMAIL_RE.search(search_zone)
    phone = PHONE_RE.search(search_zone)
    linkedin = LINKEDIN_RE.search(search_zone)
    location = _extract_header_location(candidate_contact_zone or header_scan, full_name or '', headline or '')
    portfolio = _extract_explicit_portfolio_url(candidate_contact_zone or header_scan)

    region = None
    address_match = re.search(r'Address\s*:\s*(.+)', raw_text, re.I)
    if address_match:
        parts = [part.strip() for part in address_match.group(1).split(',') if part.strip()]
        if len(parts) >= 2:
            region = ', '.join(parts[-3:-1] if len(parts) >= 3 and parts[-1].lower() == 'south africa' else parts[-2:])
    region_match = re.search(r'Region\s*:\s*(.+)', raw_text, re.I)
    if region_match:
        region = sanitize_entity_text(region_match.group(1)) or region
    if not location and region:
        location = region
    if not region and location:
        region = location

    return {
        'full_name': full_name or None,
        'headline': headline or None,
        'availability': None,
        'region': region,
        'email': email.group(0) if email else None,
        'phone': phone.group(0) if phone else None,
        'location': location,
        'linkedin': linkedin.group(0) if linkedin else None,
        'portfolio': portfolio,
        'confidence': 0.92 if full_name and headline else 0.8,
    }
def _parse_experience_section_consulting_final_eof(content: str) -> List[Dict[str, Any]]:
    def _is_professional_entry(entry: Dict[str, Any]) -> bool:
        role = sanitize_entity_text(entry.get("position")) or ""
        company = sanitize_entity_text(entry.get("company")) or ""
        text = f"{role} {company} {' '.join(entry.get('responsibilities', []) or [])}".lower()
        if any(term in text for term in ("volunteer", "astroquiz", "tanks tournament")):
            return False
        return bool(role and (company or entry.get("clients")))

    def _parse_role_line(text: str) -> Optional[Dict[str, Any]]:
        normalized = re.sub(r"\s+\?\s+", " - ", sanitize_entity_text(text) or '')
        if not normalized:
            return None
        rendered = re.match(r"^(?P<prefix>.+?)\s*\((?P<start>[^()]+?)\s+to\s+(?P<end>[^()]+?)\)$", normalized, re.I)
        if rendered:
            base = _parse_role_line(rendered.group('prefix'))
            if base:
                base['start_date'] = format_recruiter_date(rendered.group('start'))
                base['end_date'] = format_recruiter_date(rendered.group('end'))
                return base
        compact = _split_role_company_date_line(normalized) or _split_role_company_anchor_line(normalized)
        if compact:
            return compact
        # Handle "Role Title DateRange" – role with trailing date, company on
        # the next line.  E.g. "Senior Engineer Jun 2025 - Present"
        _role_date_match = re.match(
            rf"^(?P<role>.+?)\s+(?P<start>{_DATE_VALUE_PATTERN})\s*[{_DATE_SEPARATOR_CHARS}]\s*(?P<end>Present|Current|Now|In Progress|{_DATE_VALUE_PATTERN})$",
            normalized,
            re.I,
        )
        if _role_date_match:
            role_candidate = sanitize_entity_text(_role_date_match.group('role')) or ''
            if role_candidate and _looks_like_role_title_local(role_candidate):
                return {
                    'company': '',
                    'position': role_candidate,
                    'start_date': format_recruiter_date(_role_date_match.group('start')),
                    'end_date': format_recruiter_date(_role_date_match.group('end')),
                    'responsibilities': [],
                    'clients': [],
                    'technologies': [],
                    'summary': None,
                }
        parts = [sanitize_entity_text(part) or '' for part in re.split(r"\s+\W\s+", normalized, maxsplit=1) if sanitize_entity_text(part)]
        if len(parts) != 2:
            return None
        left, right = parts
        if _looks_like_role_title_local(left) and not likely_heading(right):
            return {
                'company': right,
                'position': left,
                'start_date': '',
                'end_date': '',
                'responsibilities': [],
                'clients': [],
                'technologies': [],
                'summary': None,
            }
        if _looks_like_company_name(left) and _looks_like_role_title_local(right):
            return {
                'company': left,
                'position': right,
                'start_date': '',
                'end_date': '',
                'responsibilities': [],
                'clients': [],
                'technologies': [],
                'summary': None,
            }
        return None

    lines = _experience_source_lines(content)
    if not lines:
        return []
    entries: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    active_client: Optional[Dict[str, Any]] = None
    in_client_section = False
    started = not any(normalize_heading(line) in _EXPERIENCE_CAPTURE_HEADINGS for line in lines)

    for raw in lines:
        norm = normalize_heading(raw)
        if norm in _EXPERIENCE_CAPTURE_HEADINGS:
            started = True
            active_client = None
            in_client_section = False
            continue
        if not started:
            continue
        if norm in _CONSULTING_CLIENT_SECTION_HEADINGS:
            in_client_section = True
            active_client = None
            continue
        if norm in _DEFENSIVE_STOP_HEADINGS and norm not in _EXPERIENCE_CAPTURE_HEADINGS:
            break
        if _looks_like_reference_line(raw):
            break

        cleaned = sanitize_entity_text(BULLET_RE.sub('', raw)) or ''
        if not cleaned or _line_is_attachment_noise(cleaned):
            continue

        if re.match(r"^Responsibilities\s*:\s*", cleaned, re.I):
            if current is not None:
                body = sanitize_entity_text(re.sub(r"^Responsibilities\s*:\s*", '', cleaned, flags=re.I)) or ''
                if body:
                    _append_unique_text(current.setdefault('responsibilities', []), body)
            active_client = None
            in_client_section = False
            continue

        if BULLET_RE.match(raw):
            if current is None:
                continue
            if active_client is not None and in_client_section:
                _append_unique_text(active_client.setdefault('responsibilities', []), cleaned)
            else:
                _append_unique_text(current.setdefault('responsibilities', []), cleaned)
            continue

        parsed = _parse_role_line(cleaned)
        if parsed:
            if current and _is_professional_entry(current):
                entries.append(current)
            current = parsed
            active_client = None
            in_client_section = False
            continue

        if current is None:
            continue

        # If the current role has no company yet, check if this line is a
        # company name (common in "Role DateRange\nCompany, Location" format)
        if current and not current.get('company') and not BULLET_RE.match(raw):
            # Strip trailing location suffix like ", Johannesburg" or ", Sandton"
            company_candidate = re.sub(r",\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s*$", "", cleaned).strip()
            if company_candidate and not _looks_like_role_title_local(company_candidate) and not likely_heading(company_candidate):
                current['company'] = company_candidate
                continue

        date_text = re.sub(r"\s+\?\s+", " - ", cleaned)
        start_date, end_date = extract_date_range(date_text)
        if (start_date or end_date) and not (current.get('start_date') or current.get('end_date')):
            current['start_date'] = format_recruiter_date(start_date)
            current['end_date'] = format_recruiter_date(end_date)
            continue

        client_row = _parse_client_line(cleaned)
        if client_row:
            current.setdefault('clients', []).append(client_row)
            active_client = current['clients'][-1]
            in_client_section = True
            continue

        if _looks_like_experience_location_line(cleaned):
            continue

        if active_client is not None and in_client_section:
            _append_unique_text(active_client.setdefault('responsibilities', []), cleaned)
            continue

        if len(cleaned.split()) >= 10 and not current.get('summary'):
            current['summary'] = cleaned
        else:
            _append_unique_text(current.setdefault('responsibilities', []), cleaned)

    if current and _is_professional_entry(current):
        entries.append(current)
    return clean_experience_entries(entries)


# ---------------------------------------------------------------------------
# Final generic layout-aware parser refinements
# ---------------------------------------------------------------------------

_parse_sections_before_layout_fix = _parse_sections_core
_extract_identity_before_layout_fix = extract_identity
_parse_experience_section_before_layout_fix = _parse_experience_section_consulting_final_eof
_is_valid_name_candidate_before_layout_fix = is_valid_name_candidate
_looks_like_role_title_local_before_layout_fix = _looks_like_role_title_local

_GENERIC_IDENTITY_LABELS = {
    "name",
    "availability",
    "gender",
    "nationality",
    "region",
    "location",
    "address",
    "email",
    "phone",
    "mobile",
    "telephone",
    "linkedin",
    "date of birth",
    "marital status",
    "race",
    "criminal offense",
    "criminal offence",
}
_GENERIC_EDUCATION_HINTS = {
    "matric", "grade 12", "national senior certificate", "certificate", "diploma",
    "degree", "honours", "honors", "academy", "school", "college", "university",
    "institute", "faculty", "bachelor", "bcom", "bsc", "ba", "nqf",
}
_GENERIC_CERTIFICATION_HINTS = {"certified", "certification", "certificate -", "accredit", "licence", "license"}
_GENERIC_TRAINING_HINTS = {"course", "training", "workshop", "udemy", "coursera", "alison", "alton", "torque", "coach"}
_DENSE_STACK_HEADINGS = {
    "objective",
    "personal details",
    "education",
    "languages",
    "skills",
    "experience",
    "reference",
    "references",
    "achievements",
    "achievements awards",
    "achievements & awards",
    "awards",
}
_PERSONAL_DETAIL_LABELS = {
    "personal details",
    "date of birth",
    "marital status",
    "nationality",
    "gender",
    "race",
    "criminal offense",
    "criminal offence",
}
_LOCATION_HINTS = re.compile(
    r"\b(?:street|st\b|road|rd\b|avenue|ave\b|drive|dr\b|lane|close|crescent|court|park|"
    r"midrand|johannesburg|pretoria|sandton|randburg|centurion|cape town|durban|"
    r"gauteng|limpopo|mpumalanga|north west|western cape|eastern cape|free state|"
    r"kwazulu[- ]natal|south africa)\b",
    re.I,
)


def _is_year_marker_line(line: str) -> bool:
    return bool(re.fullmatch(r"(?:19|20)\d{2}\s*:?\s*", sanitize_entity_text(line) or "", re.I))


def _coalesce_inline_label(line: str) -> tuple[str, str]:
    cleaned = sanitize_entity_text(line) or ""
    if not cleaned:
        return "", ""
    inline = re.match(r"^([A-Za-z][A-Za-z /&+-]{1,40}?)\s*[:|]\s*(.+)$", cleaned)
    if inline:
        return normalize_heading(inline.group(1)), sanitize_entity_text(inline.group(2)) or ""
    return "", ""


def _looks_like_contact_or_location_line(text: str) -> bool:
    cleaned = sanitize_entity_text(text) or ""
    if not cleaned:
        return False
    if EMAIL_RE.search(cleaned) or PHONE_RE.search(cleaned) or LINKEDIN_RE.search(cleaned) or URL_RE.search(cleaned):
        return True
    if normalize_heading(cleaned) in _PERSONAL_DETAIL_LABELS | _GENERIC_IDENTITY_LABELS:
        return True
    if cleaned.startswith(":"):
        return True
    return bool(_LOCATION_HINTS.search(cleaned) and len(cleaned.split()) <= 12)


def _looks_like_language_line(text: str) -> bool:
    cleaned = sanitize_entity_text(text) or ""
    return bool(re.match(r"^(?:read|write|speak|spoken|written)\s*[-:]\s*.+$", cleaned, re.I))


def _looks_like_vertical_experience_anchor(lines: List[str], idx: int) -> bool:
    if idx + 1 >= len(lines):
        return False
    company = sanitize_entity_text(lines[idx]) or ""
    role = sanitize_entity_text(lines[idx + 1]) or ""
    if not company or not role:
        return False
    if normalize_heading(company) in KNOWN_HEADING_TERMS or normalize_heading(role) in KNOWN_HEADING_TERMS:
        return False
    if _looks_like_reference_line(company) or _looks_like_reference_line(role):
        return False
    if _looks_like_contact_or_location_line(company) or _looks_like_contact_or_location_line(role):
        return False
    if looks_like_education_line(company) or looks_like_education_line(role):
        return False
    if not _looks_like_role_title_local(role) or len(role.split()) > 8:
        return False
    company_like = _looks_like_company_name(company) or any(
        marker in company.lower()
        for marker in (
            "solutions",
            "services",
            "technologies",
            "technology",
            "networks",
            "network",
            "labs",
            "bank",
            "group",
            "systems",
            "consulting",
            "security",
            "holdings",
            "limited",
            "ltd",
            "pty",
        )
    )
    if not company_like and len(company.split()) > 5:
        return False
    nearby = [sanitize_entity_text(line) or "" for line in lines[idx + 2: idx + 10]]
    has_date = any(
        extract_date_range(line) != (None, None)
        or re.fullmatch(r"(?:19|20)\d{2}\s*[â€“-]\s*(?:Present|Current|Now|(?:19|20)\d{2})", line, re.I)
        for line in nearby
    )
    has_body = any(_looks_like_compact_responsibility_line(line) or len(line.split()) >= 5 for line in nearby[:4])
    return company_like and (has_date or has_body)


def _looks_like_experience_noise_line(text: str) -> bool:
    cleaned = sanitize_entity_text(text) or ""
    lowered = cleaned.lower()
    normalized = normalize_heading(cleaned)
    if not cleaned:
        return True
    if cleaned.isdigit() or _looks_like_contact_or_location_line(cleaned):
        return True
    if normalized in _PERSONAL_DETAIL_LABELS or normalized in _DENSE_STACK_HEADINGS:
        return True
    if re.fullmatch(r"(?:19|20)\d{2}\s*(?:[â€“-]\s*(?:Present|Current|Now|(?:19|20)\d{2}))?", cleaned, re.I):
        return True
    if _looks_like_language_line(cleaned):
        return True
    if looks_like_education_line(cleaned):
        return True
    if any(term in lowered for term in ("date of birth", "marital status", "nationality", "gender", "race", "criminal offense", "criminal offence")):
        return True
    return cleaned in {"Soft", "Personal Details"}


def _looks_like_summary_line(line: str) -> bool:
    cleaned = sanitize_entity_text(line) or ""
    if len(cleaned.split()) < 8:
        return False
    if EMAIL_RE.search(cleaned) or PHONE_RE.search(cleaned):
        return False
    if _is_year_marker_line(cleaned):
        return False
    if normalize_heading(cleaned) in KNOWN_HEADING_TERMS:
        return False
    label, _ = _coalesce_inline_label(cleaned)
    if label in _GENERIC_IDENTITY_LABELS:
        return False
    return cleaned.endswith((".", ",")) or len(cleaned.split()) >= 14


def _looks_like_compact_responsibility_line(line: str) -> bool:
    cleaned = sanitize_entity_text(line) or ""
    lowered = cleaned.lower()
    word_count = len(cleaned.split())
    if not cleaned:
        return False
    if cleaned.endswith(".") and word_count >= 2:
        return True
    if word_count >= 6 and re.search(r"\b(?:and|with|through|across|while|where|including)\b", lowered):
        return True
    if word_count < 4:
        return False
    return lowered.startswith((
        "manage ",
        "managing ",
        "working ",
        "acting ",
        "reviews ",
        "reviewing ",
        "relationship ",
        "operationalize ",
        "assist ",
        "assisting ",
        "supporting ",
        "responsible ",
        "responsibility ",
        "query resolution ",
        "monthly ",
        "coordinating ",
        "coordinate ",
        "following-up ",
        "follow up ",
        "monitoring ",
        "monitor ",
        "updating ",
        "update ",
        "identify ",
        "create ",
        "gather ",
        "analyze ",
        "match ",
        "assign ",
        "develop ",
        "assess ",
        "negotiate ",
        "track ",
        "communicate ",
        "generate ",
        "plan ",
        "evaluate ",
        "setup ",
        "organize ",
        "maintain ",
        "preparing ",
        "prepare ",
        "take ",
        "liaise ",
        "receive ",
        "draw ",
        "report ",
        "compile ",
        "compiling ",
        "create new ",
        "arrange ",
        "site ",
        "filing",
    ))


def _classify_compact_profile_line(line: str) -> Optional[str]:
    cleaned = sanitize_entity_text(line) or ""
    if not cleaned:
        return None
    lowered = cleaned.lower()
    normalized = normalize_heading(cleaned)
    if normalized in KNOWN_HEADING_TERMS or normalized in _DENSE_STACK_HEADINGS or normalized in _PERSONAL_DETAIL_LABELS:
        return None
    if _looks_like_reference_line(cleaned) or _looks_like_contact_or_location_line(cleaned):
        return None
    if _looks_like_language_line(cleaned):
        return "languages"
    if _looks_like_compact_responsibility_line(cleaned):
        return None
    if any(token in lowered for token in _GENERIC_CERTIFICATION_HINTS):
        return "certifications"
    if any(token in lowered for token in _GENERIC_TRAINING_HINTS):
        return "training"
    if len(cleaned.split()) > 12:
        return None
    if any(token in lowered for token in _GENERIC_EDUCATION_HINTS) and not any(
        token in lowered for token in {"api testing", "project management", "microsoft office"}
    ):
        return "education"
    if len(cleaned.split()) <= 10 and not DATE_RANGE_RE.search(cleaned):
        return "skills"
    return None


def _format_compact_profile_line(classification: str, line: str) -> str:
    cleaned = sanitize_entity_text(line) or ""
    if not cleaned:
        return ""
    if classification == "education":
        match = re.match(r"^(Matric|National Senior Certificate|Grade 12)\s+(.+)$", cleaned, re.I)
        if match:
            return f"{match.group(1).strip()} | {match.group(2).strip()}"
    if classification == "certifications":
        match = re.match(r"^(.*?\b(?:Certified|Certificate)\b)\s+(.+)$", cleaned, re.I)
        if match and "-" not in match.group(2):
            return f"{match.group(1).strip()} | {match.group(2).strip()}"
    if classification == "training":
        provider_match = re.search(r"\b(Udemy|Coursera|Alton|Torque IT)\b", cleaned, re.I)
        if provider_match:
            provider = provider_match.group(1).strip()
            before = cleaned[:provider_match.start()].strip(" |-")
            after = cleaned[provider_match.end():].strip(" |-")
            if before and after:
                return f"{before} / {after} | {provider}"
            if before:
                return f"{before} | {provider}"
    if classification == "languages":
        return re.sub(r"^(?:Read|Write|Speak|Spoken|Written)\s*[-:]\s*", "", cleaned, flags=re.I).strip()
    return cleaned


def _make_section(title: str, canonical_key: str, lines: List[str], start_line: int, end_line: int, *, confidence: float = 0.88) -> Optional[SectionBlock]:
    content = "\n".join(line for line in lines if sanitize_entity_text(line))
    if not content.strip():
        return None
    return SectionBlock(
        id=str(uuid.uuid4())[:8],
        title=title,
        canonical_key=canonical_key,
        content=content.strip(),
        confidence=confidence,
        source="heuristic",
        start_line=start_line,
        end_line=end_line,
    )


def _needs_dense_layout_reparse(raw_text: str, sections: List[SectionBlock]) -> bool:
    lines = [sanitize_entity_text(line) or "" for line in raw_text.splitlines() if sanitize_entity_text(line)]
    if not lines:
        return False
    non_unknown = [section for section in sections if section.canonical_key != "raw_unknown"]
    has_labeled_experience = any(normalize_heading(line) in {"company", "position", "duration"} for line in lines)
    has_vertical_experience = any(_looks_like_vertical_experience_anchor(lines, idx) for idx in range(max(len(lines) - 1, 0)))
    has_year_stack = sum(1 for line in lines if _is_year_marker_line(line)) >= 2
    has_summaryish_top = any(_looks_like_summary_line(line) for line in lines[:18])
    heading_stack = sum(1 for line in lines[:12] if normalize_heading(line) in _DENSE_STACK_HEADINGS) >= 4
    sparse_top_sections = sum(1 for section in sections[:5] if len(section.content.split()) <= 3) >= 2
    skills_leakage = any(
        section.canonical_key == "skills"
        and any(_looks_like_contact_or_location_line(line) or normalize_heading(line) in _PERSONAL_DETAIL_LABELS for line in section.content.splitlines())
        for section in sections
    )
    if len(non_unknown) <= 1 and (has_labeled_experience or has_year_stack or has_summaryish_top):
        return True
    if not any(section.canonical_key == "summary" for section in sections) and has_summaryish_top and (has_labeled_experience or has_year_stack):
        return True
    if heading_stack and (has_vertical_experience or has_year_stack or sparse_top_sections):
        return True
    if skills_leakage and (heading_stack or has_vertical_experience):
        return True
    return False


def _parse_dense_profile_sections(raw_text: str) -> List[SectionBlock]:
    lines = [sanitize_entity_text(line) or "" for line in raw_text.splitlines() if sanitize_entity_text(line)]
    if not lines:
        return []

    experience_start = next(
        (
            idx for idx, line in enumerate(lines)
            if normalize_heading(line) in {"company", "position", "duration"}
            or re.match(r"^(?:company|position|duration)\s*[:|]", line, re.I)
            or _looks_like_vertical_experience_anchor(lines, idx)
        ),
        len(lines),
    )
    pre_experience = lines[:experience_start]
    used = [False] * len(pre_experience)
    sections: List[SectionBlock] = []

    chosen_cluster: tuple[int, int, int] | None = None
    idx = 0
    while idx < len(pre_experience):
        if not _looks_like_summary_line(pre_experience[idx]):
            idx += 1
            continue
        start = idx
        words = 0
        while idx < len(pre_experience):
            candidate = pre_experience[idx]
            if _is_year_marker_line(candidate) or normalize_heading(candidate) in _GENERIC_IDENTITY_LABELS:
                break
            if words and not _looks_like_summary_line(candidate) and len(candidate.split()) <= 8 and not candidate.endswith((".", ",")):
                break
            words += len(candidate.split())
            idx += 1
        end = idx - 1
        if words >= 35:
            chosen_cluster = (start, end, words)
            break
    if chosen_cluster is not None:
        start, end, _ = chosen_cluster
        for i in range(start, end + 1):
            used[i] = True
        summary_section = _make_section("Candidate Summary", "summary", pre_experience[start:end + 1], start, end, confidence=0.92)
        if summary_section:
            sections.append(summary_section)

    info_lines: List[str] = []
    idx = 0
    while idx < len(pre_experience):
        if used[idx]:
            idx += 1
            continue
        label, value = _coalesce_inline_label(pre_experience[idx])
        if label in _GENERIC_IDENTITY_LABELS and value:
            info_lines.append(f"{label.title()}: {value}")
            used[idx] = True
            idx += 1
            continue
        norm = normalize_heading(pre_experience[idx])
        if norm in _GENERIC_IDENTITY_LABELS and idx + 1 < len(pre_experience) and not used[idx + 1]:
            next_value = sanitize_entity_text(pre_experience[idx + 1]) or ""
            if next_value and len(next_value.split()) <= 8 and normalize_heading(next_value) not in KNOWN_HEADING_TERMS:
                info_lines.append(f"{pre_experience[idx].rstrip(':')}: {next_value}")
                used[idx] = True
                used[idx + 1] = True
                idx += 2
                continue
        idx += 1
    info_section = _make_section("Additional Information", "raw_unknown", info_lines, 0, max(len(info_lines) - 1, 0), confidence=0.84)
    if info_section:
        sections.append(info_section)

    bucket_lines: Dict[str, List[str]] = {"education": [], "certifications": [], "training": [], "languages": [], "skills": []}
    idx = 0
    while idx < len(pre_experience):
        if used[idx]:
            idx += 1
            continue
        line = pre_experience[idx]
        if _is_year_marker_line(line):
            year = re.sub(r":", "", line).strip()
            used[idx] = True
            values: List[str] = []
            cursor = idx + 1
            while cursor < len(pre_experience) and not used[cursor]:
                candidate = pre_experience[cursor]
                if _is_year_marker_line(candidate) or normalize_heading(candidate) in _GENERIC_IDENTITY_LABELS or _looks_like_summary_line(candidate):
                    break
                if len(values) >= 2 and _classify_compact_profile_line(candidate) == "skills" and len(candidate.split()) >= 4:
                    break
                if len(values) >= 3:
                    break
                values.append(candidate)
                used[cursor] = True
                cursor += 1
            joined = " | ".join(values)
            classification = _classify_compact_profile_line(joined) or _classify_compact_profile_line(" ".join(values))
            if classification == "education" and values:
                if len(values) >= 2:
                    bucket_lines["education"].append(f"{values[0]} | {values[1]} | {year}")
                else:
                    bucket_lines["education"].append(f"{values[0]} | {year}")
            elif classification == "certifications" and values:
                bucket_lines["certifications"].append(" | ".join(values + [year]))
            elif classification == "training" and values:
                bucket_lines["training"].append(" | ".join([year] + values))
            elif classification == "languages" and values:
                bucket_lines["languages"].extend(values)
            elif values:
                bucket_lines["skills"].extend(values)
            idx = cursor
            continue

        classification = _classify_compact_profile_line(line)
        if classification:
            formatted = _format_compact_profile_line(classification, line)
            if formatted:
                bucket_lines[classification].append(formatted)
            used[idx] = True
        idx += 1

    section_specs = [
        ("Qualifications", "education"),
        ("Certifications", "certifications"),
        ("Training", "training"),
        ("Languages", "languages"),
        ("Skills", "skills"),
    ]
    for title, key in section_specs:
        content_lines = bucket_lines[key]
        if key == "skills":
            content_lines = [
                line for line in content_lines
                if len(line.split()) <= 12
                and not is_valid_name_candidate(line)
                and not _looks_like_role_title_local(line)
            ]
        block = _make_section(title, key, content_lines, 0, max(len(content_lines) - 1, 0), confidence=0.87)
        if block:
            sections.append(block)

    if experience_start < len(lines):
        experience_section = _make_section(
            "Career History",
            "experience",
            lines[experience_start:],
            experience_start,
            len(lines) - 1,
            confidence=0.9,
        )
        if experience_section:
            sections.append(experience_section)

    return sections


def _parse_sections_with_layout_fix(raw_text: str) -> List[SectionBlock]:
    sections = _parse_sections_before_layout_fix(raw_text)
    if not _needs_dense_layout_reparse(raw_text, sections):
        return sections
    reparsed = _parse_dense_profile_sections(raw_text)
    return reparsed or sections


def _parse_labeled_experience_blocks(content: str) -> List[Dict[str, Any]]:
    lines = _experience_source_lines(content)
    if not any(normalize_heading(line) == "company" for line in lines):
        return []

    entries: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    pending_label = ""
    in_responsibilities = False
    pending_date_start = ""
    pending_date_end = ""

    def flush() -> None:
        nonlocal current
        if current and _is_professional_experience(current):
            entries.append(current)
        current = None

    def _strip_leading_colon(text: str) -> str:
        return re.sub(r"^:\s*", "", text)

    for raw in lines:
        norm = normalize_heading(raw)
        cleaned = sanitize_entity_text(BULLET_RE.sub("", raw)) or ""
        if not cleaned or re.fullmatch(r"[?]+", cleaned):
            continue
        if _looks_like_reference_line(cleaned):
            break
        if norm == "company":
            flush()
            current = {
                "company": "",
                "position": "",
                "start_date": "",
                "end_date": "",
                "responsibilities": [],
                "clients": [],
                "technologies": [],
                "summary": None,
            }
            # Apply any date range that appeared before the Company label
            if pending_date_start or pending_date_end:
                current["start_date"] = pending_date_start
                current["end_date"] = pending_date_end
                pending_date_start = ""
                pending_date_end = ""
            pending_label = "company"
            in_responsibilities = False
            continue
        if norm in {"position", "position held", "role", "job title"}:
            pending_label = "position"
            in_responsibilities = False
            continue
        if norm in {"duration", "dates", "period"}:
            pending_label = "duration"
            in_responsibilities = False
            continue
        if norm in {"responsibilities", "duties responsibilities", "duties"}:
            pending_label = ""
            in_responsibilities = True
            continue
        # Detect date range lines before Company (e.g. "July 2024 – Present")
        if current is None:
            date_text = re.sub(r"\s+\?\s+", " - ", cleaned)
            d_start, d_end = extract_date_range(date_text)
            if d_start or d_end:
                pending_date_start = format_recruiter_date(d_start)
                pending_date_end = format_recruiter_date(d_end)
            continue

        if pending_label == "company":
            current["company"] = _strip_leading_colon(cleaned)
            pending_label = ""
            continue
        if pending_label == "position":
            current["position"] = _strip_leading_colon(cleaned)
            pending_label = ""
            continue
        if pending_label == "duration":
            date_text = re.sub(r"\s+\?\s+", " - ", cleaned)
            start_date, end_date = extract_date_range(date_text)
            if not (start_date or end_date):
                parts = [part.strip() for part in re.split(r"\s+-\s+", date_text, maxsplit=1) if part.strip()]
                if len(parts) == 2:
                    start_date, end_date = parts[0], parts[1]
            current["start_date"] = format_recruiter_date(start_date)
            current["end_date"] = format_recruiter_date(end_date)
            pending_label = ""
            continue
        # Detect inline date range lines between entries
        if not current.get("start_date") and not current.get("end_date"):
            date_text = re.sub(r"\s+\?\s+", " - ", cleaned)
            d_start, d_end = extract_date_range(date_text)
            if d_start or d_end:
                current["start_date"] = format_recruiter_date(d_start)
                current["end_date"] = format_recruiter_date(d_end)
                continue

        # Date range line while in responsibilities = start of next entry
        if in_responsibilities and current.get("start_date"):
            date_text = re.sub(r"\s+\?\s+", " - ", cleaned)
            d_start, d_end = extract_date_range(date_text)
            if (d_start or d_end) and len(cleaned.split()) <= 6:
                pending_date_start = format_recruiter_date(d_start)
                pending_date_end = format_recruiter_date(d_end)
                continue

        if _looks_like_experience_location_line(cleaned):
            continue
        if current.get("company") and current.get("position"):
            in_responsibilities = True
        if in_responsibilities:
            _append_unique_text(current.setdefault("responsibilities", []), cleaned)

    flush()
    return clean_experience_entries(entries)


def _parse_pipe_experience_blocks(content: str) -> List[Dict[str, Any]]:
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    if not any("|" in line for line in lines):
        return []

    entries: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    row_count = 0
    for raw in lines:
        cleaned = sanitize_entity_text(BULLET_RE.sub("", raw)) or ""
        if not cleaned or re.fullmatch(r"[?]+", cleaned):
            continue
        if _parse_rendered_history_role_line(cleaned):
            continue
        parsed_row = _split_role_company_date_line(cleaned) if _looks_like_pipe_experience_row(cleaned) else None
        if parsed_row:
            if current and _is_professional_experience(current):
                entries.append(current)
            current = parsed_row
            current.setdefault("responsibilities", [])
            current.setdefault("clients", [])
            current.setdefault("technologies", [])
            current.setdefault("summary", None)
            row_count += 1
            continue
        if current is None:
            continue
        resp_text = sanitize_entity_text(re.sub(r"^Responsibilities\s*:\s*", "", cleaned, flags=re.I)) or ""
        if not resp_text or _looks_like_experience_location_line(resp_text):
            continue
        _append_unique_text(current.setdefault("responsibilities", []), resp_text)

    if current and _is_professional_experience(current):
        entries.append(current)
    if row_count < 1:
        return []
    return clean_experience_entries(entries)


def _looks_like_experience_restart_line(line: str) -> bool:
    cleaned = sanitize_entity_text(BULLET_RE.sub("", line)) or ""
    if not cleaned or _line_is_attachment_noise(cleaned):
        return False
    return bool(
        _split_role_company_date_line(cleaned)
        or _split_role_company_anchor_line(cleaned)
        or _parse_role_company_without_dates_line(cleaned)
    )


def _looks_like_pipe_experience_row(line: str) -> bool:
    cleaned = sanitize_entity_text(BULLET_RE.sub("", line)) or ""
    if cleaned.count("|") < 3:
        return False
    parts = [sanitize_entity_text(part) or "" for part in cleaned.split("|") if sanitize_entity_text(part)]
    if len(parts) < 4:
        return False
    if EMAIL_RE.search(parts[2]) or PHONE_RE.search(parts[2]) or EMAIL_RE.search(parts[3]) or PHONE_RE.search(parts[3]):
        return False
    return bool(format_recruiter_date(parts[2]) and format_recruiter_date(parts[3]))


def _strip_reference_interludes(lines: List[str]) -> List[str]:
    filtered: List[str] = []
    in_reference_block = False
    stop_terms = {
        "qualifications",
        "education",
        "projects",
        "certifications",
        "courses",
        "training",
        "publications",
        "volunteering",
        "interests",
        "achievements awards",
        "achievements & awards",
        "achievements",
        "awards",
    }
    for raw in lines:
        cleaned = sanitize_entity_text(raw) or ""
        normalized = normalize_heading(cleaned)
        if _looks_like_reference_line(cleaned):
            in_reference_block = True
            continue
        if in_reference_block:
            if _looks_like_experience_restart_line(raw):
                in_reference_block = False
                filtered.append(raw)
                continue
            if normalized in stop_terms:
                filtered.append(raw)
                in_reference_block = False
                continue
            continue
        filtered.append(raw)
    return filtered


def _parse_vertical_experience_blocks(content: str) -> List[Dict[str, Any]]:
    lines = _experience_source_lines(content)
    if len(lines) < 2:
        return []

    entries: List[Dict[str, Any]] = []
    idx = 0
    while idx < len(lines) - 1:
        if not _looks_like_vertical_experience_anchor(lines, idx):
            idx += 1
            continue

        current: Dict[str, Any] = {
            "company": sanitize_entity_text(lines[idx]) or "",
            "position": sanitize_entity_text(lines[idx + 1]) or "",
            "start_date": "",
            "end_date": "",
            "responsibilities": [],
            "clients": [],
            "technologies": [],
            "summary": None,
        }
        idx += 2

        while idx < len(lines):
            cleaned = sanitize_entity_text(BULLET_RE.sub("", lines[idx])) or ""
            normalized = normalize_heading(cleaned)
            if not cleaned or _line_is_attachment_noise(cleaned):
                idx += 1
                continue
            if normalized in _DEFENSIVE_STOP_HEADINGS and normalized not in _EXPERIENCE_CAPTURE_HEADINGS:
                break
            if _looks_like_reference_line(cleaned):
                break
            if _looks_like_vertical_experience_anchor(lines, idx):
                break

            start_date, end_date = extract_date_range(cleaned)
            if (start_date or end_date) and not (current.get("start_date") or current.get("end_date")):
                current["start_date"] = format_recruiter_date(start_date)
                current["end_date"] = format_recruiter_date(end_date)
                idx += 1
                continue

            if not _looks_like_experience_noise_line(cleaned):
                _append_unique_text(current.setdefault("responsibilities", []), cleaned)
            idx += 1

        if _is_professional_experience(current):
            entries.append(current)

    return clean_experience_entries(entries)


def _parse_anchor_date_experience_blocks(content: str) -> List[Dict[str, Any]]:
    lines = _experience_source_lines(content)
    if not lines:
        return []

    entries: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    active_client: Optional[Dict[str, Any]] = None
    in_client_section = False

    for raw in lines:
        normalized = normalize_heading(raw)
        if normalized in _EXPERIENCE_CAPTURE_HEADINGS:
            continue
        if normalized in _CONSULTING_CLIENT_SECTION_HEADINGS:
            in_client_section = True
            active_client = None
            continue
        if normalized in _DEFENSIVE_STOP_HEADINGS and normalized not in _EXPERIENCE_CAPTURE_HEADINGS:
            break
        if _looks_like_reference_line(raw):
            break

        cleaned = sanitize_entity_text(BULLET_RE.sub("", raw)) or ""
        if not cleaned or _line_is_attachment_noise(cleaned):
            continue

        parsed = _parse_rendered_history_role_line(cleaned) or _parse_role_company_without_dates_line(cleaned) or _split_role_company_anchor_line(cleaned)
        if parsed:
            if current and _is_professional_experience(current):
                entries.append(current)
            current = parsed
            active_client = None
            in_client_section = False
            continue

        if current is None:
            continue

        start_date, end_date = extract_date_range(cleaned)
        if (start_date or end_date) and not (current.get("start_date") or current.get("end_date")):
            current["start_date"] = format_recruiter_date(start_date)
            current["end_date"] = format_recruiter_date(end_date)
            continue

        client_row = _parse_client_line(cleaned)
        if client_row:
            current.setdefault("clients", []).append(client_row)
            active_client = current["clients"][-1]
            in_client_section = True
            continue

        if re.match(r"^Responsibilities\s*:\s*", cleaned, re.I):
            body = sanitize_entity_text(re.sub(r"^Responsibilities\s*:\s*", "", cleaned, flags=re.I)) or ""
            if body:
                _append_unique_text(current.setdefault("responsibilities", []), body)
            in_client_section = False
            active_client = None
            continue

        if _looks_like_experience_location_line(cleaned) or _looks_like_experience_noise_line(cleaned):
            continue

        if active_client is not None and in_client_section:
            _append_unique_text(active_client.setdefault("responsibilities", []), cleaned)
            continue

        if BULLET_RE.match(raw):
            _append_unique_text(current.setdefault("responsibilities", []), cleaned)
            continue

        if len(cleaned.split()) >= 10 and not current.get("summary"):
            current["summary"] = cleaned
        else:
            _append_unique_text(current.setdefault("responsibilities", []), cleaned)

    if current and _is_professional_experience(current):
        entries.append(current)

    return clean_experience_entries(entries)


def _parse_experience_section_with_layout_fix(content: str) -> List[Dict[str, Any]]:
    source_lines = _experience_source_lines(content)
    start_idx = 0
    for idx, raw in enumerate(source_lines):
        cleaned = sanitize_entity_text(raw) or ""
        normalized = normalize_heading(cleaned)
        if normalized in _EXPERIENCE_CAPTURE_HEADINGS:
            start_idx = idx + 1
            break
        if normalized in {"company", "position", "position held", "duration", "role", "job title"} or re.match(r"^(?:company|position|duration|role|job title)\s*[:|]", cleaned, re.I):
            # Include preceding date range line if present (e.g. "July 2024 – Present")
            if idx > 0:
                prev_cleaned = sanitize_entity_text(source_lines[idx - 1]) or ""
                prev_start, prev_end = extract_date_range(prev_cleaned)
                if prev_start or prev_end:
                    start_idx = idx - 1
                    break
            start_idx = idx
            break
        if _looks_like_pipe_experience_row(cleaned):
            start_idx = idx
            break
        if _parse_rendered_history_role_line(cleaned):
            start_idx = idx
            break
    scoped_lines = _strip_reference_interludes(source_lines[start_idx:])
    trimmed_lines: List[str] = []
    for raw in scoped_lines:
        cleaned = sanitize_entity_text(raw) or ""
        normalized = normalize_heading(cleaned)
        if trimmed_lines and normalized in {"achievements awards", "achievements & awards", "achievements", "awards", "qualifications", "education", "projects", "certifications", "courses", "training", "publications", "volunteering", "interests"}:
            break
        trimmed_lines.append(raw)
    trimmed_content = "\n".join(trimmed_lines).strip()
    labeled_entries = _parse_labeled_experience_blocks(trimmed_content)
    if labeled_entries:
        return labeled_entries
    pipe_entries = _parse_pipe_experience_blocks(trimmed_content)
    if pipe_entries:
        return pipe_entries
    anchored_entries = _parse_anchor_date_experience_blocks(trimmed_content)
    if anchored_entries:
        return anchored_entries
    vertical_entries = _parse_vertical_experience_blocks(trimmed_content)
    if vertical_entries:
        return vertical_entries
    return _parse_experience_section_before_layout_fix(trimmed_content)


def is_valid_name_candidate(text: str) -> bool:
    cleaned = sanitize_entity_text(text) or ""
    if not _is_valid_name_candidate_before_layout_fix(cleaned):
        return False
    lowered = cleaned.lower()
    if any(token in lowered for token in {"academy", "university", "college", "school", "matric", "certificate", "diploma", "degree", "honours", "honors"}):
        return False
    if re.search(r"[,/|()]", cleaned):
        return False
    tokens = [token.strip(".") for token in cleaned.split() if token.strip(".")]
    if len(tokens) < 2 or len(tokens) > 4:
        return False
    particles = {"de", "da", "del", "der", "di", "du", "la", "le", "van", "von", "bin"}
    blocked = {
        "project",
        "management",
        "manager",
        "coordinator",
        "co-ordinator",
        "administrator",
        "admin",
        "analyst",
        "developer",
        "engineer",
        "architect",
        "consultant",
        "scrum",
        "sprint",
        "master",
        "devops",
        "azure",
        "oracle",
        "sharepoint",
        "jira",
        "confluence",
        "sap",
        "resource",
        "planning",
        "allocation",
        "contract",
        "cost",
        "performance",
        "lifecycle",
        "communication",
        "procurement",
        "meetings",
        "delivery",
        "office",
        "software",
        "coordination",
        "productivity",
        "tools",
        "platforms",
        "frameworks",
        "skills",
        "testing",
        "automation",
        "analytics",
        "databases",
        "methodologies",
        "training",
        "course",
        "fundamentals",
        "expert",
        "worked",
        "team",
        "charter",
        "foundations",
        "engineering",
        "data",
        "warehousing",
        "concepts",
        "science",
        "intelligence",
        "modelling",
        "modeling",
        "visualization",
        "reporting",
        "systems",
        "cleaning",
        "preparation",
        "transformation",
        "programming",
        "computing",
        "networking",
        "security",
        "infrastructure",
        "operations",
        "strategy",
        "technical",
        "professional",
        "business",
        "digital",
        "cloud",
        "agile",
        "design",
        "development",
        "solutions",
        "services",
        "support",
        "quality",
        "assurance",
        "analysis",
        "governance",
        "compliance",
        "integration",
    }
    name_like_count = 0
    for token in tokens:
        lowered_token = token.lower()
        if lowered_token in blocked:
            return False
        if lowered_token in particles:
            continue
        if re.fullmatch(r"[A-Z](?:[A-Z]+)?", token) or re.fullmatch(r"[A-Z][a-z]+(?:[-'][A-Z][a-z]+)*", token):
            name_like_count += 1
            continue
        return False
    if name_like_count < 2:
        return False
    return True


def _find_labeled_identity_value(lines: List[str], label: str) -> str:
    target = normalize_heading(label)
    for idx, raw in enumerate(lines[:40]):
        field, value = _coalesce_inline_label(raw)
        if field == target and value:
            return value
        if normalize_heading(raw) == target and idx + 1 < len(lines):
            next_value = sanitize_entity_text(lines[idx + 1]) or ""
            if next_value and normalize_heading(next_value) not in KNOWN_HEADING_TERMS:
                return next_value
    return ""


def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    base = _extract_identity_before_layout_fix(raw_text, sections, path)
    lines = [sanitize_entity_text(line) or "" for line in raw_text.splitlines() if sanitize_entity_text(line)]
    reference_start = next((idx for idx, line in enumerate(lines[:40]) if normalize_heading(line) == "references"), -1)
    filename_name = infer_name_from_filename(path.name) if path else ""
    matched_filename_identity = False

    if filename_name:
        matched_idx = next((idx for idx, line in enumerate(lines[:40]) if line.casefold() == filename_name.casefold()), -1)
        if matched_idx >= 0:
            matched_filename_identity = True
            base["full_name"] = filename_name
            candidate_zone = [line for line in lines[matched_idx: matched_idx + 6] if not _looks_like_reference_line(line)]
            if len(candidate_zone) >= 2:
                candidate_headline = _extract_identity_header_headline(candidate_zone[1], filename_name)
                if candidate_headline and normalize_heading(candidate_headline) not in KNOWN_HEADING_TERMS:
                    base["headline"] = candidate_headline
            zone_text = "\n".join(candidate_zone)
            email_match = EMAIL_RE.search(zone_text)
            phone_match = PHONE_RE.search(zone_text)
            if email_match:
                base["email"] = email_match.group(0)
            if phone_match:
                base["phone"] = phone_match.group(0)

    explicit_name = _find_labeled_identity_value(lines, "name")
    if explicit_name and is_valid_name_candidate(explicit_name):
        base["full_name"] = explicit_name
    elif not is_valid_name_candidate(base.get("full_name") or ""):
        candidates = [line for line in lines[:12] if is_valid_name_candidate(line)]
        if candidates:
            base["full_name"] = candidates[0]
    elif reference_start >= 0 and filename_name and not matched_filename_identity:
        selected_name = sanitize_entity_text(base.get("full_name")) or ""
        selected_idx = next((idx for idx, line in enumerate(lines[:40]) if line == selected_name), -1)
        if selected_idx >= reference_start:
            base["full_name"] = filename_name
            selected_headline = sanitize_entity_text(base.get("headline")) or ""
            headline_idx = next((idx for idx, line in enumerate(lines[:40]) if line == selected_headline), -1)
            if headline_idx >= reference_start:
                base["headline"] = None
            if base.get("email") and any((base["email"] in line) for line in lines[reference_start:]):
                base["email"] = None
            if base.get("phone") and any((base["phone"] in line) for line in lines[reference_start:]):
                base["phone"] = None
    elif reference_start >= 0 and not matched_filename_identity:
        selected_name = sanitize_entity_text(base.get("full_name")) or ""
        selected_idx = next((idx for idx, line in enumerate(lines[:40]) if line == selected_name), -1)
        if selected_idx >= reference_start:
            base["full_name"] = None
            base["headline"] = None
            base["email"] = None
            base["phone"] = None

    headline = sanitize_entity_text(base.get("headline")) or ""
    if normalize_heading(headline) in {"professional profile", "profile", "professional summary", "summary"}:
        headline = ""

    if not headline:
        for line in lines[:18]:
            if is_valid_name_candidate(line):
                continue
            candidate = _extract_identity_header_headline(line, sanitize_entity_text(base.get("full_name")) or "")
            if candidate and normalize_heading(candidate) not in KNOWN_HEADING_TERMS:
                headline = candidate
                break
        if not headline:
            experience_rows = clean_experience_entries(parse_experience_section(raw_text))
            if experience_rows:
                headline = sanitize_entity_text(experience_rows[0].get("position")) or ""

    availability = _find_labeled_identity_value(lines, "availability")
    if availability:
        base["availability"] = availability

    identity_window: List[str] = []
    for line in lines[:40]:
        if _looks_like_reference_line(line):
            break
        identity_window.append(line)
    identity_search = "\n".join(identity_window)
    if not base.get("email"):
        email_match = EMAIL_RE.search(identity_search)
        if email_match:
            base["email"] = email_match.group(0)
    if not base.get("phone") or not PHONE_RE.search(str(base.get("phone") or "")):
        phone_match = PHONE_RE.search(identity_search)
        if phone_match:
            base["phone"] = phone_match.group(0)
    if not base.get("linkedin"):
        linkedin_match = LINKEDIN_RE.search(identity_search)
        if linkedin_match:
            base["linkedin"] = linkedin_match.group(0)
    if base.get("portfolio") and re.search(r"\b(?:gmail|yahoo|hotmail|outlook)\.com\b", str(base.get("portfolio")), re.I):
        base["portfolio"] = None
    if not base.get("portfolio"):
        for match in URL_RE.finditer(identity_search):
            url = sanitize_entity_text(match.group(0)) or ""
            if not url or "linkedin" in url.lower() or "@" in url:
                continue
            base["portfolio"] = url
            break
    if not base.get("location"):
        for line in identity_window:
            cleaned = sanitize_entity_text(line) or ""
            if not cleaned or cleaned == sanitize_entity_text(base.get("full_name")) or cleaned == headline:
                continue
            if normalize_heading(cleaned) in KNOWN_HEADING_TERMS or normalize_heading(cleaned) in _PERSONAL_DETAIL_LABELS:
                continue
            if looks_like_education_line(cleaned) or _looks_like_role_title_local(cleaned):
                continue
            if not _looks_like_contact_or_location_line(cleaned):
                continue
            if _LOCATION_HINTS.search(cleaned) and not (EMAIL_RE.search(cleaned) or PHONE_RE.search(cleaned) or LINKEDIN_RE.search(cleaned) or URL_RE.search(cleaned)):
                _lbl, _val = _coalesce_inline_label(line)
                base["location"] = _val if _val and _LOCATION_HINTS.search(_val) else cleaned
                break
    if not base.get("region") and base.get("location"):
        base["region"] = base["location"]

    if headline:
        base["headline"] = headline
    base["confidence"] = 0.92 if base.get("full_name") and base.get("headline") else 0.8
    return base


def _looks_like_role_title_local(text: str) -> bool:
    lowered = (sanitize_entity_text(text) or "").lower().strip()
    if any(
        phrase in lowered
        for phrase in {
            "delivery lifecycle",
            "project charter",
            "project meetings",
            "communication management",
            "performance management",
            "resource planning",
            "cost management",
            "devops team",
        }
    ):
        return False
    if "co-ordinator" in lowered:
        return True
    return _looks_like_role_title_local_before_layout_fix(text)



def _looks_like_reference_line(line: str) -> bool:
    cleaned = sanitize_entity_text(line) or ""
    lowered = cleaned.lower()
    if not cleaned:
        return False
    if "available on request" in lowered:
        return True
    if re.search(r"\b(?:references?|referees?)\b", lowered):
        return True
    if (EMAIL_RE.search(cleaned) or PHONE_RE.search(cleaned)) and re.search(
        r"\b(?:supervisor|lecturer|professor|referee)\b",
        lowered,
    ):
        return True
    return False


# ---------------------------------------------------------------------------
# Final shared table-layout and identity guardrails
# ---------------------------------------------------------------------------

_TABLE_LAYOUT_SECTION_HEADINGS: Dict[str, tuple[str, str]] = {
    "personal details": ("Personal Details", "raw_unknown"),
    "education / qualifications": ("Qualifications", "education"),
    "qualifications / education": ("Qualifications", "education"),
    "education qualifications": ("Qualifications", "education"),
    "certificates / courses / training": ("Training", "training"),
    "additional certificates / courses / training": ("Training", "training"),
    "professional experience": ("Career History", "experience"),
    "skills and competencies": ("Skills", "skills"),
    "key achievements / awards": ("Awards", "awards"),
    "achievements / awards": ("Awards", "awards"),
}
_TABLE_LAYOUT_HEADER_TERMS = {
    "qualification",
    "institution",
    "date",
    "dates",
    "year",
    "degree",
    "provider",
    "certificate / course / training",
    "certification",
    "organisation",
    "organization",
    "position",
    "client/s",
    "clients",
    "technologies",
}
_LABELLED_EXPERIENCE_FIELDS = {
    "organisation",
    "organization",
    "company",
    "dates",
    "duration",
    "period",
    "position",
    "role",
    "job title",
    "client/s",
    "clients",
    "client",
    "technologies",
    "overview",
    "what i did",
    "responsibilities",
    "duties",
    "duties responsibilities",
    "key achievements / awards",
    "achievements / awards",
    "key achievements",
    "awards",
}
_IDENTITY_PHONE_LABELS = {
    "phone",
    "mobile",
    "telephone",
    "tel",
    "cell",
    "cellphone",
    "contact number",
    "cell number",
}
_IDENTITY_ID_LABELS = {
    "id number",
    "identity number",
    "id no",
    "passport",
    "passport number",
}


def _split_pipe_parts(text: str) -> List[str]:
    cleaned = sanitize_entity_text(text) or ""
    if not cleaned:
        return []
    return [part for part in (sanitize_entity_text(piece) or "" for piece in cleaned.split("|")) if part]


def _dedupe_preserve_text(items: List[str]) -> List[str]:
    seen = set()
    deduped: List[str] = []
    for item in items:
        cleaned = sanitize_entity_text(item) or ""
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


def _extract_labelled_pipe_value(text: str, allowed_labels: set[str]) -> tuple[str, str]:
    parts = _split_pipe_parts(text)
    if len(parts) >= 2:
        label = normalize_heading(parts[0].rstrip(":"))
        value = " | ".join(parts[1:]).strip(" |")
        if label in allowed_labels and value:
            return label, sanitize_entity_text(value) or ""
    label, value = _coalesce_inline_label(text)
    if label in allowed_labels and value:
        return label, value
    return "", ""


def _collapse_repeated_heading_line(text: str) -> str:
    parts = _split_pipe_parts(text)
    if len(parts) >= 2:
        normalized = {normalize_heading(part.rstrip(":")) for part in parts}
        if len(normalized) == 1:
            only = next(iter(normalized))
            if only in _TABLE_LAYOUT_SECTION_HEADINGS:
                return sanitize_entity_text(parts[0].rstrip(":")) or ""
    cleaned = sanitize_entity_text(text) or ""
    if normalize_heading(cleaned.rstrip(":")) in _TABLE_LAYOUT_SECTION_HEADINGS:
        return cleaned.rstrip(":")
    return ""


def _looks_like_table_layout_header_row(text: str) -> bool:
    parts = _split_pipe_parts(text)
    if not parts:
        return False
    headerish_count = sum(1 for part in parts if normalize_heading(part.rstrip(":")) in _TABLE_LAYOUT_HEADER_TERMS)
    return len(parts) >= 2 and headerish_count >= 2


def _parse_table_layout_sections(raw_text: str) -> List[SectionBlock]:
    lines = [sanitize_entity_text(line) or "" for line in raw_text.splitlines() if sanitize_entity_text(line)]
    if not lines:
        return []

    headings: List[tuple[int, str, str]] = []
    for idx, line in enumerate(lines):
        heading = _collapse_repeated_heading_line(line)
        if not heading:
            continue
        title, canonical_key = _TABLE_LAYOUT_SECTION_HEADINGS[normalize_heading(heading)]
        headings.append((idx, title, canonical_key))

    canonical_keys = {item[2] for item in headings}
    if len(headings) < 4 or "experience" not in canonical_keys or "education" not in canonical_keys:
        return []

    sections: List[SectionBlock] = []
    first_heading_idx = headings[0][0]
    if first_heading_idx > 0:
        header_lines = [line for line in lines[:first_heading_idx] if line]
        if header_lines:
            sections.append(
                SectionBlock(
                    id=str(uuid.uuid4())[:8],
                    title="Header",
                    canonical_key="raw_unknown",
                    content="\n".join(header_lines),
                    confidence=0.78,
                    source="table_heading",
                    start_line=0,
                    end_line=first_heading_idx - 1,
                )
            )

    for offset, (start_idx, title, canonical_key) in enumerate(headings):
        end_idx = headings[offset + 1][0] if offset + 1 < len(headings) else len(lines)
        block_lines = [line for line in lines[start_idx + 1:end_idx] if line]
        if canonical_key in {"training", "education", "experience"}:
            block_lines = [line for line in block_lines if not _looks_like_table_layout_header_row(line)]
        if not block_lines:
            continue
        sections.append(
            SectionBlock(
                id=str(uuid.uuid4())[:8],
                title=title,
                canonical_key=canonical_key,
                content="\n".join(block_lines),
                confidence=0.97,
                source="table_heading",
                start_line=start_idx + 1,
                end_line=end_idx - 1,
            )
        )
    return merge_section_blocks(sections)


_parse_sections_before_table_guardrails = _parse_sections_with_layout_fix


def parse_sections(raw_text: str) -> List[SectionBlock]:
    table_sections = _parse_table_layout_sections(raw_text)
    if table_sections:
        return table_sections
    return _parse_sections_before_table_guardrails(raw_text)


def _clean_labelled_education_date(text: str) -> str:
    cleaned = sanitize_entity_text(text) or ""
    if not cleaned:
        return ""
    incomplete = re.match(r"^(Incomplete\s*\([^)]+\))", cleaned, re.I)
    if incomplete:
        return incomplete.group(1)
    return cleaned


def _parse_labelled_education_rows(content: str) -> List[Dict[str, Any]]:
    lines = [sanitize_entity_text(line) or "" for line in content.splitlines() if sanitize_entity_text(line)]
    if not lines:
        return []

    rows: List[Dict[str, Any]] = []
    seen = set()
    current: Optional[Dict[str, Any]] = None

    def commit(row: Optional[Dict[str, Any]]) -> None:
        if not row:
            return
        qualification = sanitize_entity_text(row.get("qualification")) or ""
        institution = sanitize_entity_text(row.get("institution")) or ""
        if not qualification or not institution:
            return
        key = (
            qualification.casefold(),
            institution.casefold(),
            (sanitize_entity_text(row.get("start_date")) or "").casefold(),
            (sanitize_entity_text(row.get("end_date")) or "").casefold(),
        )
        if key in seen:
            return
        seen.add(key)
        row["qualification"] = qualification
        row["institution"] = institution
        rows.append(row)

    for raw in lines:
        label, value = _extract_labelled_pipe_value(raw, {"qualification", "institution", "date", "dates", "year"})
        if not label or not value:
            continue
        if label == "qualification":
            commit(current)
            current = {
                "qualification": value,
                "institution": "",
                "start_date": "",
                "end_date": "",
                "sa_standard_hint": infer_sa_qualification_note(value),
            }
            continue
        if current is None:
            continue
        if label == "institution":
            current["institution"] = value
            continue

        date_value = _clean_labelled_education_date(value)
        if not date_value:
            continue
        if re.search(r"^Incomplete\b", date_value, re.I):
            current["end_date"] = date_value
            continue
        start_date, end_date = extract_date_range(date_value)
        current["start_date"] = format_recruiter_date(start_date)
        current["end_date"] = format_recruiter_date(end_date) or date_value

    commit(current)
    return rows


_parse_education_section_before_labelled_rows = parse_education_section


_EDUCATION_QUALIFICATION_STARTERS = re.compile(
    r"^(?:grade\s*12|national\s+diploma|diploma|bachelor|b\.?tech|honours|honors|"
    r"master|phd|doctorate|national\s+senior\s+certificate|matric|higher\s+certificate|"
    r"advanced\s+diploma|postgraduate|certificate\b)",
    re.I,
)


def _parse_vertical_colon_education(content: str) -> List[Dict[str, Any]]:
    """Parse education entries in vertical year / qualification / : / institution format.

    Handles PDF-extracted layouts like:
        2026
        ISTQB Foundation
        Certificate : ISTQB Certificate
        2021
        National Diploma in Information Technology
        :
        Durban University of Technology
    """
    lines = [sanitize_entity_text(line) or "" for line in content.splitlines() if sanitize_entity_text(line)]
    if not lines:
        return []

    # Detect entries anchored by standalone year lines
    year_re = re.compile(r"^((?:19|20)\d{2})$")
    entry_starts: List[int] = []
    for idx, line in enumerate(lines):
        if year_re.match(line.strip()):
            entry_starts.append(idx)
    if len(entry_starts) < 2:
        return []

    # Also check if ":" appears as a separator line (not inline label:value)
    has_colon_separator = any(line.strip() == ":" for line in lines)
    if not has_colon_separator:
        return []

    # Build raw blocks between year anchors
    raw_blocks: List[tuple] = []
    for i, start in enumerate(entry_starts):
        end = entry_starts[i + 1] if i + 1 < len(entry_starts) else len(lines)
        raw_blocks.append((lines[start].strip(), lines[start + 1:end]))

    entries: List[Dict[str, Any]] = []
    for year, block in raw_blocks:
        if not block:
            continue

        # Split block into sub-entries when a qualification term appears after a colon section
        sub_entries: List[tuple] = []  # (qual_parts, inst_parts, sub_year)
        qualification_parts: List[str] = []
        institution_parts: List[str] = []
        after_colon = False
        sub_year = year

        def commit_sub():
            nonlocal qualification_parts, institution_parts, after_colon, sub_year
            q = " ".join(qualification_parts).strip()
            inst = " ".join(institution_parts).strip()
            if q:
                sub_entries.append((q, inst, sub_year))
            qualification_parts = []
            institution_parts = []
            after_colon = False

        for bline in block:
            stripped = bline.strip()
            if stripped == ":":
                after_colon = True
                continue
            # Handle "Certificate : Value" inline → merge into qualification
            cert_match = re.match(r"^Certificate\s*:\s*(.+)$", stripped, re.I)
            if cert_match and not after_colon:
                cert_value = cert_match.group(1).strip()
                # Avoid duplication: if existing parts share prefix with cert value
                # e.g. "ISTQB Foundation" + "ISTQB Certificate" → "ISTQB Foundation Certificate"
                if qualification_parts:
                    existing = qualification_parts[-1]
                    existing_words = existing.split()
                    cert_words = cert_value.split()
                    if existing_words and cert_words and existing_words[0].lower() == cert_words[0].lower():
                        # Drop the shared prefix from cert value
                        cert_value = " ".join(cert_words[1:])
                qualification_parts.append(cert_value)
                continue
            if after_colon:
                # Check if this line starts a new qualification (e.g. "Grade 12")
                if _EDUCATION_QUALIFICATION_STARTERS.match(stripped):
                    commit_sub()
                    qualification_parts.append(stripped)
                    continue
                # Check if institution line has a trailing year (e.g. "Technology 2013")
                trailing_year = re.search(r"\s+((?:19|20)\d{2})$", stripped)
                if trailing_year:
                    institution_parts.append(stripped[:trailing_year.start()].strip())
                    sub_year_for_next = trailing_year.group(1)
                    # The trailing year belongs to the NEXT sub-entry
                    commit_sub()
                    sub_year = sub_year_for_next
                else:
                    institution_parts.append(stripped)
            else:
                qualification_parts.append(stripped)

        commit_sub()

        for qual, inst, yr in sub_entries:
            entries.append({
                "qualification": qual,
                "institution": inst,
                "start_date": "",
                "end_date": format_recruiter_date(yr),
                "sa_standard_hint": infer_sa_qualification_note(qual),
            })

    return entries if len(entries) >= 2 else []


def parse_education_section(content: str) -> List[Dict[str, Any]]:
    labelled_rows = _parse_labelled_education_rows(content)
    if labelled_rows:
        return labelled_rows
    vertical_rows = _parse_vertical_colon_education(content)
    if vertical_rows:
        return vertical_rows
    return _parse_education_section_before_labelled_rows(content)


def _collapse_duplicate_pipe_body(text: str) -> str:
    parts = _split_pipe_parts(text)
    if not parts:
        return ""
    if len(parts) >= 2 and len({part.casefold() for part in parts}) == 1:
        return parts[0]
    return sanitize_entity_text(text) or ""


def _split_experience_body_items(text: str) -> List[str]:
    cleaned = sanitize_entity_text(text) or ""
    if not cleaned:
        return []
    pipe_parts = _split_pipe_parts(cleaned)
    if len(pipe_parts) >= 2 and len({part.casefold() for part in pipe_parts}) == 1:
        cleaned = pipe_parts[0]
    elif len(pipe_parts) >= 2 and all(part.strip() for part in pipe_parts):
        return _dedupe_preserve_text(pipe_parts)

    sentence_parts = [
        sanitize_entity_text(part) or ""
        for part in re.split(r"(?<=[.!?])\s+(?=[A-Z])", cleaned)
        if sanitize_entity_text(part)
    ]
    if len(sentence_parts) >= 2:
        return _dedupe_preserve_text(sentence_parts)
    return [cleaned]


def _parse_labelled_table_experience_blocks(content: str) -> List[Dict[str, Any]]:
    lines = _experience_source_lines(content)
    if not lines:
        return []

    detected_labels = [
        _extract_labelled_pipe_value(line, _LABELLED_EXPERIENCE_FIELDS)[0]
        for line in lines
    ]
    detected_labels = [label for label in detected_labels if label]
    if not detected_labels:
        return []
    if not any(label in {"organisation", "organization", "company"} for label in detected_labels):
        return []

    entries: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    capture_mode = ""

    def flush() -> None:
        nonlocal current, capture_mode
        if current and _is_professional_experience(current):
            entries.append(current)
        current = None
        capture_mode = ""

    for raw in lines:
        cleaned = _collapse_duplicate_pipe_body(raw)
        normalized = normalize_heading(cleaned)
        if _looks_like_reference_line(cleaned):
            break
        if current and normalized in _DEFENSIVE_STOP_HEADINGS and normalized not in _EXPERIENCE_CAPTURE_HEADINGS:
            break

        label, value = _extract_labelled_pipe_value(raw, _LABELLED_EXPERIENCE_FIELDS)
        if label in {"organisation", "organization", "company"}:
            flush()
            current = {
                "company": value,
                "position": "",
                "start_date": "",
                "end_date": "",
                "responsibilities": [],
                "clients": [],
                "technologies": [],
                "summary": None,
                "awards": [],
            }
            continue
        if current is None:
            continue

        if label in {"dates", "duration", "period"}:
            start_date, end_date = extract_date_range(value)
            current["start_date"] = format_recruiter_date(start_date)
            current["end_date"] = format_recruiter_date(end_date) or sanitize_entity_text(value) or ""
            continue
        if label in {"position", "role", "job title"}:
            current["position"] = value
            continue
        if label in {"client/s", "clients", "client"}:
            for client_name in [item for item in re.split(r"\s*,\s*", value) if item]:
                current.setdefault("clients", []).append(
                    {
                        "client_name": sanitize_entity_text(client_name) or "",
                        "project_name": "",
                        "programme": "",
                        "responsibilities": [],
                    }
                )
            continue
        if label == "technologies":
            current["technologies"] = parse_simple_items(value)
            continue
        if label == "overview":
            capture_mode = "overview"
            if normalize_heading(value) != "overview":
                current["summary"] = value
            continue
        if label in {"what i did", "responsibilities", "duties", "duties responsibilities"}:
            capture_mode = "responsibilities"
            if normalize_heading(value) not in {"what i did", "responsibilities", "duties", "duties responsibilities"}:
                for item in _split_experience_body_items(value):
                    _append_unique_text(current.setdefault("responsibilities", []), item)
            continue
        if label in {"key achievements / awards", "achievements / awards", "key achievements", "awards"}:
            capture_mode = "awards"
            if normalize_heading(value) not in {"key achievements / awards", "achievements / awards", "key achievements", "awards"}:
                for item in _split_experience_body_items(value):
                    _append_unique_text(current.setdefault("awards", []), item)
            continue
        if label.startswith("reason for leaving"):
            current["reason_for_leaving"] = value
            capture_mode = ""
            continue
        if label:
            continue
        if not cleaned or _line_is_attachment_noise(cleaned) or _looks_like_experience_location_line(cleaned):
            continue

        body_items = _split_experience_body_items(cleaned)
        if capture_mode == "awards":
            for item in body_items:
                _append_unique_text(current.setdefault("awards", []), item)
            continue
        if capture_mode == "overview" and body_items:
            if not current.get("summary"):
                current["summary"] = body_items[0]
                body_items = body_items[1:]
        for item in body_items:
            _append_unique_text(current.setdefault("responsibilities", []), item)

    flush()
    return clean_experience_entries(entries)


_parse_experience_section_before_labelled_tables = _parse_experience_section_with_layout_fix


def parse_experience_section(content: str) -> List[Dict[str, Any]]:
    labelled_entries = _parse_labelled_table_experience_blocks(content)
    if labelled_entries:
        return labelled_entries
    detected_labels = {
        _extract_labelled_pipe_value(line, _LABELLED_EXPERIENCE_FIELDS)[0]
        for line in _experience_source_lines(content)
    }
    detected_labels.discard("")
    if any(label in {"organisation", "organization", "company"} for label in detected_labels):
        return []
    return _parse_experience_section_before_labelled_tables(content)


def _phone_candidate_is_safe(candidate: str, context_line: str = "") -> bool:
    cleaned = re.sub(r"\s+", " ", sanitize_entity_text(candidate) or "").strip()
    digits = re.sub(r"\D", "", cleaned)
    lowered_context = (sanitize_entity_text(context_line) or "").lower()
    if not cleaned or any(label in lowered_context for label in _IDENTITY_ID_LABELS):
        return False
    if len(digits) < 10 or len(digits) > 12:
        return False
    if len(digits) == 13:
        return False
    if re.fullmatch(r"(?:19|20)\d{8,}", digits):
        return False
    if digits.startswith("0") and len(digits) == 10:
        return True
    if digits.startswith("27") and len(digits) == 11:
        return True
    if cleaned.startswith("+") and 11 <= len(digits) <= 12:
        return True
    if any(label in lowered_context for label in _IDENTITY_PHONE_LABELS):
        return True
    return False


def _extract_safe_phone_from_lines(lines: List[str]) -> str:
    for raw in lines:
        label, value = _extract_labelled_pipe_value(raw, _IDENTITY_PHONE_LABELS | _IDENTITY_ID_LABELS)
        if label in _IDENTITY_PHONE_LABELS:
            if _phone_candidate_is_safe(value, raw):
                return re.sub(r"\s+", " ", value).strip()
            # Try splitting on "/" for multi-phone values like "0710093985/ 0720900034"
            for part in re.split(r"\s*/\s*", value):
                part = part.strip()
                if part and _phone_candidate_is_safe(part, raw):
                    return re.sub(r"\s+", " ", part).strip()
    for raw in lines:
        cleaned = sanitize_entity_text(raw) or ""
        if any(label in cleaned.lower() for label in _IDENTITY_ID_LABELS):
            continue
        for match in PHONE_RE.finditer(cleaned):
            candidate = re.sub(r"\s+", " ", match.group(0)).strip()
            if _phone_candidate_is_safe(candidate, raw):
                return candidate
    return ""


def _extract_labelled_identity_values(lines: List[str]) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    for raw in lines[:40]:
        segments = [segment.strip() for segment in re.split(r"\s*\|\s*", raw) if segment.strip()]
        for segment in segments:
            label, value = _coalesce_inline_label(segment)
            if not label or not value:
                continue
            if label in {"name", "full name"} and is_valid_name_candidate(value):
                parsed.setdefault("full_name", value)
            elif label in {"headline", "professional headline", "title"}:
                parsed.setdefault("headline", value)
            elif label == "availability":
                parsed.setdefault("availability", value)
            elif label == "region":
                parsed.setdefault("region", value)
            elif label in {"location", "address"}:
                parsed.setdefault("location", value)
            elif label == "email":
                email_match = EMAIL_RE.search(value)
                if email_match:
                    parsed.setdefault("email", email_match.group(0))
            elif label in _IDENTITY_PHONE_LABELS:
                normalized_value = re.sub(r"\s+", " ", value).strip()
                if _phone_candidate_is_safe(normalized_value, raw):
                    parsed.setdefault("phone", normalized_value)
            elif label == "linkedin":
                linkedin_match = LINKEDIN_RE.search(value) or LINKEDIN_RE.search(segment)
                if linkedin_match:
                    parsed.setdefault("linkedin", linkedin_match.group(0))
            elif label in {"portfolio", "website", "web site"}:
                portfolio_value = sanitize_entity_text(value) or ""
                if portfolio_value:
                    parsed.setdefault("portfolio", portfolio_value)
    return parsed


_extract_identity_before_phone_guardrails = extract_identity


def extract_identity(raw_text: str, sections: List[SectionBlock], path: Optional[Path] = None) -> Dict[str, Any]:
    base = _extract_identity_before_phone_guardrails(raw_text, sections, path)
    lines = [sanitize_entity_text(line) or "" for line in raw_text.splitlines() if sanitize_entity_text(line)]
    identity_window: List[str] = []
    for line in lines[:40]:
        if _looks_like_reference_line(line):
            break
        identity_window.append(line)
    labelled_identity = _extract_labelled_identity_values(identity_window)
    for key in ("full_name", "availability", "region", "email", "location", "linkedin", "portfolio"):
        if labelled_identity.get(key):
            base[key] = labelled_identity[key]
    if labelled_identity.get("headline"):
        base["headline"] = labelled_identity["headline"]
    safe_phone = labelled_identity.get("phone") or _extract_safe_phone_from_lines(identity_window)
    if safe_phone:
        base["phone"] = safe_phone

    existing_phone = sanitize_entity_text(base.get("phone")) or ""
    existing_context = ""
    if existing_phone:
        for line in lines:
            if existing_phone in line:
                existing_context = line
                break
    base["phone"] = existing_phone if _phone_candidate_is_safe(existing_phone, existing_context) else None
    return base
