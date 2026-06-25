import json

from fastapi.testclient import TestClient

from app.main import create_app


STRUCTURED_CV = {
    "cestacv_version": 1,
    "identity": {
        "full_name": "Alex Morgan",
        "headline": "Senior Software Developer",
        "availability": "Immediate",
        "region": "Gauteng",
        "email": "lerato@example.com",
        "phone": "+27 82 555 1234",
        "location": "Johannesburg, South Africa",
        "linkedin": "https://www.linkedin.com/in/lerato",
        "portfolio": "https://www.lerato.dev",
    },
    "career_summary": "Results-driven Senior Software Developer with extensive experience building scalable web applications, improving delivery quality, and mentoring teams across complex enterprise environments.",
    "skills": [{"category": "Programming Languages", "items": ["Python", "JavaScript"]}],
    "qualifications": [{"qualification": "BSc Computer Science", "institution": "Example University", "year": "2018"}],
    "certifications": [{"name": "AWS Certified Developer", "provider": "AWS", "year": "2024"}],
    "training": [],
    "achievements": [],
    "languages": [],
    "interests": [],
    "references": [],
    "projects": [],
    "career_history": [
        {
            "job_title": "Senior Software Developer",
            "company": "BrightPath Technologies",
            "start_date": "March 2022",
            "end_date": "Present",
            "responsibilities": ["Design backend services", "Mentor junior developers"],
        }
    ],
    "additional_sections": [{"title": "Driver's Licence", "content": "Code B"}],
}


def test_removed_prompt_endpoint_returns_410():
    client = TestClient(create_app())
    response = client.get("/api/structuring-prompt")
    assert response.status_code == 410


def test_structured_json_ingest_uses_lean_profile_response():
    client = TestClient(create_app())
    response = client.post("/api/upload-text", json={"text": json.dumps(STRUCTURED_CV)})
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["structured_source"] is True
    assert payload["import_mode"] == "structured_json"
    assert payload["template_state"]["full_name"] == "Alex Morgan"
    assert "Senior Software Developer" in payload["template_state"]["career_history"]
    assert payload["detected_blocks"] == []
    assert payload["source_sections"] == []
    assert "recommendations" not in payload
    assert payload["workflow_state"]["blocking_issues"] == []


def test_removed_restore_endpoint_returns_410_and_review_download_still_work():
    client = TestClient(create_app())
    uploaded = client.post("/api/upload-text", json={"text": json.dumps(STRUCTURED_CV)}).json()
    document_id = uploaded["document_id"]

    update = client.post(f"/api/document/{document_id}/template", json={"headline": "Principal Engineer"})
    assert update.status_code == 200, update.text
    assert update.json()["workflow_state"]["can_download"] is False

    restore = client.post(f"/api/document/{document_id}/restore-field", json={"target_key": "headline"})
    assert restore.status_code == 410

    review = client.post(
        f"/api/document/{document_id}/review-complete",
        json={"template_state": update.json()["template_state"]},
    )
    assert review.status_code == 200, review.text
    assert review.json()["workflow_state"]["can_download"] is True

    download = client.post(
        f"/api/document/{document_id}/download",
        json={"template_state": review.json()["template_state"]},
    )
    assert download.status_code == 200, download.text
    assert len(download.content) > 1000
