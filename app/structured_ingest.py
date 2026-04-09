from __future__ import annotations

"""Helpers for ingesting canonical CestaCV JSON directly into the builder.

The original bug happened because valid pasted JSON could still be treated like
free text later in the pipeline. That let heuristic block detection and field
inference mutate canonical values. This module now owns a deterministic
structured-import path that parses once, trims recursively, validates the basic
schema shape, and hydrates the UI directly from the JSON object.
"""

import json
from typing import Any, Dict, Iterable, List, Tuple

from .source_views import build_pasted_text_source_view

STRUCTURED_IMPORT_MODE = "structured_json"
RAW_IMPORT_MODE = "raw_cv_text"
_EXPECTED_TOP_LEVEL_KEYS = {
    "cestacv_version",
    "identity",
    "career_summary",
    "skills",
    "certifications",
    "training",
    "achievements",
    "languages",
    "interests",
    "references",
    "projects",
    "qualifications",
    "career_history",
    "additional_sections",
}
_STRUCTURED_LIST_KEYS = {
    "skills",
    "qualifications",
    "certifications",
    "training",
    "achievements",
    "languages",
    "interests",
    "references",
    "projects",
    "career_history",
    "additional_sections",
}
_IDENTITY_KEYS = {
    "full_name",
    "headline",
    "availability",
    "region",
    "email",
    "phone",
    "location",
    "linkedin",
    "portfolio",
}


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    return str(value).strip()


def _list_lines(values: Iterable[Any]) -> List[str]:
    lines: List[str] = []
    for value in values or []:
        cleaned = _clean(value)
        if cleaned:
            lines.append(cleaned)
    return lines


def _key_value_lines(values: Any, field_order: Iterable[str]) -> List[str]:
    lines: List[str] = []
    for value in values or []:
        if isinstance(value, dict):
            parts = []
            for field in field_order:
                cleaned = _clean(value.get(field))
                if cleaned:
                    parts.append(cleaned)
            if parts:
                lines.append(" | ".join(parts))
            continue
        cleaned = _clean(value)
        if cleaned:
            lines.append(cleaned)
    return lines


def _skill_lines(skills: Any) -> List[str]:
    lines: List[str] = []
    for block in skills or []:
        if isinstance(block, dict):
            category = _clean(block.get("category"))
            items = [item for item in _list_lines(block.get("items") or []) if item]
            if category and items:
                lines.append(f"{category}: {', '.join(items)}")
            elif items:
                lines.extend(items)
        else:
            cleaned = _clean(block)
            if cleaned:
                lines.append(cleaned)
    return lines


def _qualification_lines(rows: Any) -> List[str]:
    lines: List[str] = []
    for row in rows or []:
        if not isinstance(row, dict):
            cleaned = _clean(row)
            if cleaned:
                lines.append(cleaned)
            continue
        parts = [_clean(row.get("qualification")), _clean(row.get("institution")), _clean(row.get("year"))]
        parts = [part for part in parts if part]
        if parts:
            lines.append(" | ".join(parts))
    return lines


def _certification_lines(rows: Any) -> List[str]:
    lines: List[str] = []
    for row in rows or []:
        if not isinstance(row, dict):
            cleaned = _clean(row)
            if cleaned:
                lines.append(cleaned)
            continue
        parts = [_clean(row.get("name")), _clean(row.get("provider")), _clean(row.get("year"))]
        parts = [part for part in parts if part]
        if parts:
            lines.append(" | ".join(parts))
    return lines


def _career_history_lines(rows: Any) -> Tuple[str, str]:
    summary_lines: List[str] = []
    history_lines: List[str] = []
    for row in rows or []:
        if not isinstance(row, dict):
            cleaned = _clean(row)
            if cleaned:
                history_lines.append(cleaned)
            continue
        job_title = _clean(row.get("job_title"))
        company = _clean(row.get("company"))
        start = _clean(row.get("start_date"))
        end = _clean(row.get("end_date")) or "Present"
        responsibilities = _list_lines(row.get("responsibilities") or [])
        meta_parts = [part for part in [company, job_title, start, end] if part]
        if meta_parts:
            history_lines.append(" | ".join(meta_parts))
        history_lines.extend(responsibilities)
        summary_parts = [part for part in [job_title, company, start, end] if part]
        if summary_parts:
            summary_lines.append(" | ".join(summary_parts))
    return "\n".join(summary_lines), "\n".join(history_lines)


def _additional_lines(rows: Any) -> List[str]:
    lines: List[str] = []
    for row in rows or []:
        if isinstance(row, dict):
            title = _clean(row.get("title"))
            content = _clean(row.get("content"))
            if title and content:
                lines.append(f"{title}: {content}")
            elif title:
                lines.append(title)
            elif content:
                lines.append(content)
        else:
            cleaned = _clean(row)
            if cleaned:
                lines.append(cleaned)
    return lines


def _project_lines(rows: Any) -> List[str]:
    lines: List[str] = []
    for row in rows or []:
        if isinstance(row, dict):
            name = _clean(row.get("name") or row.get("title") or row.get("project"))
            details = _clean(row.get("details") or row.get("description") or row.get("content"))
            if name and details:
                lines.append(f"{name} | {details}")
            elif name:
                lines.append(name)
            elif details:
                lines.append(details)
            continue
        cleaned = _clean(row)
        if cleaned:
            lines.append(cleaned)
    return lines


