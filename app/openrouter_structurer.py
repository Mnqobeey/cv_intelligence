from __future__ import annotations

"""OpenRouter-backed CV structuring.

This is the LLM-first ingestion path for raw CV text. It returns the same
canonical CestaCV JSON shape as the structured import flow, so the rest of the
app can keep using the existing preview and DOCX export pipeline.
"""

import json
import os
import re
from typing import Any, Dict, Tuple

import httpx


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "deepseek/deepseek-v4-flash:free"


class OpenRouterNotConfiguredError(RuntimeError):
    """OpenRouter cannot be used because the API key is missing."""


class OpenRouterStructuringError(RuntimeError):
    """OpenRouter failed or returned unusable structured output."""


def openrouter_mode() -> str:
    return os.getenv("CV_INTELLIGENCE_LLM_MODE", "auto").strip().lower() or "auto"


def is_openrouter_configured() -> bool:
    return bool(os.getenv("OPENROUTER_API_KEY"))


def should_use_openrouter() -> bool:
    mode = openrouter_mode()
    return mode == "required" or (mode != "disabled" and is_openrouter_configured())


def _string_schema(description: str = "") -> Dict[str, Any]:
    schema: Dict[str, Any] = {"type": "string"}
    if description:
        schema["description"] = description
    return schema


def _string_array_schema(description: str = "") -> Dict[str, Any]:
    schema: Dict[str, Any] = {"type": "array", "items": {"type": "string"}}
    if description:
        schema["description"] = description
    return schema


CV_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "cestacv_version",
        "identity",
        "career_summary",
        "skills",
        "qualifications",
        "certifications",
        "training",
        "achievements",
        "languages",
        "interests",
        "references",
        "projects",
        "career_history",
        "additional_sections",
    ],
    "properties": {
        "cestacv_version": {"type": "integer", "enum": [1]},
        "identity": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "full_name",
                "headline",
                "availability",
                "region",
                "email",
                "phone",
                "location",
                "linkedin",
                "portfolio",
            ],
            "properties": {
                "full_name": _string_schema("Candidate full name exactly as stated."),
                "headline": _string_schema("Professional headline or current role."),
                "availability": _string_schema("Availability or notice period if stated."),
                "region": _string_schema("Region only if explicitly stated."),
                "email": _string_schema("Email address."),
                "phone": _string_schema("Phone number."),
                "location": _string_schema("Physical location or address."),
                "linkedin": _string_schema("LinkedIn URL or handle."),
                "portfolio": _string_schema("Portfolio, GitHub, website, or relevant profile URL."),
            },
        },
        "career_summary": _string_schema(
            "Recruiter-ready summary, faithful to the source and not invented."
        ),
        "skills": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["category", "items"],
                "properties": {
                    "category": _string_schema("Skill category, or Core Skills if ungrouped."),
                    "items": _string_array_schema("Skills in source order."),
                },
            },
        },
        "qualifications": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["qualification", "institution", "year"],
                "properties": {
                    "qualification": _string_schema(),
                    "institution": _string_schema(),
                    "year": _string_schema(),
                },
            },
        },
        "certifications": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "provider", "year"],
                "properties": {
                    "name": _string_schema(),
                    "provider": _string_schema(),
                    "year": _string_schema(),
                },
            },
        },
        "training": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "provider", "year", "details"],
                "properties": {
                    "name": _string_schema(),
                    "provider": _string_schema(),
                    "year": _string_schema(),
                    "details": _string_schema(),
                },
            },
        },
        "achievements": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "year", "details"],
                "properties": {
                    "title": _string_schema(),
                    "year": _string_schema(),
                    "details": _string_schema(),
                },
            },
        },
        "languages": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "proficiency"],
                "properties": {
                    "name": _string_schema(),
                    "proficiency": _string_schema(),
                },
            },
        },
        "interests": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "details"],
                "properties": {
                    "name": _string_schema(),
                    "details": _string_schema(),
                },
            },
        },
        "references": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "role", "company", "email", "phone", "relationship"],
                "properties": {
                    "name": _string_schema(),
                    "role": _string_schema(),
                    "company": _string_schema(),
                    "email": _string_schema(),
                    "phone": _string_schema(),
                    "relationship": _string_schema(),
                },
            },
        },
        "projects": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "details"],
                "properties": {
                    "name": _string_schema(),
                    "details": _string_schema(),
                },
            },
        },
        "career_history": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "job_title",
                    "company",
                    "start_date",
                    "end_date",
                    "responsibilities",
                    "client_engagements",
                    "projects",
                ],
                "properties": {
                    "job_title": _string_schema(),
                    "company": _string_schema(),
                    "start_date": _string_schema(),
                    "end_date": _string_schema(),
                    "responsibilities": _string_array_schema(),
                    "client_engagements": _string_array_schema(),
                    "projects": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["name", "details"],
                            "properties": {
                                "name": _string_schema(),
                                "details": _string_schema(),
                            },
                        },
                    },
                },
            },
        },
        "additional_sections": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "content"],
                "properties": {
                    "title": _string_schema(),
                    "content": _string_schema(),
                },
            },
        },
    },
}


