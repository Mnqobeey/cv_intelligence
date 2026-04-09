"""Tests for the internal CV structurer module and the refactored upload flow."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.cv_structurer import (
    StructuringError,
    StructuringUnavailableError,
    _extract_json_object,
    _strip_markdown_fences,
    _validate_cv_shape,
    structure_cv_text,
)
from app.main import create_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_valid_cv_json() -> Dict[str, Any]:
    """Return a minimal CestaCV JSON that passes shape and profile validation."""
    return {
        "cestacv_version": 1,
        "identity": {
            "full_name": "Lerato Mokoena",
            "headline": "Senior Software Developer",
            "availability": "",
            "region": "",
            "email": "lerato@example.com",
            "phone": "+27 82 555 1234",
            "location": "Johannesburg, South Africa",
            "linkedin": "",
            "portfolio": "",
        },
        "career_summary": "Results-driven Senior Software Developer with extensive experience building scalable web applications, improving delivery quality, and mentoring teams across complex enterprise environments.",
        "skills": [{"category": "Technical", "items": ["Python", "SQL", "C#", ".NET"]}],
        "qualifications": [{"qualification": "BSc Computer Science", "institution": "University of Johannesburg", "year": "2019"}],
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
                "company": "BrightPath Technologies",
                "start_date": "March 2022",
                "end_date": "Present",
                "responsibilities": ["Designed backend services", "Improved release automation", "Mentored junior developers"],
            }
        ],
        "additional_sections": [],
    }


RAW_CV_TEXT = """Lerato Mokoena
Senior Software Developer
Email: lerato@example.com
Phone: +27 82 555 1234
Location: Johannesburg, South Africa

Professional Summary
Results-driven Senior Software Developer with extensive experience building scalable web applications, improving delivery quality, and mentoring teams across complex enterprise environments.

Technical Skills
Python, SQL, C#, .NET

Education
BSc Computer Science | University of Johannesburg | 2019

