from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.openrouter_structurer import OpenRouterStructuringError


def _fake_openrouter_json() -> dict:
    return {
        "cestacv_version": 1,
        "identity": {
            "full_name": "Alex Morgan",
            "headline": "Senior Software Developer",
            "availability": "Immediate",
            "region": "South Africa",
            "email": "alex@example.com",
            "phone": "+27 82 555 1234",
            "location": "Johannesburg",
            "linkedin": "",
            "portfolio": "",
        },
        "career_summary": (
            "Senior software developer with experience delivering production systems, "
            "supporting teams, and improving platform reliability across enterprise environments."
        ),
        "skills": [{"category": "Core Skills", "items": ["Python", "FastAPI", "SQL"]}],
        "qualifications": [{"qualification": "BSc Computer Science", "institution": "Example University", "year": "2018"}],
        "certifications": [],
        "training": [],
        "achievements": [],
        "languages": [],
        "interests": [],
        "references": [],
        "projects": [],
        "career_history": [
            {
                "job_title": "Senior Software Developer",
                "company": "Example Systems",
                "start_date": "Jan 2020",
                "end_date": "Present",
                "responsibilities": [
                    "Delivered backend services for production workflow automation.",
                    "Improved deployment reliability and supported engineering delivery.",
                ],
                "client_engagements": [],
                "projects": [],
            }
        ],
        "additional_sections": [],
    }


def test_upload_text_uses_openrouter_when_configured(monkeypatch):
    async def fake_structure(raw_text: str):
        assert "Alex Morgan" in raw_text
        return _fake_openrouter_json(), {
            "provider": "openrouter",
            "model": "test/model",
            "usage": {"total_tokens": 42},
            "generation_id": "gen-test",
        }

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("CV_INTELLIGENCE_LLM_MODE", "required")
    monkeypatch.setattr("app.routes.structure_cv_text_with_openrouter", fake_structure)

    client = TestClient(create_app())
    response = client.post(
        "/api/upload-text",
        json={"text": "Alex Morgan\nSenior Software Developer\nPython, FastAPI, SQL"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["import_mode"] == "openrouter_structured"
    assert payload["structured_source"] is True
    assert payload["template_state"]["full_name"] == "Alex Morgan"
    assert payload["profile"]["document_meta"]["llm"]["model"] == "test/model"


def test_required_openrouter_mode_reports_missing_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("CV_INTELLIGENCE_LLM_MODE", "required")

    client = TestClient(create_app())
    response = client.post("/api/upload-text", json={"text": "Alex Morgan\nDeveloper"})

    assert response.status_code == 503
    assert "OPENROUTER_API_KEY" in response.text


def test_openrouter_failure_returns_bad_gateway(monkeypatch):
    async def fake_structure(raw_text: str):
        raise OpenRouterStructuringError("provider unavailable")

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("CV_INTELLIGENCE_LLM_MODE", "required")
    monkeypatch.setattr("app.routes.structure_cv_text_with_openrouter", fake_structure)

    client = TestClient(create_app())
    response = client.post("/api/upload-text", json={"text": "Alex Morgan\nDeveloper"})

    assert response.status_code == 502
    assert "provider unavailable" in response.text


def test_openrouter_invalid_schema_response_returns_bad_gateway(monkeypatch):
    async def fake_structure(raw_text: str):
        return {
            "identity": {"full_name": "Alex Morgan"},
            "career_summary": "Too small",
            "career_history": [],
        }, {"provider": "openrouter", "model": "test/model"}

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("CV_INTELLIGENCE_LLM_MODE", "required")
    monkeypatch.setattr("app.routes.structure_cv_text_with_openrouter", fake_structure)

    client = TestClient(create_app())
    response = client.post("/api/upload-text", json={"text": "Alex Morgan\nDeveloper"})

    assert response.status_code == 502
    assert "does not match the CestaCV schema" in response.text


def test_health_reports_openrouter_configuration(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("CV_INTELLIGENCE_LLM_MODE", "required")

    client = TestClient(create_app())
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["openrouter_active"] is True
