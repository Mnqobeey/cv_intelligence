import json

from fastapi.testclient import TestClient

from app.main import create_app
from app.parsers import parse_experience_section


THREE_ROLE_SAME_EMPLOYER_SAMPLE = {
    "cestacv_version": 1,
    "identity": {
        "full_name": "Test Candidate",
        "headline": "QA Intern",
        "availability": "",
        "region": "",
        "email": "test@example.com",
        "phone": "",
        "location": "",
        "linkedin": "",
        "portfolio": "",
    },
    "career_summary": "QA and student support candidate with hands-on experience across internship and university support roles for recruiter review workflows.",
    "skills": [{"category": "Testing", "items": ["Manual Testing"]}],
    "qualifications": [],
    "certifications": [],
    "training": [],
    "achievements": [],
    "languages": [],
    "interests": [],
    "references": [],
    "projects": [],
    "career_history": [
        {
            "job_title": "QA Intern",
            "company": "Cestasoft Solutions",
            "start_date": "Jun 2025",
            "end_date": "Present",
            "responsibilities": [],
        },
        {
            "job_title": "Student Assistant",
            "company": "Nelson Mandela University",
            "start_date": "Feb 2022",
            "end_date": "Oct 2024",
            "responsibilities": [],
        },
        {
            "job_title": "DigiReady Buddy",
            "company": "Nelson Mandela University",
            "start_date": "Feb 2022",
            "end_date": "Mar 2022",
            "responsibilities": [],
        },
    ],
    "additional_sections": [],
}


def test_structured_json_same_employer_roles_remain_distinct_in_template_and_preview():
    client = TestClient(create_app())

    response = client.post("/api/upload-text", json={"text": json.dumps(THREE_ROLE_SAME_EMPLOYER_SAMPLE)})
    assert response.status_code == 200, response.text
    payload = response.json()

    parsed_history = parse_experience_section(payload["template_state"]["career_history"])
    assert len(parsed_history) == 3
    assert [(entry["company"], entry["position"], entry["start_date"], entry["end_date"]) for entry in parsed_history] == [
        ("Cestasoft Solutions", "QA Intern", "Jun 2025", "Present"),
        ("Nelson Mandela University", "Student Assistant", "Feb 2022", "Oct 2024"),
        ("Nelson Mandela University", "DigiReady Buddy", "Feb 2022", "Mar 2022"),
    ]

    assert payload["preview_html"].count("experience-card") == 3
    assert "QA Intern" in payload["preview_html"]
    assert "Student Assistant" in payload["preview_html"]
    assert "DigiReady Buddy" in payload["preview_html"]
