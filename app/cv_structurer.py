from __future__ import annotations

"""Internal CV-to-JSON structuring module.

This module replaces the user-facing prompt-copy-paste ChatGPT workflow.
It accepts cleaned CV text and produces canonical CestaCV JSON by calling
an LLM provider internally.  The output is validated against the existing
structured-ingest shape so it can feed directly into
``build_structured_document_payload``.

Environment
-----------
Set **one** of these environment variables:

* ``ANTHROPIC_API_KEY`` — uses Claude (preferred)
* ``OPENAI_API_KEY``    — uses OpenAI as a fallback provider

If neither key is set, the module raises ``StructuringUnavailableError``
so the caller can fall back to the legacy heuristic parser.
"""

import json
import logging
import os
import re
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Startup validation — fail fast if an API key is set but the SDK is missing
# ---------------------------------------------------------------------------

def _check_provider_sdk_availability() -> None:
    """Validate provider configuration at import time.

    * If an API key is set but the SDK is missing → hard ImportError (fail fast).
    * If no API key is set at all → log a warning so operators notice.
    """
    has_key = False
    if os.environ.get("ANTHROPIC_API_KEY"):
        has_key = True
        try:
            import anthropic  # noqa: F401
        except ImportError:
            raise ImportError(
                "ANTHROPIC_API_KEY is set but the 'anthropic' package is not installed.  "
                "Run: pip install anthropic"
            )
    if os.environ.get("OPENAI_API_KEY"):
        has_key = True
        try:
            import openai  # noqa: F401
        except ImportError:
            raise ImportError(
                "OPENAI_API_KEY is set but the 'openai' package is not installed.  "
                "Run: pip install openai"
            )
    if not has_key:
        logger.warning(
            "CV STRUCTURER: No ANTHROPIC_API_KEY or OPENAI_API_KEY is set.  "
            "All CV uploads will use the legacy heuristic parser (import_mode='raw_fallback').  "
            "Set an API key to enable the JSON-first ingestion pipeline."
        )

_check_provider_sdk_availability()

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class StructuringError(Exception):
    """The LLM returned output that could not be parsed into valid CV JSON."""


class StructuringUnavailableError(Exception):
    """No LLM provider is configured (missing API key)."""


# ---------------------------------------------------------------------------
# Canonical CestaCV JSON schema
# ---------------------------------------------------------------------------

SCHEMA_EXAMPLE: Dict[str, Any] = {
    "cestacv_version": 1,
    "identity": {
        "full_name": "",
        "headline": "",
        "availability": "",
        "region": "",
        "email": "",
        "phone": "",
        "location": "",
        "linkedin": "",
        "portfolio": "",
    },
    "career_summary": "",
    "skills": [{"category": "", "items": []}],
    "qualifications": [{"qualification": "", "institution": "", "year": ""}],
    "certifications": [{"name": "", "provider": "", "year": ""}],
    "training": [],
    "achievements": [],
    "languages": [],
    "interests": [],
    "references": [],
    "projects": [],
    "career_history": [
        {
            "job_title": "",
            "company": "",
            "start_date": "",
            "end_date": "",
            "responsibilities": [],
            "client_engagements": [],
            "projects": [],
        }
    ],
    "additional_sections": [{"title": "", "content": ""}],
}

SCHEMA_JSON = json.dumps(SCHEMA_EXAMPLE, indent=2, ensure_ascii=False)

# ---------------------------------------------------------------------------
# System prompt for internal CV structuring
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = f"""\
You are an internal CV-structuring service for the CestaSoft recruiter platform.

Your ONLY job: convert the raw CV text provided by the user into a single valid
JSON object that matches the schema below.  Return **nothing** except the JSON
object — no markdown, no commentary, no explanations.

## Schema

{SCHEMA_JSON}

## Output rules
- Return ONLY valid raw JSON.
- Do NOT use markdown code fences.
- Use exactly the schema shown above.  Keep the top-level key order.
- Trim leading/trailing whitespace from every string value.
- Do NOT insert literal (unescaped) line breaks inside JSON string values.
- If a value is missing from the CV, use "" or [].
- Preserve source facts exactly.  Do NOT invent, infer, embellish, or summarise
  beyond the source CV.
- Treat placeholder tokens such as (LinkedIn_link), N/A, null, or undefined as
  missing values (use "").

## Mapping rules
- identity.full_name = candidate full name only.
- identity.headline = professional headline or current title explicitly stated.
- identity.region must remain blank unless the CV explicitly provides a region.
- identity.location maps only to physical location/address.
- Map phone, email, LinkedIn, portfolio into identity fields directly.
- career_summary = summary / profile / objective / about section only.
- skills = grouped by category where possible, preserving source order.
- qualifications = formal education only.
- certifications = certificates, licences, accreditations only.
- training = courses, workshops, bootcamps, short courses only.
- achievements = awards, honours, distinctions only.
- languages, interests, references, projects map to their matching sections.
- career_history = real work experience only.
- additional_sections = useful content that does not fit a dedicated field.

## Failure-avoidance rules
- Do NOT leave identity.full_name blank if the CV contains the candidate's name.
- Do NOT leave identity.headline blank when the source clearly provides a title.
- Keep academic employment roles (Student Assistant, Lab Demonstrator, Research
  Assistant, Tutor, Intern) in career_history if they are real work.
- Do NOT place pure education records in career_history.
- Do NOT infer region from location.
- Do NOT generate references such as "Available on request" unless that exact
  text appears in the source.
- Do NOT leak quoted field labels into values.
- Do NOT flatten skills, career history, qualifications into one blob.
- Do NOT duplicate contact details into additional_sections.
- Do NOT leave a career_history job_title blank when the source states the role.
- Do NOT merge company location text into company name.
- Do NOT produce malformed arrays or objects.
- Do NOT let summary fragments become career_history entries.
- Do NOT over-split certification lines into bogus columns.
- Preserve unusual but valid employer names exactly as written.
"""

