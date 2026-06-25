from __future__ import annotations

"""HTTP routes for the lean OpenRouter-first profile builder."""

import asyncio
import json
import re
import uuid
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from .constants import EXPORT_DIR, FIELD_DEFINITIONS, FIELD_MAP, MAX_UPLOAD_SIZE_BYTES, TEMPLATE_COPY, UPLOAD_DIR
from .docx_exporter import build_final_profile_payload, build_profile_docx_from_schema
from .normalizers import build_review_board, build_workflow_state, validate_profile_readiness
from .openrouter_structurer import (
    OpenRouterNotConfiguredError,
    OpenRouterStructuringError,
    is_openrouter_configured,
    openrouter_mode,
    should_use_openrouter,
    structure_cv_text_with_openrouter,
)
from .renderers import build_preview_html
from .schema import validate_export_payload
from .source_views import build_pasted_text_source_view, build_source_view
from .storage import SQLiteDocumentStore
from .structured_ingest import build_structured_document_payload, detect_structured_cv_json
from .utils_text import clean_extracted_text, extract_text


LLM_IMPORT_MODE = "openrouter_structured"
STRUCTURED_JSON_IMPORT_MODE = "structured_json"


def register_routes(templates: Jinja2Templates, store: SQLiteDocumentStore) -> APIRouter:
    router = APIRouter()

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

    def legacy_gone() -> None:
        raise HTTPException(
            status_code=410,
            detail="This workflow was removed. Use upload/paste, edit the generated profile, complete review, and download.",
        )

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

    def refresh_document_state(
        document: Dict[str, Any],
        template_state: Dict[str, str] | None = None,
        *,
        persist_review_reset: bool = False,
    ) -> Dict[str, Any]:
        if template_state is not None:
            document["template_state"] = normalize_template_state(template_state)
        else:
            document["template_state"] = normalize_template_state(document.get("template_state", {}))
        document["structured_source"] = True
        document["sections"] = []
        document["text_blocks"] = []
        document["source_sections"] = []
        document["detected_blocks"] = []
        if persist_review_reset:
            document["review_confirmed"] = False
            document.pop("validated_export_json", None)
        issues = validate_profile_readiness(document["template_state"])
        document["_cached_issues"] = issues
        document["review_board"] = build_review_board(
            document["template_state"],
            document.get("profile"),
            precomputed_issues=issues,
        )
        document["workflow_state"] = build_workflow_state(
            document["template_state"],
            document["review_board"],
            document.get("review_confirmed", False),
            precomputed_issues=issues,
        )
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
        return {"message": "Profile failed schema validation.", "issues": issues or ["Schema validation failed."]}

    def build_document_response(document: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "document_id": document["document_id"],
            "filename": document.get("filename"),
            "raw_text": document.get("raw_text", ""),
            "sections": document.get("sections", []),
            "text_blocks": document.get("text_blocks", []),
            "source_sections": document.get("source_sections", []),
            "source_view": document.get("source_view"),
            "detected_blocks": document.get("detected_blocks", []),
            "profile": document.get("profile"),
            "template_state": document.get("template_state", {}),
            "review_board": document.get("review_board", {}),
            "workflow_state": document.get("workflow_state", {}),
            "preview_html": build_preview_html(
                document["template_state"],
                document.get("profile"),
                precomputed_issues=document.get("_cached_issues"),
            ),
            "structured_source": True,
            "import_mode": document.get("import_mode") or LLM_IMPORT_MODE,
            "structured_parse_strategy": document.get("structured_parse_strategy"),
            "llm": document.get("llm"),
        }

    def build_structured_payload(
        structured: Dict[str, Any],
        *,
        document_id: str,
        filename: str,
        parse_strategy: str,
        source_view: Dict[str, Any],
        path: str | None = None,
        raw_text: str | None = None,
        llm_metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        normalized, normalized_strategy = detect_structured_cv_json(json.dumps(structured, ensure_ascii=False))
        if normalized is None:
            raise HTTPException(status_code=502, detail="OpenRouter returned JSON that does not match the CestaCV schema.")
        document_payload = build_structured_document_payload(
            normalized,
            document_id=document_id,
            filename=filename,
            parse_strategy=parse_strategy or normalized_strategy or "structured_json",
        )
        document_payload["path"] = path
        document_payload["source_view"] = source_view
        if raw_text is not None:
            document_payload["raw_text"] = raw_text
        if llm_metadata is not None:
            document_payload["import_mode"] = LLM_IMPORT_MODE
            document_payload["llm"] = llm_metadata
            profile = document_payload.get("profile") or {}
            if isinstance(profile, dict):
                profile.setdefault("document_meta", {})["import_mode"] = LLM_IMPORT_MODE
                profile["document_meta"]["llm"] = llm_metadata
                document_payload["profile"] = profile
        else:
            document_payload["import_mode"] = STRUCTURED_JSON_IMPORT_MODE
            profile = document_payload.get("profile") or {}
            if isinstance(profile, dict):
                profile.setdefault("document_meta", {})["structured_parse_strategy"] = parse_strategy or normalized_strategy or "structured_json"
                document_payload["profile"] = profile
        return document_payload

    async def build_openrouter_payload(
        raw_text: str,
        *,
        document_id: str,
        filename: str,
        source_view: Dict[str, Any],
        path: str | None = None,
    ) -> Dict[str, Any]:
        try:
            structured, metadata = await structure_cv_text_with_openrouter(raw_text)
        except OpenRouterNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except OpenRouterStructuringError as exc:
            raise HTTPException(status_code=502, detail=f"OpenRouter could not structure this CV: {exc}") from exc
        return build_structured_payload(
            structured,
            document_id=document_id,
            filename=filename,
            parse_strategy=f"openrouter:{metadata.get('model') or 'unknown-model'}",
            source_view=source_view,
            path=path,
            raw_text=raw_text,
            llm_metadata=metadata,
        )

    @router.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        return templates.TemplateResponse(
            request,
            "index.html",
            {"field_definitions": FIELD_DEFINITIONS, "template_file_name": TEMPLATE_COPY.name if TEMPLATE_COPY.exists() else ""},
        )

    @router.get("/api/health")
    async def health():
        return {
            "status": "ok",
            "llm_mode": openrouter_mode(),
            "openrouter_configured": is_openrouter_configured(),
            "openrouter_active": should_use_openrouter(),
        }

    @router.get("/api/structuring-prompt")
    async def structuring_prompt_removed():
        legacy_gone()

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
        source_view = build_source_view(file_path, document_id)

        if ext in {".txt", ".md"}:
            raw_text = payload.decode("utf-8", errors="ignore").strip()
        else:
            raw_text = extract_text(file_path)
        raw_text = clean_extracted_text(raw_text)
        if not raw_text:
            file_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="No text could be extracted from the file.")

        structured, structured_strategy = detect_structured_cv_json(raw_text)
        if structured is not None:
            document_payload = build_structured_payload(
                structured,
                document_id=document_id,
                filename=file.filename or "Structured CV JSON",
                parse_strategy=structured_strategy or "direct_json",
                source_view=source_view,
                path=str(file_path),
            )
        else:
            document_payload = await build_openrouter_payload(
                raw_text,
                document_id=document_id,
                filename=file.filename or file_path.name,
                source_view=source_view,
                path=str(file_path),
            )
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
        raw_text = clean_extracted_text(str(input_text).strip())
        if not raw_text:
            raise HTTPException(status_code=400, detail="No CV text provided. Paste your CV content and try again.")
        if len(raw_text) > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(status_code=413, detail=f"Pasted text exceeds the {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB limit.")

        document_id = str(uuid.uuid4())
        source_view = build_pasted_text_source_view(raw_text)
        structured, structured_strategy = detect_structured_cv_json(raw_text)
        if structured is not None:
            document_payload = build_structured_payload(
                structured,
                document_id=document_id,
                filename="Structured CV JSON",
                parse_strategy=structured_strategy or "direct_json",
                source_view=source_view,
            )
        else:
            document_payload = await build_openrouter_payload(
                raw_text,
                document_id=document_id,
                filename="Pasted CV Text",
                source_view=source_view,
            )
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

    @router.post("/api/document/{document_id}/template")
    async def update_template(document_id: str, request: Request):
        data = await safe_request_json(request)

        def _sync():
            document = get_document_or_404(document_id)
            for key, value in data.items():
                if key in FIELD_MAP:
                    document["template_state"][key] = value
            document["template_state"] = normalize_template_state(document["template_state"])
            refresh_document_state(document, persist_review_reset=True)
            store.save_document(document_id, document)
            return build_document_response(document)

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
                raise HTTPException(
                    status_code=400,
                    detail={
                        "message": "Profile is not ready for review completion.",
                        "issues": document["workflow_state"]["blocking_issues"],
                    },
                )
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
                **build_document_response(document),
                "validated_export_json": document["validated_export_json"],
            }

        return await asyncio.to_thread(_sync)

    @router.post("/api/document/{document_id}/download")
    async def download_cv(document_id: str, request: Request):
        store.cleanup_expired_artifacts()
        document = get_document_or_404(document_id)
        payload = await safe_request_json(request)
        template_state = normalize_template_state(payload.get("template_state", document["template_state"]))
        refresh_document_state(document, template_state)
        if not document.get("review_confirmed"):
            raise HTTPException(status_code=400, detail="Complete preview review successfully before download.")
        if not document.get("workflow_state", {}).get("review_ready"):
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Profile is not ready for download.",
                    "issues": document.get("workflow_state", {}).get("blocking_issues") or [],
                },
            )
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

    @router.post("/api/document/{document_id}/annotate")
    async def annotate_text_removed(document_id: str):
        legacy_gone()

    @router.post("/api/document/{document_id}/restore-field")
    async def restore_field_removed(document_id: str):
        legacy_gone()

    @router.post("/api/document/{document_id}/export")
    async def export_document_removed(document_id: str):
        legacy_gone()

    @router.get("/api/export/{filename}")
    async def download_export_removed(filename: str):
        legacy_gone()

    return router
