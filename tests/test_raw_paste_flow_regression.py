from fastapi.testclient import TestClient

from app.main import create_app


RAW_PASTE_TEXT = """Lerato Mokoena
Senior Software Developer
Email: lerato@example.com
Phone: +27 82 555 1234
Location: Johannesburg, South Africa

Professional Profile
Results-driven Senior Software Developer with experience building enterprise web platforms, improving release quality, and mentoring delivery teams across complex client environments.

Technical Skills
C#, .NET, React, SQL, Azure DevOps

Employment History
BrightPath Technologies | Senior Software Developer | March 2022 | Present
Designed backend services; Improved release automation; Mentored developers

Education
BSc Computer Science | University of Johannesburg | 2019
"""


def test_raw_paste_flow_does_not_leak_employment_history_into_skills():
    client = TestClient(create_app())
    response = client.post("/api/upload-text", json={"text": RAW_PASTE_TEXT})
    assert response.status_code == 200, response.text
    payload = response.json()

    assert "Employment History" not in payload["template_state"]["skills"]
    assert "BrightPath Technologies | Senior Software Developer | March 2022 | Present" not in payload["template_state"]["skills"]

    review = client.post(
        f"/api/document/{payload['document_id']}/review-complete",
        json={"template_state": payload["template_state"]},
    )
    assert review.status_code == 200, review.text


def test_skill_validation_flags_experience_rows_as_contamination():
    client = TestClient(create_app())
    response = client.post("/api/upload-text", json={"text": RAW_PASTE_TEXT})
    assert response.status_code == 200, response.text
    payload = response.json()

    contaminated = dict(payload["template_state"])
    contaminated["skills"] = (
        "C#\n.NET\nEmployment History\n"
        "BrightPath Technologies | Senior Software Developer | March 2022 | Present"
    )
    update = client.post(f"/api/document/{payload['document_id']}/template", json={"skills": contaminated["skills"]})
    assert update.status_code == 200, update.text
    assert "Skills appear contaminated" in "\n".join(update.json()["workflow_state"]["blocking_issues"])