def _reference_lines(rows: Any) -> List[str]:
    lines: List[str] = []
    for row in rows or []:
        if isinstance(row, dict):
            parts = []
            for field in ("name", "role", "company", "email", "phone", "relationship"):
                cleaned = _clean(row.get(field))
                if cleaned:
                    parts.append(cleaned)
            if parts:
                lines.append(" | ".join(parts))
            continue
        cleaned = _clean(row)
        if cleaned:
            lines.append(cleaned)
    return lines


def _normalize_scalar_string(value: str) -> str:
    text = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if "\n" not in text:
        return text
    lines = [line.strip() for line in text.split("\n")]
    compact = [line for line in lines if line]
    return "\n".join(compact)


def _normalize_strings(value: Any) -> Any:
    if isinstance(value, str):
        return _normalize_scalar_string(value)
    if isinstance(value, list):
        return [_normalize_strings(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_strings(item) for key, item in value.items()}
    return value


def _structured_json_candidate(raw_text: str) -> str:
    text = (raw_text or "").strip().lstrip("\ufeff")
    if not text:
        return ""
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            body = "\n".join(lines[1:-1]).strip()
            if body.lower().startswith("json"):
                body = body[4:].lstrip()
            text = body
    return text.strip()


def _escape_control_chars_in_json_strings(raw_text: str) -> str:
    chars: List[str] = []
    in_string = False
    escape_next = False
    for char in raw_text:
        if in_string:
            if escape_next:
                chars.append(char)
                escape_next = False
                continue
            if char == "\\":
                chars.append(char)
                escape_next = True
                continue
            if char == '"':
                chars.append(char)
                in_string = False
                continue
            if char == "\n":
                chars.append("\\n")
                continue
            if char == "\r":
                chars.append("\\r")
                continue
            if char == "\t":
                chars.append("\\t")
                continue
            chars.append(char)
            continue
        chars.append(char)
        if char == '"':
            in_string = True
    return "".join(chars)


def _load_json_candidate(candidate: str) -> Tuple[Any, str]:
    try:
        return json.loads(candidate), "direct_json"
    except json.JSONDecodeError:
        repaired = _escape_control_chars_in_json_strings(candidate)
        if repaired == candidate:
            raise
        return json.loads(repaired), "repaired_json"


def _extract_embedded_structured_json(raw_text: str) -> Tuple[Dict[str, Any] | None, str | None]:
    decoder = json.JSONDecoder()
    for idx, char in enumerate(raw_text):
        if char not in "{[":
            continue
        snippet = raw_text[idx:].lstrip()
        if not snippet.startswith(("{", "[")):
            continue
        try:
            data, end = decoder.raw_decode(snippet)
        except json.JSONDecodeError:
            try:
                repaired = _escape_control_chars_in_json_strings(snippet)
                data, end = decoder.raw_decode(repaired)
                snippet = repaired
            except json.JSONDecodeError:
                continue
        trailing = snippet[end:].strip()
        if trailing and not all(part in {"Upload File", "Paste Text", "Paste CV Text"} for part in trailing.splitlines() if part.strip()):
            continue
        root = _coerce_structured_root(data)
        if root is None:
            continue
        normalized = _normalize_strings(root)
        if _matches_structured_cv_shape(normalized):
            return normalized, "embedded_json"
    return None, None


def _coerce_structured_root(data: Any) -> Dict[str, Any] | None:
    if isinstance(data, dict):
        return data
    if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
        return data[0]
    return None


def _matches_structured_cv_shape(data: Dict[str, Any]) -> bool:
    if not isinstance(data, dict):
        return False
    identity = data.get("identity")
    if not isinstance(identity, dict):
        return False
    if not _IDENTITY_KEYS.issubset(identity.keys()):
        return False
    if not isinstance(data.get("career_summary"), str):
        return False
    for key in _STRUCTURED_LIST_KEYS:
        if key in data and not isinstance(data.get(key), list):
            return False
    return _EXPECTED_TOP_LEVEL_KEYS.issubset(data.keys())


def detect_structured_cv_json(raw_text: str) -> Tuple[Dict[str, Any] | None, str | None]:
    candidate = _structured_json_candidate(raw_text)
    if candidate and candidate.startswith(("{", "[")):
        try:
            data, strategy = _load_json_candidate(candidate)
        except json.JSONDecodeError:
            data = None
            strategy = None
        if data is not None:
            data = _coerce_structured_root(data)
            if data is not None:
                data = _normalize_strings(data)
                if _matches_structured_cv_shape(data):
                    return data, strategy
    return _extract_embedded_structured_json(candidate)


def load_structured_cv_json(raw_text: str) -> Dict[str, Any] | None:
    data, _ = detect_structured_cv_json(raw_text)
    return data


def looks_like_structured_cv_json(raw_text: str) -> bool:
    return load_structured_cv_json(raw_text) is not None


def parse_structured_cv_json(raw_text: str) -> Dict[str, Any]:
    data, _ = detect_structured_cv_json(raw_text)
    if data is None:
        raise ValueError("Structured CV JSON must be a valid JSON object that matches the expected CV shape.")
    return data


def build_template_state_from_structured_json(data: Dict[str, Any]) -> Dict[str, str]:
    identity = data.get("identity") or {}
    career_summary, career_history = _career_history_lines(data.get("career_history") or [])
    template_state = {
        "full_name": _clean(identity.get("full_name")),
        "headline": _clean(identity.get("headline")),
        "availability": _clean(identity.get("availability")),
        "region": _clean(identity.get("region")),
        "email": _clean(identity.get("email")),
        "phone": _clean(identity.get("phone")),
        "location": _clean(identity.get("location")),
        "linkedin": _clean(identity.get("linkedin")),
        "portfolio": _clean(identity.get("portfolio")),
        "summary": _clean(data.get("career_summary")),
        "career_summary": career_summary,
        "skills": "\n".join(_skill_lines(data.get("skills") or [])),
        "education": "\n".join(_qualification_lines(data.get("qualifications") or [])),
        "certifications": "\n".join(_certification_lines(data.get("certifications") or [])),
        "training": "\n".join(_key_value_lines(data.get("training") or [], ("name", "provider", "year", "details"))),
        "career_history": career_history,
        "projects": "\n".join(_project_lines(data.get("projects") or [])),
        "volunteering": "",
        "publications": "",
        "languages": "\n".join(_key_value_lines(data.get("languages") or [], ("name", "proficiency", "level"))),
        "awards": "\n".join(_key_value_lines(data.get("achievements") or [], ("title", "name", "year", "details"))),
        "interests": "\n".join(_key_value_lines(data.get("interests") or [], ("name", "details"))),
        "references": "\n".join(_reference_lines(data.get("references") or [])),
        "additional_sections": "\n".join(_additional_lines(data.get("additional_sections") or [])),
    }
    if not template_state["career_history"] and career_summary:
        template_state["career_history"] = career_summary
    return template_state


def build_profile_from_structured_json(data: Dict[str, Any]) -> Dict[str, Any]:
    identity = data.get("identity") or {}
    qualification_rows = data.get("qualifications") or []
    certification_rows = data.get("certifications") or []
    return {
        "identity": {
            "full_name": _clean(identity.get("full_name")),
            "headline": _clean(identity.get("headline")),
            "availability": _clean(identity.get("availability")),
            "region": _clean(identity.get("region")),
            "email": _clean(identity.get("email")),
            "phone": _clean(identity.get("phone")),
            "location": _clean(identity.get("location")),
            "linkedin": _clean(identity.get("linkedin")),
            "portfolio": _clean(identity.get("portfolio")),
        },
        "summary": _clean(data.get("career_summary")),
        "career_summary": _clean(data.get("career_summary")),
        "skills": {
            "declared": _skill_lines(data.get("skills") or []),
            "inferred": {},
            "sa_context": [],
            "source_faithful": True,
        },
        "education": [
            {
                "qualification": _clean(row.get("qualification")),
                "institution": _clean(row.get("institution")),
                "end_date": _clean(row.get("year")),
            }
            for row in qualification_rows
            if isinstance(row, dict)
        ],
        "certifications": _certification_lines(certification_rows),
        "training": _key_value_lines(data.get("training") or [], ("name", "provider", "year", "details")),
        "projects": _project_lines(data.get("projects") or []),
        "languages": _key_value_lines(data.get("languages") or [], ("name", "proficiency", "level")),
        "awards": _key_value_lines(data.get("achievements") or [], ("title", "name", "year", "details")),
        "interests": _key_value_lines(data.get("interests") or [], ("name", "details")),
        "references": _reference_lines(data.get("references") or []),
        "experience": [
            {
                "position": _clean(row.get("job_title")),
                "company": _clean(row.get("company")),
                "start_date": _clean(row.get("start_date")),
                "end_date": _clean(row.get("end_date")),
                "responsibilities": _list_lines(row.get("responsibilities") or []),
                "projects": row.get("projects") or [],
                "client_engagements": _list_lines(row.get("client_engagements") or []),
                "summary": _clean(row.get("summary")),
            }
            for row in data.get("career_history") or []
            if isinstance(row, dict)
        ],
        "additional_sections": data.get("additional_sections") or [],
        "raw_sections": [],
        "document_meta": {"layout_flags": {"structured_json": True}, "import_mode": STRUCTURED_IMPORT_MODE},
    }


def build_structured_document_payload(data: Dict[str, Any], *, document_id: str, filename: str = "Structured CV JSON", parse_strategy: str = "direct_json") -> Dict[str, Any]:
    template_state = build_template_state_from_structured_json(data)
    raw_text = json.dumps(data, indent=2, ensure_ascii=False)
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
        "profile": build_profile_from_structured_json(data),
        "template_state": template_state,
        "detected_blocks": [],
        "review_confirmed": False,
        "structured_source": True,
        "import_mode": STRUCTURED_IMPORT_MODE,
        "structured_parse_strategy": parse_strategy,
    }