_REPAIR_SUFFIX = (
    "\n\nThe previous attempt returned invalid JSON.  "
    "Fix the JSON so it parses with json.loads and matches the schema exactly.  "
    "Return ONLY the repaired JSON object."
)


# ---------------------------------------------------------------------------
# Provider abstraction
# ---------------------------------------------------------------------------

def _get_provider() -> str:
    """Return 'anthropic' or 'openai' based on available API keys."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    raise StructuringUnavailableError(
        "No LLM API key configured.  Set ANTHROPIC_API_KEY or OPENAI_API_KEY."
    )


def _call_anthropic(cv_text: str, *, repair_hint: str = "") -> str:
    """Call the Anthropic Messages API and return the raw text response."""
    import anthropic  # deferred import — only needed when this provider is used

    client = anthropic.Anthropic()
    system = _SYSTEM_PROMPT + repair_hint
    message = client.messages.create(
        model=os.environ.get("CV_STRUCTURER_MODEL", "claude-haiku-4-5-20251001"),
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": cv_text}],
    )
    # Extract text from the response
    return "".join(
        block.text for block in message.content if hasattr(block, "text")
    )


def _call_openai(cv_text: str, *, repair_hint: str = "") -> str:
    """Call the OpenAI Chat Completions API and return the raw text response."""
    import openai  # deferred import

    client = openai.OpenAI()
    system = _SYSTEM_PROMPT + repair_hint
    response = client.chat.completions.create(
        model=os.environ.get("CV_STRUCTURER_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": cv_text},
        ],
        max_tokens=4096,
        temperature=0.0,
    )
    return response.choices[0].message.content or ""


def _call_provider(provider: str, cv_text: str, *, repair_hint: str = "") -> str:
    if provider == "anthropic":
        return _call_anthropic(cv_text, repair_hint=repair_hint)
    return _call_openai(cv_text, repair_hint=repair_hint)


# ---------------------------------------------------------------------------
# JSON extraction and validation helpers
# ---------------------------------------------------------------------------

def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences if the LLM wrapped the JSON anyway."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Remove first line (```json or ```) and last line (```)
        if len(lines) >= 3 and lines[-1].strip() == "```":
            body = "\n".join(lines[1:-1]).strip()
            if body.lower().startswith("json"):
                body = body[4:].lstrip()
            return body
    return text


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Try to extract a JSON object from potentially messy LLM output."""
    text = _strip_markdown_fences(text)

    # Direct parse
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # Try to find the first { ... } block
    match = re.search(r"\{", text)
    if match:
        candidate = text[match.start():]
        try:
            decoder = json.JSONDecoder()
            data, _ = decoder.raw_decode(candidate)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    return None


def _validate_cv_shape(data: Dict[str, Any]) -> bool:
    """Quick structural check — must have identity dict and career_summary str."""
    if not isinstance(data.get("identity"), dict):
        return False
    if not isinstance(data.get("career_summary"), str):
        return False
    # Must have at least the core top-level keys
    required = {"identity", "career_summary", "skills", "qualifications",
                "career_history", "certifications"}
    return required.issubset(data.keys())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def structure_cv_text(raw_text: str) -> Tuple[Dict[str, Any], str]:
    """Structure raw CV text into canonical CestaCV JSON.

    Parameters
    ----------
    raw_text : str
        The cleaned, extracted text from the uploaded CV document.

    Returns
    -------
    tuple[dict, str]
        A (structured_json, strategy) tuple where *strategy* is
        ``"internally_structured"`` on success.

    Raises
    ------
    StructuringUnavailableError
        If no LLM API key is configured.
    StructuringError
        If both the initial attempt and the retry produce invalid JSON.
    """
    import asyncio

    provider = _get_provider()  # raises StructuringUnavailableError if no key

    # --- First attempt ---
    logger.info("CV structurer: calling %s provider (first attempt)", provider)
    try:
        raw_response = await asyncio.to_thread(
            _call_provider, provider, raw_text
        )
    except Exception as exc:
        logger.error("CV structurer: provider call failed: %s", exc)
        raise StructuringError(f"LLM provider call failed: {exc}") from exc

    data = _extract_json_object(raw_response)
    if data is not None and _validate_cv_shape(data):
        logger.info("CV structurer: first attempt succeeded")
        return data, "internally_structured"

    # --- Retry with repair hint ---
    logger.warning("CV structurer: first attempt returned invalid output, retrying with repair hint")
    try:
        raw_response_2 = await asyncio.to_thread(
            _call_provider, provider, raw_text, repair_hint=_REPAIR_SUFFIX
        )
    except Exception as exc:
        logger.error("CV structurer: retry provider call failed: %s", exc)
        raise StructuringError(f"LLM provider retry failed: {exc}") from exc

    data_2 = _extract_json_object(raw_response_2)
    if data_2 is not None and _validate_cv_shape(data_2):
        logger.info("CV structurer: retry succeeded")
        return data_2, "internally_structured"

    raise StructuringError(
        "CV structurer: both attempts returned output that could not be "
        "parsed into valid CestaCV JSON."
    )
