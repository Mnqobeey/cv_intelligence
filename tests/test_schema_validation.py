from pathlib import Path

import pytest
from pydantic import ValidationError

from app.docx_exporter import build_final_profile_payload
from app.schema import validate_export_payload


def sample_state():
    return {
        "full_name": "George Thabiso Mpopo",
        "headline": "Senior / Lead Software Engineer",
        "availability": "Immediate / Negotiable",
        "region": "South Africa",
        "summary": "Experienced software engineering leader delivering enterprise systems, improving delivery quality, and guiding complex platform implementation across regulated environments.",
        "skills": "Languages & Frameworks: C#, .NET",
        "education": "BSc Degree in Computer Science | University of Zululand | 2007",
        "certifications": "TOGAF 9.2 Certification (2018)",
        "career_history": (
            "Senior Full-Stack Software Developer - Gijima Technologies Apr 2024 - Present\n"
            "Led delivery of enterprise software platforms."
        ),
    }


def test_export_payload_schema_validation_passes():
    payload = build_final_profile_payload(sample_state(), profile=None)
    validated = validate_export_payload(payload)
    assert validated.identity.full_name == "George Thabiso Mpopo"
    assert "Gijima Technologies" in validated.career_history[0].company


def test_export_payload_schema_rejects_academic_career_history():
    payload = build_final_profile_payload(sample_state(), profile=None)
    payload.career_history = [
        {
            "position": "Database Systems Module",
            "company": "University of Zululand",
            "start_date": "2023",
            "end_date": "2023",
            "responsibilities": ["Completed semester coursework and practical assignments."],
        }
    ]
    with pytest.raises(ValidationError):
        validate_export_payload(payload)


def test_export_payload_schema_allows_academic_employment_roles_with_responsibilities():
    payload = build_final_profile_payload(sample_state(), profile=None)
    payload.career_history = [
        {
            "position": "Lab Demonstrator",
            "company": "University of Zululand",
            "start_date": "2023",
            "end_date": "2023",
            "responsibilities": [
                "Guided students during practical lab sessions.",
                "Assisted with setup and troubleshooting during demonstrations.",
            ],
        }
    ]
    validated = validate_export_payload(payload)
    assert validated.career_history[0].job_title == "Lab Demonstrator"