SYSTEM_PROMPT = """\
You are the CV intelligence engine for CestaSoft Profile Builder.

Convert the supplied CV text into the required JSON schema. The output must be
source-faithful and recruiter-ready:
- Preserve factual details exactly. Do not invent employers, dates, degrees, or tools.
- Improve wording only for the career summary and responsibility bullets.
- Keep academic employment roles in career_history when they are real work.
- Keep pure education records out of career_history.
- Separate qualifications, certifications, training, projects, references, and skills.
- Use empty strings or empty arrays when the source does not provide a value.
- Do not duplicate contact details into additional_sections.
- Treat the latest/current role as the headline when the CV has no headline.
- Return JSON only.
"""


def _headers() -> Dict[str, str]:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise OpenRouterNotConfiguredError("Set OPENROUTER_API_KEY to enable LLM CV processing.")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    referer = os.getenv("OPENROUTER_SITE_URL")
    title = os.getenv("OPENROUTER_APP_NAME", "CestaCV Intelligence Studio")
    if referer:
        headers["HTTP-Referer"] = referer
    if title:
        headers["X-OpenRouter-Title"] = title
    return headers


def _request_payload(raw_text: str) -> Dict[str, Any]:
    return {
        "model": os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": raw_text},
        ],
        "temperature": 0,
        "max_tokens": int(os.getenv("OPENROUTER_MAX_TOKENS", "6000")),
        "provider": {
            "require_parameters": True,
        },
        "plugins": [
            {"id": "response-healing"},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "cestacv_profile",
                "strict": True,
                "schema": CV_JSON_SCHEMA,
            },
        },
    }


def _strip_markdown_fences(text: str) -> str:
    value = (text or "").strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            body = "\n".join(lines[1:-1]).strip()
            if body.lower().startswith("json"):
                body = body[4:].lstrip()
            return body
    return value


def _extract_json_object(content: Any) -> Dict[str, Any]:
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        text_parts = []
        for part in content:
            if isinstance(part, dict):
                text_parts.append(str(part.get("text") or part.get("content") or ""))
            else:
                text_parts.append(str(part))
        content = "\n".join(text_parts)
    text = _strip_markdown_fences(str(content or ""))
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{", text)
        if not match:
            raise OpenRouterStructuringError("OpenRouter returned no JSON object.")
        try:
            data, _ = json.JSONDecoder().raw_decode(text[match.start():])
        except json.JSONDecodeError as exc:
            raise OpenRouterStructuringError(f"OpenRouter returned invalid JSON: {exc.msg}.") from exc
    if not isinstance(data, dict):
        raise OpenRouterStructuringError("OpenRouter returned JSON, but not an object.")
    return data


def _validate_minimum_shape(data: Dict[str, Any]) -> None:
    identity = data.get("identity")
    if not isinstance(identity, dict):
        raise OpenRouterStructuringError("OpenRouter JSON is missing identity.")
    if not isinstance(data.get("career_summary"), str):
        raise OpenRouterStructuringError("OpenRouter JSON is missing career_summary.")
    if not isinstance(data.get("career_history"), list):
        raise OpenRouterStructuringError("OpenRouter JSON is missing career_history.")


async def structure_cv_text_with_openrouter(raw_text: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return canonical CestaCV JSON plus OpenRouter metadata."""

    if not raw_text.strip():
        raise OpenRouterStructuringError("No CV text supplied to OpenRouter.")

    timeout = float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "90"))
    payload = _request_payload(raw_text)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(OPENROUTER_URL, headers=_headers(), json=payload)

    if response.status_code >= 400:
        detail = response.text[:1000]
        raise OpenRouterStructuringError(
            f"OpenRouter request failed with HTTP {response.status_code}: {detail}"
        )

    body = response.json()
    choices = body.get("choices") or []
    if not choices:
        raise OpenRouterStructuringError("OpenRouter returned no choices.")
    message = choices[0].get("message") or {}
    data = _extract_json_object(message.get("content"))
    _validate_minimum_shape(data)

    metadata = {
        "provider": "openrouter",
        "model": body.get("model") or payload.get("model"),
        "usage": body.get("usage") or {},
        "generation_id": body.get("id"),
    }
    return data, metadata
