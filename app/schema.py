from __future__ import annotations

"""Strict structured-data contract for the final CestaSoft profile export."""

import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EDUCATION_RECORD_MARKERS = {
    "module", "subject", "coursework", "semester", "assessment", "assignment",
    "tutorial", "practical", "exam", "curriculum", "faculty", "department",
    "degree", "diploma", "honours", "honors", "bachelor", "masters", "doctorate", "nqf",
    "programme", "program", "course", "qualification", "major", "minor",
}
EMPLOYMENT_ROLE_MARKERS = {
    "assistant", "lab demonstrator", "demonstrator", "tutor", "research assistant",
    "researcher", "intern", "coordinator", "officer", "administrator", "developer",
    "analyst", "engineer", "consultant", "manager", "lecturer", "facilitator",
    "technician", "student assistant", "conference", "supervisor", "lead",
}
REFERENCE_MARKERS = {"reference", "referee", "manager", "lecturer", "supervisor", "director", "professor"}


def _clean(value: Optional[str]) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    if text.lower() in {"", "n/a", "na", "none", "null"}:
        return ""
    return text


def _strip_leading_bullets(value: Optional[str]) -> str:
    text = _clean(value)
    return _clean(re.sub(r"^(?:[\u2022\u00b7\-\*\u25cf\?]+\s*)+", "", text))


def _looks_education_like(text: str) -> bool:
    haystack = _clean(text).lower()
    return any(term in haystack for term in EDUCATION_RECORD_MARKERS)


def _looks_like_employment_role(text: str) -> bool:
    haystack = _clean(text).lower()
    return any(term in haystack for term in EMPLOYMENT_ROLE_MARKERS)


def _is_pure_education_record(job_title: str, company: str, bullets: List[str], client_engagements: List[str], projects: List["RoleProjectSchema"]) -> bool:
    cleaned_title = _clean(job_title)
    cleaned_company = _clean(company)
    bullet_text = " ".join(_clean(item) for item in bullets if _clean(item))
    engagement_text = " ".join(_clean(item) for item in client_engagements if _clean(item))
    project_text = " ".join(
        " ".join(part for part in [_clean(project.name), _clean(project.details)] if part)
        for project in projects
    )
    combined = " ".join(part for part in [cleaned_title, cleaned_company, bullet_text, engagement_text, project_text] if part)
    if _looks_like_employment_role(cleaned_title):
        return False
    if not _looks_education_like(combined):
        return False
    has_work_evidence = bool(bullet_text or engagement_text or project_text)
    return not has_work_evidence or _looks_education_like(cleaned_title)


def _looks_like_reference(text: str) -> bool:
    haystack = _clean(text).lower()
    return any(term in haystack for term in REFERENCE_MARKERS)


class IdentitySchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(..., min_length=2)
    headline: str = Field(..., min_length=2)
    availability: Optional[str] = None
    region: Optional[str] = None

    @field_validator("full_name", "headline", "availability", "region")
    @classmethod
    def normalize_fields(cls, value: Optional[str]) -> Optional[str]:
        return _clean(value) if value is not None else value

    @model_validator(mode="after")
    def reject_reference_identity(self) -> "IdentitySchema":
        combined = f"{self.full_name} {self.headline}"
        if _looks_like_reference(combined):
            raise ValueError("Identity cannot come from reference data.")
        return self


class QualificationSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    degree: str = Field(..., min_length=2)
    institution: str = Field(..., min_length=2)
    year: Optional[str] = None

    @field_validator("degree", "institution", "year")
    @classmethod
    def normalize_fields(cls, value: Optional[str]) -> Optional[str]:
        return _clean(value) if value is not None else value


class CertificationSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cert_name: str = Field(..., min_length=2)
    provider: Optional[str] = None
    year: Optional[str] = None

    @field_validator("cert_name", "provider", "year")
    @classmethod
    def normalize_fields(cls, value: Optional[str]) -> Optional[str]:
        return _strip_leading_bullets(value) if value is not None else value


class RoleProjectSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=2)
    details: Optional[str] = None

    @field_validator("name", "details")
    @classmethod
    def normalize_fields(cls, value: Optional[str]) -> Optional[str]:
        return _clean(value) if value is not None else value


class CareerHistorySchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_title: str = Field(..., min_length=2)
    company: str = Field(..., min_length=2)
    dates: str = Field(..., min_length=2)
    bullets: List[str] = Field(default_factory=list)
    client_engagements: List[str] = Field(default_factory=list)
    projects: List[RoleProjectSchema] = Field(default_factory=list)

    @field_validator("job_title", "company", "dates")
    @classmethod
    def normalize_core_fields(cls, value: str) -> str:
        return _clean(value)

    @field_validator("bullets")
    @classmethod
    def normalize_bullets(cls, value: List[str]) -> List[str]:
        cleaned: List[str] = []
        seen = set()
        for item in value:
            bullet = _clean(item)
            if not bullet:
                continue
            key = bullet.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(bullet)
        return cleaned[:6]

    @field_validator("client_engagements")
    @classmethod
    def normalize_client_engagements(cls, value: List[str]) -> List[str]:
        cleaned: List[str] = []
        seen = set()
        for item in value:
            engagement = _clean(item)
            if not engagement:
                continue
            key = engagement.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(engagement)
        return cleaned[:8]

    @model_validator(mode="after")
    def reject_academic_entries(self) -> "CareerHistorySchema":
        if _is_pure_education_record(self.job_title, self.company, self.bullets, self.client_engagements, self.projects):
            raise ValueError("Pure education records are not allowed in career_history.")
        return self


class CandidateProfileSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity: IdentitySchema
    career_summary: str = Field(..., min_length=20)
    skills: List[str] = Field(default_factory=list)
    qualifications: List[QualificationSchema] = Field(default_factory=list)
    certifications: List[CertificationSchema] = Field(default_factory=list)
    career_history: List[CareerHistorySchema] = Field(default_factory=list)

    @field_validator("career_summary")
    @classmethod
    def normalize_summary(cls, value: str) -> str:
        return _clean(value)

    @field_validator("skills")
    @classmethod
    def normalize_skills(cls, value: List[str]) -> List[str]:
        cleaned: List[str] = []
        seen = set()
        for item in value:
            skill = _clean(item)
            if not skill:
                continue
            key = skill.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(skill)
        return cleaned



def build_export_schema_payload(final_payload: Any) -> Dict[str, Any]:
    qualifications = [
        {
            "degree": item.get("qualification", ""),
            "institution": item.get("institution", ""),
            "year": item.get("end_date", ""),
        }
        for item in final_payload.qualifications
        if any(item.values())
    ]
    certifications = []
    for item in final_payload.certifications:
        if isinstance(item, dict):
            name = _clean(item.get("name") or item.get("cert_name"))
            provider = _clean(item.get("provider"))
            year = _clean(item.get("year"))
            if name:
                certifications.append({"cert_name": name, "provider": provider, "year": year})
            continue
        text = _clean(item)
        if not text:
            continue
        parts = [_clean(part) for part in re.split(r"\s*\|\s*", text) if _clean(part)]
        if len(parts) >= 3:
            certifications.append({"cert_name": parts[0], "provider": parts[1], "year": parts[2]})
            continue
        match = re.search(r"\((\d{4}|In Progress|Present)\)$", text, re.I)
        year = match.group(1) if match else ""
        name = re.sub(r"\s*\((\d{4}|In Progress|Present)\)$", "", text, flags=re.I).strip()
        certifications.append({"cert_name": name, "provider": "", "year": year})
    career_history = []
    for entry in final_payload.career_history:
        start_date = _clean(entry.get("start_date"))
        end_date = _clean(entry.get("end_date"))
        dates = " – ".join(part for part in [start_date, end_date] if part)
        projects = []
        for project in entry.get("projects", []) or []:
            if isinstance(project, dict):
                name = _clean(project.get("name"))
                details = _clean(project.get("details"))
            else:
                name = _clean(project)
                details = ""
            if name:
                projects.append({"name": name, "details": details})
        mapped = {
            "job_title": _clean(entry.get("position")),
            "company": _clean(entry.get("company")),
            "dates": _clean(dates or entry.get("dates")),
            "bullets": entry.get("responsibilities", []) or [],
            "client_engagements": entry.get("client_engagements", []) or [],
            "projects": projects,
        }
        if mapped["job_title"] and mapped["company"] and len(mapped["dates"]) >= 2:
            career_history.append(mapped)
    skills = []
    for group in final_payload.skills:
        category = _clean(group.get("category"))
        items = _clean(group.get("items"))
        if category and items:
            skills.append(f"{category}: {items}")
        elif items:
            skills.append(items)
    return {
        "identity": {
            "full_name": final_payload.identity.get("full_name", ""),
            "headline": final_payload.identity.get("headline", ""),
            "availability": final_payload.identity.get("availability", ""),
            "region": final_payload.identity.get("region", ""),
        },
        "career_summary": final_payload.summary,
        "skills": skills,
        "qualifications": qualifications,
        "certifications": certifications,
        "career_history": career_history,
    }



def validate_export_payload(final_payload: Any) -> CandidateProfileSchema:
    return CandidateProfileSchema.model_validate(build_export_schema_payload(final_payload))
