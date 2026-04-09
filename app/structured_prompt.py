from __future__ import annotations

"""Reusable structuring prompt framework for paste-ready CestaCV JSON output."""

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List


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
    "skills": [
        {
            "category": "",
            "items": [],
        }
    ],
    "qualifications": [
        {
            "qualification": "",
            "institution": "",
            "year": "",
        }
    ],
    "certifications": [
        {
            "name": "",
            "provider": "",
            "year": "",
        }
    ],
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
        }
    ],
    "additional_sections": [
        {
            "title": "",
            "content": "",
        }
    ],
}

SCHEMA_JSON = json.dumps(SCHEMA_EXAMPLE, indent=2, ensure_ascii=False)

PRE_PASTE_GUIDANCE = (
    "Paste only valid raw JSON. Do not wrap the output in markdown."
)

BASE_OUTPUT_RULES = [
    "Return ONLY valid raw JSON.",
    "Do NOT use markdown code fences.",
    "Do NOT add commentary, notes, labels, or explanations.",
    "Use exactly the schema shown below.",
    "Keep the top-level key order exactly as shown in the schema.",
    "Trim leading and trailing whitespace from every string value.",
    "Do NOT insert literal line breaks inside JSON string values.",
    'If a value is missing, use "" or [].',
    "Preserve source facts exactly. Do NOT invent, infer, embellish, or summarize beyond the source CV.",
    "Keep ordering as it appears in the source CV.",
    "Treat placeholder tokens such as (LinkedIn_link), (Portfolio link), N/A, null, or undefined as missing values unless the source clearly intends them as literal content.",
]

BASE_MAPPING_RULES = [
    "identity.full_name = candidate full name only.",
    "identity.headline = the professional headline or current title explicitly supported by the CV.",
    "If the source CV clearly contains a recruiter-facing professional title, populate identity.headline rather than leaving it blank.",
    "identity.region must remain blank unless the CV explicitly provides a region.",
    "identity.location must map only to location.",
    "Map phone, email, LinkedIn, portfolio, and address details into identity fields directly instead of duplicating them elsewhere.",
    "identity.portfolio must remain portfolio and must not be moved into projects.",
    "career_summary = summary/profile/objective/about section only.",
    "skills = grouped skills by category where possible, preserving source order.",
    "qualifications = formal education only.",
    "certifications = certificates, licences, and accreditations only.",
    "training = courses, workshops, bootcamps, and short courses only.",
    "achievements = awards, honours, distinctions, or notable achievements only.",
    "languages, interests, references, and projects must map only to their matching sections.",
    "career_history = real work experience only.",
    "additional_sections = useful content that does not fit a dedicated field.",
]

BASE_FAILURE_AVOIDANCE_RULES = [
    "Do NOT leave identity.full_name blank if the source CV contains the candidate's name.",
    "Do NOT leave identity.headline blank when the source clearly provides a professional title.",
    "Keep academic employment roles in career_history if they are real work with responsibilities, such as Student Assistant, Lab Demonstrator, Research Assistant, Tutor, or Intern.",
    "Do NOT place pure education records in career_history.",
    "Do NOT infer region from location.",
    'Do NOT generate references such as "Available on request" unless that exact text appears in the source.',
    'If the source says references are available on request, place that text in references rather than in additional_sections.',
    "Do NOT leak quoted field labels like headline, category, or responsibilities into the values.",
    "Do NOT flatten skills, career history, and qualifications into one blob.",
    "Do NOT duplicate contact details or addresses inside additional_sections when canonical identity fields already exist for them.",
    "Do NOT leave a career_history job_title blank when the source clearly states the role title.",
    "Do NOT merge company location text into company when the employer name can be separated cleanly.",
    "Do NOT produce malformed arrays or objects.",
]

FINAL_VALIDATION_RULES = [
    "Before finalizing, ensure the output parses successfully with JSON.parse.",
    "Ensure the output contains no literal line breaks inside string values.",
    "Ensure every opened object and array is properly closed.",
]

