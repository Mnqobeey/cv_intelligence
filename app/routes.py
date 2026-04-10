from __future__ import annotations

"""HTTP routes for the CestaCV Intelligence Studio."""

import asyncio
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from .constants import EXPORT_DIR, FIELD_DEFINITIONS, FIELD_MAP, MAX_UPLOAD_SIZE_BYTES, TEMPLATE_COPY, UPLOAD_DIR
from .models import build_detected_blocks
from .normalizers import (
    apply_selection_to_state,
    build_review_board,
    build_workflow_state,
    clean_selected_text,
    profile_from_sections,
    profile_to_template_state,
    validate_profile_readiness,
)
from .parsers import build_source_sections, build_text_blocks, parse_sections
from .docx_exporter import build_final_profile_payload, build_profile_docx_from_schema
from .recommendations import build_recommendations
from .renderers import build_preview_html
from .schema import validate_export_payload
from .source_views import build_pasted_text_source_view, build_source_view
from .structured_ingest import build_structured_document_payload, detect_structured_cv_json
from .structured_section_ingest import build_structured_section_document_payload, looks_like_structured_section_text, parse_structured_section_text
from .structured_prompt import get_structuring_prompt_payload
from .storage import SQLiteDocumentStore
from .utils_text import extract_text


def register_routes(templates: Jinja2Templates, store: SQLiteDocumentStore) -> APIRouter:
    router = APIRouter()
    logger = logging.getLogger(__name__)

    def normalize_template_state(template_state: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(template_state or {})
        certifications = normalized.get("certifications")
        if isinstance(certifications, str):
            cleaned_lines = []
            for line in certifications.splitlines():
                cleaned = re.sub(r"^(?:[\u2022\u00b7\-\*\u25cf\?]+\s*)+", "", str(line or "").strip())
                cleaned = re.sub(r"\s+", " ", cleaned).strip()
                if cleaned:
                    cleaned_lines.append(cleaned)
            normalized["certifications"] = "\n".join(cleaned_lines)
        return normalized

    @router.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        return templates.TemplateResponse(
            request,
            "index.html",
            {"field_definitions": FIELD_DEFINITIONS, "template_file_name": TEMPLATE_COPY.name if TEMPLATE_COPY.exists() else ""},
        )

    @router.get("/api/structuring-prompt")
    async def structuring_prompt():
        return get_structuring_prompt_payload()

    async def safe_request_json(request: Request) -> Dict[str, Any]:
        body = await request.body()
        if not body or not body.strip():
            return {}
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc.msg}.") from exc
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="JSON payload must be an object.")
        return data

    def get_document_or_404(document_id: str) -> Dict[str, Any]:
        document = store.get_document(document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found.")
        return document

    def refresh_document_state(document: Dict[str, Any], template_state: Dict[str, str] | None = None, *, persist_review_reset: bool = False) -> Dict[str, Any]:
        if template_state is not None:
            document["template_state"] = normalize_template_state(template_state)
        else:
            document["template_state"] = normalize_template_state(document.get("template_state", {}))
        document = enforce_structured_import_contract(document)
        document.setdefault("field_history", {})
        if persist_review_reset:
            document["review_confirmed"] = False
            document.pop("validated_export_json", None)
        issues = validate_profile_readiness(document["template_state"])
        document["_cached_issues"] = issues
        document["review_board"] = build_review_board(document["template_state"], document.get("profile"), precomputed_issues=issues)
        document["workflow_state"] = build_workflow_state(document["template_state"], document["review_board"], document.get("review_confirmed", False), precomputed_issues=issues)
        return document

    def validated_schema_from_document(document: Dict[str, Any], template_state: Dict[str, str] | None = None):
        final_payload = build_final_profile_payload(template_state or document["template_state"], document.get("profile"))
        return validate_export_payload(final_payload)

    def schema_error_detail(exc: ValidationError) -> Dict[str, Any]:
        issues: list[str] = []
        for err in exc.errors():
            message = str(err.get("msg") or "Schema validation failed.")
            if message.startswith("Value error, "):
                message = message[len("Value error, "):]
            if message not in issues:
                issues.append(message)
        return {
            "message": "Profile failed schema validation.",
            "issues": issues or ["Schema validation failed."],
        }

    def restorable_fields(document: Dict[str, Any]) -> list[str]:
        history = document.get("field_history") or {}
        return [key for key, entries in history.items() if entries]

    def enforce_structured_import_contract(document: Dict[str, Any]) -> Dict[str, Any]:
        if document.get("import_mode") != "structured_json":
            return document
        document["structured_source"] = True
        document["sections"] = []
        document["text_blocks"] = []
        document["source_sections"] = []
        document["detected_blocks"] = []
        document["annotations"] = document.get("annotations") or []
        profile = document.get("profile") or {}
        if isinstance(profile, dict):
            profile["raw_sections"] = []
            profile.setdefault("document_meta", {})
            profile["document_meta"]["import_mode"] = "structured_json"
            if document.get("structured_parse_strategy"):
                profile["document_meta"]["structured_parse_strategy"] = document["structured_parse_strategy"]
            document["profile"] = profile
        required_keys = ("full_name", "headline")
        missing = [key for key in required_keys if not (document.get("template_state") or {}).get(key)]
        if missing:
            logger.warning("Structured import missing required hydrated fields: %s", ", ".join(missing))
        return document

    def build_document_response(document: Dict[str, Any]) -> Dict[str, Any]:
        document = enforce_structured_import_contract(document)
        return {
            **document,
            "preview_html": build_preview_html(document["template_state"], document.get("profile"), precomputed_issues=document.get("_cached_issues")),
            "recommendations": build_recommendations(document.get("review_board"), document.get("detected_blocks") or []),
            "restorable_fields": restorable_fields(document),
        }


    @router.post("/api/upload")
    async def upload_cv(file: UploadFile = File(...)):
        store.cleanup_expired_artifacts()
        ext = Path(file.filename or "").suffix.lower()
        if ext not in {".pdf", ".docx", ".txt", ".md"}:
            raise HTTPException(status_code=400, detail="Unsupported file type. Use PDF, DOCX, TXT, or MD.")
        payload = await file.read()
        if not payload:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")
        if len(payload) > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(status_code=413, detail=f"File exceeds the {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB upload limit.")

        document_id = str(uuid.uuid4())
        file_path = UPLOAD_DIR / f"{document_id}{ext}"
        file_path.write_bytes(payload)

        raw_text = ""
        structured = None
        structured_strategy = None
        if ext in {".txt", ".md"}:
            decoded_payload = payload.decode("utf-8", errors="ignore")
            structured, structured_strategy = detect_structured_cv_json(decoded_payload)
            if structured is not None:
                raw_text = decoded_payload.strip()
        structured_sections = None
        if structured is None:
            raw_text = extract_text(file_path)
            if not raw_text.strip():
                file_path.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail="No text could be extracted from the file.")
            structured, structured_strategy = detect_structured_cv_json(raw_text)
            if structured is None and looks_like_structured_section_text(raw_text):
                structured_sections = parse_structured_section_text(raw_text)

        if structured is not None:
            document_payload = build_structured_document_payload(structured, document_id=document_id, filename=file.filename or "Structured CV JSON", parse_strategy=structured_strategy or "direct_json")
            document_payload["path"] = str(file_path)
            document_payload["source_view"] = build_source_view(file_path, document_id)
        elif structured_sections is not None:
            document_payload = build_structured_section_document_payload(structured_sections, document_id=document_id, filename=file.filename or "Structured Section CV Text")
            document_payload["path"] = str(file_path)
            document_payload["source_view"] = build_source_view(file_path, document_id)
        else:
            sections = parse_sections(raw_text)
            original_name_path = file_path.parent / (file.filename or file_path.name)
            profile = profile_from_sections(raw_text, sections, original_name_path)
            template_state = profile_to_template_state(profile)
            text_blocks = build_text_blocks(raw_text)
            source_sections = build_source_sections(sections)
            detected_blocks = build_detected_blocks(sections)
            source_view = build_source_view(file_path, document_id)

            document_payload = {
                "document_id": document_id,
                "filename": file.filename,
                "path": str(file_path),
                "raw_text": raw_text,
                "sections": [section.__dict__ for section in sections],
                "text_blocks": text_blocks,
                "source_sections": source_sections,
                "source_view": source_view,
                "annotations": [],
                "profile": profile,
                "template_state": template_state,
                "detected_blocks": detected_blocks,
                "review_confirmed": False,
            }
        refresh_document_state(document_payload)
        store.save_document(document_id, document_payload)
        return build_document_response(document_payload)

    @router.post("/api/upload-text")
    async def upload_text(request: Request):
        store.cleanup_expired_artifacts()
        data = await safe_request_json(request)
        input_text = data.get("text")
        if input_text is None:
            raise HTTPException(status_code=400, detail="No CV text provided. Paste your CV content and try again.")
        raw_text = str(input_text).strip()
        if not raw_text:
            raise HTTPException(status_code=400, detail="No CV text provided. Paste your CV content and try again.")
        if len(raw_text) > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(status_code=413, detail=f"Pasted text exceeds the {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB limit.")

        from .utils_text import clean_extracted_text

        document_id = str(uuid.uuid4())
        structured, structured_strategy = detect_structured_cv_json(raw_text)
        if structured is not None:
            document_payload = build_structured_document_payload(structured, document_id=document_id, parse_strategy=structured_strategy or "direct_json")
        elif looks_like_structured_section_text(raw_text):
            parsed_sections = parse_structured_section_text(raw_text)
            document_payload = build_structured_section_document_payload(parsed_sections, document_id=document_id)
        else:
            raw_text = clean_extracted_text(raw_text)
            if not raw_text:
                raise HTTPException(status_code=400, detail="The pasted text contained no usable content after cleanup.")
            sections = parse_sections(raw_text)
            dummy_path = Path("pasted_cv.txt")
            profile = profile_from_sections(raw_text, sections, dummy_path)
            template_state = profile_to_template_state(profile)
            text_blocks = build_text_blocks(raw_text)
            source_sections = build_source_sections(sections)
            detected_blocks = build_detected_blocks(sections)
            source_view = build_pasted_text_source_view(raw_text)

            document_payload = {
                "document_id": document_id,
                "filename": "Pasted CV Text",
                "path": None,
                "raw_text": raw_text,
                "sections": [section.__dict__ for section in sections],
                "text_blocks": text_blocks,
                "source_sections": source_sections,
                "source_view": source_view,
                "annotations": [],
                "profile": profile,
                "template_state": template_state,
                "detected_blocks": detected_blocks,
                "review_confirmed": False,
            }
        refresh_document_state(document_payload)
        store.save_document(document_id, document_payload)
        return build_document_response(document_payload)

    @router.get("/api/document/{document_id}")
    async def get_document(document_id: str):
        def _sync():
            document = refresh_document_state(get_document_or_404(document_id))
            store.save_document(document_id, document)
            return build_document_response(document)
        return await asyncio.to_thread(_sync)

    @router.post("/api/document/{document_id}/annotate")
    async def annotate_text(document_id: str, selected_text: str = Form(...), target_key: str = Form(...), mode: str = Form("replace"), source_block_id: str = Form("manual"), source_label: str = Form("")):
        if target_key not in FIELD_MAP:
            raise HTTPException(status_code=400, detail="Invalid target field.")
        selected_text = selected_text.strip()
        if not selected_text:
            raise HTTPException(status_code=400, detail="No selected text provided.")

        def _sync():
            document = get_document_or_404(document_id)
            field_meta = FIELD_MAP[target_key]
            cleaned_text = clean_selected_text(selected_text, source_label)
            previous_value = document["template_state"].get(target_key, "")
            apply_selection_to_state(document, selected_text, target_key, mode, source_block_id, source_label)
            new_value = document["template_state"].get(target_key, "")
            if previous_value != new_value:
                document.setdefault("field_history", {}).setdefault(target_key, []).append(previous_value)
            document["annotations"].insert(0, {
                "id": str(uuid.uuid4())[:8],
                "text": cleaned_text or selected_text,
                "target_key": target_key,
                "target_label": field_meta["label"],
                "source_block_id": source_block_id,
                "source_label": source_label,
                "mode": mode,
            })
            refresh_document_state(document, persist_review_reset=True)
            store.save_document(document_id, document)
            return {
                "annotations": document["annotations"],
                "template_state": document["template_state"],
                "review_board": document["review_board"],
                "workflow_state": document["workflow_state"],
                "preview_html": build_preview_html(document["template_state"], document.get("profile"), precomputed_issues=document.get("_cached_issues")),
                "recommendations": build_recommendations(document.get("review_board"), document.get("detected_blocks") or []),
                "restorable_fields": restorable_fields(document),
            }
        return await asyncio.to_thread(_sync)

    @router.post("/api/document/{document_id}/template")
    async def update_template(document_id: str, request: Request):
        data = await safe_request_json(request)

        def _sync():
            document = get_document_or_404(document_id)
            for key, value in data.items():
                if key in FIELD_MAP:
                    previous_value = document["template_state"].get(key, "")
                    if previous_value != value:
                        document.setdefault("field_history", {}).setdefault(key, []).append(previous_value)
                    document["template_state"][key] = value
            document["template_state"] = normalize_template_state(document["template_state"])
            refresh_document_state(document, persist_review_reset=True)
            store.save_document(document_id, document)
            return {
                "template_state": document["template_state"],
                "review_board": document["review_board"],
                "workflow_state": document["workflow_state"],
                "preview_html": build_preview_html(document["template_state"], document.get("profile"), precomputed_issues=document.get("_cached_issues")),
                "recommendations": build_recommendations(document.get("review_board"), document.get("detected_blocks") or []),
                "restorable_fields": restorable_fields(document),
            }
        return await asyncio.to_thread(_sync)

    @router.post("/api/document/{document_id}/restore-field")
    async def restore_field(document_id: str, request: Request):
        payload = await safe_request_json(request)
        target_key = payload.get("target_key")
        if target_key not in FIELD_MAP:
            raise HTTPException(status_code=400, detail="Invalid target field.")

        def _sync():
            document = get_document_or_404(document_id)
            history = document.setdefault("field_history", {}).get(target_key) or []
            if not history:
                raise HTTPException(status_code=400, detail="Nothing to restore for this field.")
            previous_value = history.pop()
            document["template_state"][target_key] = previous_value
            refresh_document_state(document, persist_review_reset=True)
            store.save_document(document_id, document)
            return {
                "template_state": document["template_state"],
                "review_board": document["review_board"],
                "workflow_state": document["workflow_state"],
                "preview_html": build_preview_html(document["template_state"], document.get("profile"), precomputed_issues=document.get("_cached_issues")),
                "recommendations": build_recommendations(document.get("review_board"), document.get("detected_blocks") or []),
                "restorable_fields": restorable_fields(document),
            }
        return await asyncio.to_thread(_sync)

    @router.post("/api/document/{document_id}/review-complete")
    async def complete_review(document_id: str, request: Request):
        payload = await safe_request_json(request)

        def _sync():
            document = get_document_or_404(document_id)
            template_state = normalize_template_state(payload.get("template_state", document["template_state"]))
            document["template_state"] = template_state
            refresh_document_state(document, persist_review_reset=True)
            if not document["workflow_state"]["review_ready"]:
                raise HTTPException(status_code=400, detail={"message": "Profile is not ready for review completion.", "issues": document["workflow_state"]["blocking_issues"]})
            try:
                validated = validated_schema_from_document(document, template_state)
            except ValidationError as exc:
                raise HTTPException(status_code=400, detail=schema_error_detail(exc)) from exc
            document["validated_export_json"] = validated.model_dump()
            document["review_confirmed"] = True
            document["workflow_state"]["review_confirmed"] = True
            document["workflow_state"]["can_download"] = True
            store.save_document(document_id, document)
            return {
                "review_board": document["review_board"],
                "workflow_state": document["workflow_state"],
                "validated_export_json": document["validated_export_json"],
                "preview_html": build_preview_html(document["template_state"], document.get("profile"), precomputed_issues=document.get("_cached_issues")),
                "recommendations": build_recommendations(document.get("review_board"), document.get("detected_blocks") or []),
                "restorable_fields": restorable_fields(document),
            }
        return await asyncio.to_thread(_sync)

    @router.post("/api/document/{document_id}/export")
    async def export_document(document_id: str, request: Request):
        store.cleanup_expired_artifacts()
        document = get_document_or_404(document_id)
        payload = await safe_request_json(request)
        template_state = normalize_template_state(payload.get("template_state", document["template_state"]))
        document["template_state"] = template_state
        refresh_document_state(document)
        if not document.get("validated_export_json") or not document.get("review_confirmed"):
            raise HTTPException(status_code=400, detail="Complete preview review successfully before export.")
        if not document.get("workflow_state", {}).get("review_ready"):
            raise HTTPException(status_code=400, detail={"message": "Profile is not ready for export.", "issues": document.get("workflow_state", {}).get("blocking_issues") or []})
        export_base = EXPORT_DIR / f"cv_export_{document_id}"
        json_path = export_base.with_suffix(".json")
        docx_path = export_base.with_suffix(".docx")
        try:
            validated = validated_schema_from_document(document, template_state)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=schema_error_detail(exc)) from exc
        document["validated_export_json"] = validated.model_dump()
        store.save_document(document_id, document)
        build_profile_docx_from_schema(docx_path, document["validated_export_json"])
        json_payload = {
            "filename": document["filename"],
            "document_id": document_id,
            "validated_profile": document["validated_export_json"],
            "template_state": template_state,
        }
        json_path.write_text(json.dumps(json_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return {
            "json_file": f"/api/export/{json_path.name}",
            "docx_file": f"/api/export/{docx_path.name}",
            "json_name": json_path.name,
            "docx_name": docx_path.name,
        }

    @router.post("/api/document/{document_id}/download")
    async def download_cv(document_id: str, request: Request):
        store.cleanup_expired_artifacts()
        document = get_document_or_404(document_id)
        payload = await safe_request_json(request)
        template_state = normalize_template_state(payload.get("template_state", document["template_state"]))
        refresh_document_state(document, template_state)
        try:
            validated = validated_schema_from_document(document, template_state)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=schema_error_detail(exc)) from exc
        document["validated_export_json"] = validated.model_dump()
        store.save_document(document_id, document)
        export_base = EXPORT_DIR / f"cv_download_{document_id}"
        docx_path = export_base.with_suffix(".docx")
        build_profile_docx_from_schema(docx_path, document["validated_export_json"])
        candidate_name = document["validated_export_json"]["identity"].get("full_name", "Candidate").strip() or "Candidate"
        safe_name = re.sub(r"[^\w\s-]", "", candidate_name).strip().replace(" ", "_")
        return FileResponse(
            str(docx_path),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=f"{safe_name}_Professional_Profile.docx",
        )

    @router.get("/api/export/{filename}")
    async def download_export(filename: str):
        safe_filename = Path(filename).name
        path = EXPORT_DIR / safe_filename
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="Export not found.")
        return FileResponse(path)

    return router