Career History
BrightPath Technologies | Senior Software Developer | March 2022 | Present
Designed backend services
Improved release automation
Mentored junior developers
"""


# ---------------------------------------------------------------------------
# Unit tests: JSON extraction helpers
# ---------------------------------------------------------------------------

class TestStripMarkdownFences:
    def test_plain_json(self):
        raw = '{"identity": {}}'
        assert _strip_markdown_fences(raw) == '{"identity": {}}'

    def test_json_fences(self):
        raw = '```json\n{"identity": {}}\n```'
        assert _strip_markdown_fences(raw) == '{"identity": {}}'

    def test_plain_fences(self):
        raw = '```\n{"identity": {}}\n```'
        assert _strip_markdown_fences(raw) == '{"identity": {}}'


class TestExtractJsonObject:
    def test_direct_json(self):
        data = _extract_json_object('{"key": "value"}')
        assert data == {"key": "value"}

    def test_json_with_preamble(self):
        raw = 'Here is the JSON:\n\n{"key": "value"}'
        data = _extract_json_object(raw)
        assert data == {"key": "value"}

    def test_markdown_fenced_json(self):
        raw = '```json\n{"key": "value"}\n```'
        data = _extract_json_object(raw)
        assert data == {"key": "value"}

    def test_invalid_json_returns_none(self):
        assert _extract_json_object("not json at all") is None

    def test_array_returns_none(self):
        assert _extract_json_object("[1, 2, 3]") is None


class TestValidateCvShape:
    def test_valid_shape(self):
        assert _validate_cv_shape(_minimal_valid_cv_json()) is True

    def test_missing_identity(self):
        data = _minimal_valid_cv_json()
        del data["identity"]
        assert _validate_cv_shape(data) is False

    def test_missing_career_summary(self):
        data = _minimal_valid_cv_json()
        del data["career_summary"]
        assert _validate_cv_shape(data) is False

    def test_identity_not_dict(self):
        data = _minimal_valid_cv_json()
        data["identity"] = "not a dict"
        assert _validate_cv_shape(data) is False


# ---------------------------------------------------------------------------
# Unit tests: provider unavailable
# ---------------------------------------------------------------------------

class TestStructuringUnavailable:
    def test_raises_when_no_api_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(StructuringUnavailableError):
            asyncio.get_event_loop().run_until_complete(
                structure_cv_text("some cv text")
            )


# ---------------------------------------------------------------------------
# Unit tests: structurer with mocked provider
# ---------------------------------------------------------------------------

class TestStructureCvText:
    def test_success_on_first_attempt(self, monkeypatch):
        valid_json = json.dumps(_minimal_valid_cv_json())
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        with patch("app.cv_structurer._call_provider", return_value=valid_json):
            data, strategy = asyncio.get_event_loop().run_until_complete(
                structure_cv_text(RAW_CV_TEXT)
            )
            assert strategy == "internally_structured"
            assert data["identity"]["full_name"] == "Lerato Mokoena"
            assert isinstance(data["career_history"], list)

    def test_success_with_markdown_fences(self, monkeypatch):
        valid_json = "```json\n" + json.dumps(_minimal_valid_cv_json()) + "\n```"
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        with patch("app.cv_structurer._call_provider", return_value=valid_json):
            data, strategy = asyncio.get_event_loop().run_until_complete(
                structure_cv_text(RAW_CV_TEXT)
            )
            assert strategy == "internally_structured"

    def test_retry_on_invalid_first_attempt(self, monkeypatch):
        valid_json = json.dumps(_minimal_valid_cv_json())
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        call_count = 0
        def mock_call(provider, text, *, repair_hint=""):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "this is not valid json"
            return valid_json

        with patch("app.cv_structurer._call_provider", side_effect=mock_call):
            data, strategy = asyncio.get_event_loop().run_until_complete(
                structure_cv_text(RAW_CV_TEXT)
            )
            assert call_count == 2
            assert strategy == "internally_structured"

    def test_raises_after_both_attempts_fail(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        with patch("app.cv_structurer._call_provider", return_value="garbage"):
            with pytest.raises(StructuringError):
                asyncio.get_event_loop().run_until_complete(
                    structure_cv_text(RAW_CV_TEXT)
                )


# ---------------------------------------------------------------------------
# Integration tests: upload flow uses structured path
# ---------------------------------------------------------------------------

class TestUploadUsesStructuredPath:
    """Verify that the upload routes prefer the internal structurer."""

    def _mock_structurer(self, monkeypatch):
        """Patch structure_cv_text to return valid JSON without calling an LLM."""
        valid_data = _minimal_valid_cv_json()

        async def fake_structure(raw_text):
            return valid_data, "internally_structured"

        monkeypatch.setattr("app.routes.structure_cv_text", fake_structure)

    def test_paste_text_uses_internal_structurer(self, monkeypatch):
        self._mock_structurer(monkeypatch)
        client = TestClient(create_app())
        response = client.post("/api/upload-text", json={"text": RAW_CV_TEXT})
        assert response.status_code == 200, response.text
        payload = response.json()

        # Should be internally structured, not raw fallback
        assert payload.get("import_mode") == "internally_structured"
        assert payload["template_state"]["full_name"] == "Lerato Mokoena"

    def test_paste_text_falls_back_to_raw_when_structurer_unavailable(self, monkeypatch):
        """When no API key is set, the legacy parser should handle the upload."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        client = TestClient(create_app())
        response = client.post("/api/upload-text", json={"text": RAW_CV_TEXT})
        assert response.status_code == 200, response.text
        payload = response.json()

        # Should fall back to raw parsing with explicit tag
        assert payload.get("import_mode") == "raw_fallback"

    def test_paste_text_falls_back_on_structurer_error(self, monkeypatch):
        """When the structurer raises, the legacy parser should take over."""
        async def failing_structurer(raw_text):
            raise StructuringError("mock failure")

        monkeypatch.setattr("app.routes.structure_cv_text", failing_structurer)
        client = TestClient(create_app())
        response = client.post("/api/upload-text", json={"text": RAW_CV_TEXT})
        assert response.status_code == 200, response.text
        payload = response.json()

        assert payload.get("import_mode") == "raw_fallback"


# ---------------------------------------------------------------------------
# Regression: structured JSON import still works
# ---------------------------------------------------------------------------

