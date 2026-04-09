from fastapi.testclient import TestClient

from app.main import create_app


STRUCTURED_SECTION_TEXT = """
IDENTITY
Full Name: Rudzani Mofokeng
Professional Headline: C# Developer
Availability:
Region:
Email: rudzani902@gmail.com
Phone: 0623626109
Location: 3999 Crestfish street, Ext 20, Sky city
LinkedIn:
Portfolio: https://portfolio.example.com

CAREER SUMMARY
Experienced C# developer delivering internal tools, supporting recruiter-ready client work, and contributing to reliable business application delivery across fast-moving engagements.

SKILLS
Technical Skills: C#; .NET; SQL
Tools: Git; Azure DevOps

QUALIFICATIONS
Qualification: Matric
Institution: Sky City High School
Year: 2018

CERTIFICATIONS
Name: Azure Fundamentals
Provider:
Year: 2024

TRAINING
None listed

ACHIEVEMENTS
None listed

LANGUAGES
English

INTERESTS
None listed

REFERENCES
None listed

PROJECTS
Project: Internal Builder
Details: Built a profile-builder workflow

CAREER HISTORY
Job Title: C# Developer
Company: CestaSoft
Start Date: Jan 2024
End Date: Present
Responsibilities: Built internal tools; Supported client engagements

ADDITIONAL INFORMATION
None listed
""".strip()


def test_structured_section_text_uses_deterministic_mode_and_skips_detected_blocks():
    client = TestClient(create_app())
    response = client.post("/api/upload-text", json={"text": STRUCTURED_SECTION_TEXT})
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["structured_source"] is True
    assert payload["import_mode"] == "structured_section_text"
    assert payload["detected_blocks"] == []
    assert payload["source_sections"] == []
    assert payload["text_blocks"] == []
    assert payload["template_state"]["full_name"] == "Rudzani Mofokeng"
    assert payload["template_state"]["headline"] == "C# Developer"
    assert payload["template_state"]["region"] == ""
    assert payload["template_state"]["location"] == "3999 Crestfish street, Ext 20, Sky city"
    assert payload["template_state"]["portfolio"] == "https://portfolio.example.com"
    assert payload["template_state"]["summary"] == "Experienced C# developer delivering internal tools, supporting recruiter-ready client work, and contributing to reliable business application delivery across fast-moving engagements."
    assert payload["template_state"]["references"] == ""
    assert payload["template_state"]["projects"] == "Project: Internal Builder\nDetails: Built a profile-builder workflow"
    assert payload["template_state"]["additional_sections"] == ""
    assert "Full Name is required before build can pass." not in payload["workflow_state"]["blocking_issues"]


def test_structured_section_text_preserves_skill_categories_and_career_history_roles():
    client = TestClient(create_app())
    response = client.post("/api/upload-text", json={"text": STRUCTURED_SECTION_TEXT})
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["template_state"]["skills"].splitlines() == [
        "Technical Skills: C#; .NET; SQL",
        "Tools: Git; Azure DevOps",
    ]
    assert "CestaSoft | C# Developer | Jan 2024 | Present" in payload["template_state"]["career_history"]
    assert "Built internal tools" in payload["template_state"]["career_history"]
    assert "Supported client engagements" in payload["template_state"]["career_history"]
    assert payload["template_state"]["career_summary"] == "C# Developer | CestaSoft | Jan 2024 | Present"


def test_structured_section_text_review_passes_from_parsed_state():
    client = TestClient(create_app())
    upload = client.post("/api/upload-text", json={"text": STRUCTURED_SECTION_TEXT})
    assert upload.status_code == 200, upload.text
    uploaded = upload.json()

    review = client.post(
        f"/api/document/{uploaded['document_id']}/review-complete",
        json={"template_state": uploaded["template_state"]},
    )
    assert review.status_code == 200, review.text
    payload = review.json()

    assert payload["workflow_state"]["can_download"] is True
    assert payload["validated_export_json"]["identity"]["full_name"] == "Rudzani Mofokeng"
    assert payload["validated_export_json"]["identity"]["region"] == ""
    assert payload["validated_export_json"]["career_summary"] == "Experienced C# developer delivering internal tools, supporting recruiter-ready client work, and contributing to reliable business application delivery across fast-moving engagements."
    assert payload["validated_export_json"]["skills"] == [
        "Technical Skills: C#; .NET; SQL",
        "Tools: Git; Azure DevOps",
    ]