SELF_CHECK_RULES = [
    "Verify the first character of the final answer is {.",
    "Verify the last character of the final answer is }.",
    "Verify there are no markdown code fences anywhere in the final answer.",
    "Verify no field value contains a literal unescaped line break.",
    "Verify every string remains on one line unless a newline is escaped.",
    "Verify all commas, brackets, and braces are valid for strict JSON.",
    "Verify identity.full_name is populated when the source CV contains the candidate's name.",
    "Verify identity.headline is populated when the source CV clearly contains a professional title.",
    "Verify contact details are not duplicated into additional_sections when canonical identity fields are available.",
    "If the draft is invalid JSON, repair it before returning the answer.",
    "If the draft violates any schema or formatting rule above, silently repair it before returning the answer.",
    "After this self-check, return ONLY the final JSON object.",
]


@dataclass(frozen=True)
class PromptPreset:
    key: str
    label: str
    description: str
    task: str
    extra_rules: tuple[str, ...] = ()
    recommended: bool = False


PROMPT_PRESETS: tuple[PromptPreset, ...] = (
    PromptPreset(
        key="raw_cv_to_json",
        label="Recommended JSON Structuring Prompt",
        description="Best default for turning a CV into paste-ready CestaCV JSON.",
        task="Convert the CV into a single valid CestaCV JSON object for system import.",
        extra_rules=(
            "Map the CV into the correct schema fields even when section headings vary.",
            "Use nearby context only to complete split records, not to invent missing data.",
            "Perform the extraction in two silent passes: first map the facts into the schema, then repair the draft into strict parseable JSON before returning it.",
        ),
        recommended=True,
    ),

)


def _render_lines(lines: Iterable[str]) -> str:
    return "\n".join(f"- {line}" for line in lines)


def build_structuring_prompt(preset: PromptPreset) -> str:
    sections: List[str] = [
        "You are preparing a paste-ready CestaCV JSON object for the CestaSoft CV parsing and recruiter review system.",
        "",
        "Task",
        preset.task,
        "",
        "Output Rules",
        _render_lines(BASE_OUTPUT_RULES),
    ]
    if preset.extra_rules:
        sections.extend(
            [
                "",
                "Mode-Specific Rules",
                _render_lines(preset.extra_rules),
            ]
        )
    sections.extend(
        [
            "",
            "Mapping Rules",
            _render_lines(BASE_MAPPING_RULES),
            "",
            "Failure-Avoidance Rules",
            _render_lines(BASE_FAILURE_AVOIDANCE_RULES),
            "",
            "Use exactly this schema:",
            SCHEMA_JSON,
            "",
            "Final Validation Rule",
            _render_lines(FINAL_VALIDATION_RULES),
            "",
            "Self-Check Before Returning",
            _render_lines(SELF_CHECK_RULES),
        ]
    )
    return "\n".join(sections)


def _build_prompt_catalog() -> List[Dict[str, Any]]:
    catalog: List[Dict[str, Any]] = []
    for preset in PROMPT_PRESETS:
        catalog.append(
            {
                "key": preset.key,
                "label": preset.label,
                "description": preset.description,
                "recommended": preset.recommended,
                "prompt": build_structuring_prompt(preset),
            }
        )
    return catalog


def get_structuring_prompt_payload() -> Dict[str, Any]:
    prompts = _build_prompt_catalog()
    recommended_prompt = next((prompt for prompt in prompts if prompt["recommended"]), prompts[0])
    return {
        "prompt": recommended_prompt["prompt"],
        "prompt_key": recommended_prompt["key"],
        "prompt_label": recommended_prompt["label"],
        "recommended_prompt_key": recommended_prompt["key"],
        "recommended_prompt_label": recommended_prompt["label"],
        "prompts": prompts,
        "pre_paste_guidance": PRE_PASTE_GUIDANCE,
        "schema_example": SCHEMA_EXAMPLE,
        "schema_json": SCHEMA_JSON,
    }