class TestStructuredJsonImportPreserved:
    """Existing structured JSON imports must not regress."""

    def test_direct_json_paste_uses_structured_ingest(self):
        from tests.test_structured_json_import_regression import STRUCTURED_JSON_SAMPLE

        client = TestClient(create_app())
        response = client.post(
            "/api/upload-text",
            json={"text": json.dumps(STRUCTURED_JSON_SAMPLE)},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["import_mode"] == "structured_json"
        assert payload["structured_source"] is True
        assert payload["template_state"]["full_name"] == "Rudzani Mofokeng"


# ---------------------------------------------------------------------------
# Regression: prompt endpoint is gone
# ---------------------------------------------------------------------------

class TestPromptEndpointRemoved:
    def test_structuring_prompt_endpoint_returns_404(self):
        client = TestClient(create_app())
        response = client.get("/api/structuring-prompt")
        # FastAPI returns 404 for unregistered routes (or 405)
        assert response.status_code in (404, 405)


# ---------------------------------------------------------------------------
# Regression: prompt UI elements are gone from HTML
# ---------------------------------------------------------------------------

class TestPromptUIRemoved:
    def test_prompt_card_not_in_template(self):
        template = Path("app/templates/index.html").read_text()
        assert 'id="promptCard"' not in template
        assert 'id="viewPromptBtn"' not in template
        assert 'id="copyPromptBtn"' not in template
        assert 'id="promptPresetList"' not in template
        assert 'id="promptGuidance"' not in template

    def test_prompt_functions_not_in_js(self):
        js = Path("app/static/js/app.js").read_text()
        assert "renderStructuringPromptFramework" not in js
        assert "loadStructuringPrompt" not in js
        assert "copyStructuringPrompt" not in js
        assert "togglePromptPreview" not in js
        assert "navigator.clipboard.writeText(activePrompt.prompt" not in js


# ---------------------------------------------------------------------------
# End-to-end: upload → review → DOCX download via internal structurer
# ---------------------------------------------------------------------------

class TestEndToEndInternalStructurerFlow:
    """Prove the full pipeline: raw text → structurer → review → DOCX."""

    def _mock_structurer(self, monkeypatch):
        valid_data = _minimal_valid_cv_json()
        async def fake_structure(raw_text):
            return valid_data, "internally_structured"
        monkeypatch.setattr("app.routes.structure_cv_text", fake_structure)

    def test_upload_review_download_via_structurer(self, monkeypatch):
        self._mock_structurer(monkeypatch)
        client = TestClient(create_app())

        # Step 1: Upload raw CV text
        upload = client.post("/api/upload-text", json={"text": RAW_CV_TEXT})
        assert upload.status_code == 200, upload.text
        data = upload.json()

        assert data["import_mode"] == "internally_structured"
        assert data["structured_source"] is True
        assert data["template_state"]["full_name"] == "Lerato Mokoena"
        assert data["template_state"]["headline"] == "Senior Software Developer"
        assert "preview_html" in data
        assert len(data["preview_html"]) > 100

        doc_id = data["document_id"]

        # Step 2: Mark review complete
        review = client.post(
            f"/api/document/{doc_id}/review-complete",
            json={"template_state": data["template_state"]},
        )
        assert review.status_code == 200, review.text
        review_data = review.json()
        assert review_data["workflow_state"]["can_download"] is True
        assert "validated_export_json" in review_data
        assert review_data["validated_export_json"]["identity"]["full_name"] == "Lerato Mokoena"

        # Step 3: Download DOCX
        download = client.post(
            f"/api/document/{doc_id}/download",
            json={"template_state": data["template_state"]},
        )
        assert download.status_code == 200
        assert download.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        assert len(download.content) > 1000
        assert "Lerato_Mokoena" in download.headers.get("content-disposition", "")

    def test_fallback_upload_review_download_also_works(self, monkeypatch):
        """Legacy fallback path must still produce a downloadable DOCX."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        client = TestClient(create_app())

        upload = client.post("/api/upload-text", json={"text": RAW_CV_TEXT})
        assert upload.status_code == 200, upload.text
        data = upload.json()
        assert data["import_mode"] == "raw_fallback"

        doc_id = data["document_id"]

        review = client.post(
            f"/api/document/{doc_id}/review-complete",
            json={"template_state": data["template_state"]},
        )
        assert review.status_code == 200, review.text
        assert review.json()["workflow_state"]["can_download"] is True

        download = client.post(
            f"/api/document/{doc_id}/download",
            json={"template_state": data["template_state"]},
        )
        assert download.status_code == 200
        assert len(download.content) > 1000

    def test_import_mode_visible_in_profile_metadata(self, monkeypatch):
        """The import_mode must be propagated into profile.document_meta."""
        self._mock_structurer(monkeypatch)
        client = TestClient(create_app())

        upload = client.post("/api/upload-text", json={"text": RAW_CV_TEXT})
        assert upload.status_code == 200
        data = upload.json()

        profile = data.get("profile", {})
        doc_meta = profile.get("document_meta", {})
        assert doc_meta.get("import_mode") == "internally_structured"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestStructurerEdgeCases:
    def test_empty_cv_produces_valid_shape(self):
        data = _minimal_valid_cv_json()
        data["career_summary"] = ""
        data["career_history"] = []
        data["skills"] = []
        assert _validate_cv_shape(data) is True
