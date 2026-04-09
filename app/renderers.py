from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Optional

from .normalizers import validate_profile_readiness
from .parsers import parse_experience_section, sanitize_entity_text


def _clean(value: Optional[str]) -> str:
    value = sanitize_entity_text(value) or ""
    value = re.sub(r"\s+", " ", value).strip(" |,-")
    if value.lower() in {"", "null", "none", "n/a", "na"}:
        return ""
    return value


def _strip_leading_bullets(value: Optional[str]) -> str:
    cleaned = _clean(value)
    return _clean(re.sub(r"^(?:[\u2022\u00b7\-\*\u25cf\?]+\s*)+", "", cleaned))


def _split_lines(text: str) -> List[str]:
    return [_strip_leading_bullets(line.strip()) for line in (text or "").splitlines() if _strip_leading_bullets(line)]


def _split_rows(text: str) -> List[List[str]]:
    rows: List[List[str]] = []
    for line in _split_lines(text):
        parts = [_clean(part) for part in re.split(r"\s*\|\s*", line)]
        parts = [part for part in parts if part]
        if parts:
            rows.append(parts)
    return rows


def _table(title: str, headers: List[str], rows: List[List[str]], *, span_two: bool = True) -> str:
    if not rows:
        return ""
    thead = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    body = "".join(
        "<tr>"
        + "".join(f"<td>{html.escape((row + [''] * len(headers))[idx])}</td>" for idx in range(len(headers)))
        + "</tr>"
        for row in rows
    )
    section_class = "report-section span-2" if span_two else "report-section"
    return (
        f"<section class='{section_class}'>"
        f"<h3>{html.escape(title)}</h3>"
        f"<table class='profile-table'><thead><tr>{thead}</tr></thead><tbody>{body}</tbody></table>"
        "</section>"
    )


def _list_block(title: str, items: List[str], *, span_two: bool = True) -> str:
    if not items:
        return ""
    lis = "".join(f"<li>{html.escape(item)}</li>" for item in items)
    section_class = "report-section span-2" if span_two else "report-section"
    return f"<section class='{section_class}'><h3>{html.escape(title)}</h3><ul>{lis}</ul></section>"


def _certification_rows(lines: List[str]) -> List[List[str]]:
    rows: List[List[str]] = []
    for line in lines:
        parts = [_strip_leading_bullets(part) for part in re.split(r"\s*\|\s*", line) if _strip_leading_bullets(part)]
        if len(parts) >= 2:
            rows.append([parts[0], parts[1], parts[2] if len(parts) > 2 else ""])
    return rows


def _split_skill_item(item: str) -> tuple[str, str]:
    if ":" not in item:
        return "", item
    label, value = item.split(":", 1)
    return _clean(label), _clean(value)


def _skills_block(items: List[str]) -> str:
    if not items:
        return ""

    entries = []
    for item in items:
        label, value = _split_skill_item(item)
        if label and value:
            copy = (
                "<div class='skill-copy'>"
                f"<span class='skill-label'>{html.escape(label)}</span>"
                f"<span class='skill-value'>{html.escape(value)}</span>"
                "</div>"
            )
        else:
            copy = f"<div class='skill-copy'><span class='skill-text'>{html.escape(value or label)}</span></div>"
        entries.append(f"<div class='skill-entry'><span class='skill-dot'></span>{copy}</div>")

    return (
        "<section class='report-section report-section-skills span-2'>"
        "<h3>Skills</h3>"
        f"<div class='skills-grid'>{''.join(entries)}</div>"
        "</section>"
    )


def _experience_label(entry: Dict[str, Any]) -> str:
    company = _clean(entry.get("company")).lower()
    bullets = [_clean(line) for line in entry.get("responsibilities", []) if _clean(line)]
    client_style_count = sum(1 for bullet in bullets if re.match(r"^[A-Z][A-Za-z0-9&/().,' -]{1,60}:\s+\S", bullet))
    if "consulting partner" in company and client_style_count >= 2:
        return "Client Engagements"
    return "Responsibilities"


def build_preview_html(state: Dict[str, str], profile: Optional[Dict[str, Any]] = None, *, precomputed_issues: Optional[List[str]] = None) -> str:
    issues = precomputed_issues if precomputed_issues is not None else validate_profile_readiness(state)
    qual_rows = [
        [
            row[0],
            row[1] if len(row) > 1 else "",
            " – ".join(
                [value for value in [row[2] if len(row) > 2 else "", row[3] if len(row) > 3 else ""] if value]
            )
            if len(row) > 3
            else (row[2] if len(row) > 2 else ""),
        ]
        for row in _split_rows(state.get("education", ""))
    ]
    certs = _split_lines(state.get("certifications", ""))
    cert_rows = _certification_rows(certs)
    cert_list = certs if not cert_rows or len(cert_rows) != len(certs) else []
    skills = _split_lines(state.get("skills", ""))

    profile_history = list((profile or {}).get("experience", []) or [])
    parsed_history = parse_experience_section(state.get("career_history", "") or "")
    if profile_history and len(parsed_history) < len(profile_history):
        parsed_history = profile_history
    elif not parsed_history:
        parsed_history = profile_history

    career_summary_rows = []
    history_blocks = []
    for entry in parsed_history:
        company = _clean(entry.get("company"))
        position = _clean(entry.get("position"))
        start_date = _clean(entry.get("start_date"))
        end_date = _clean(entry.get("end_date"))
        if company and position:
            career_summary_rows.append([company, position, start_date, end_date])

        title = " — ".join(part for part in [position, company] if part) or company or position
        bullets = [_clean(line) for line in entry.get("responsibilities", []) if _clean(line)]
        summary_line = _clean(entry.get("summary"))
        if summary_line and summary_line not in bullets:
            bullets = [summary_line] + bullets

        bullet_html = "".join(f"<li>{html.escape(line)}</li>" for line in bullets[:8])
        if title:
            meta = " – ".join(part for part in [start_date, end_date] if part)
            meta_html = f"<div class='experience-meta'>{html.escape(meta)}</div>" if meta else ""
            responsibilities_block = ""
            if bullet_html:
                responsibilities_block = (
                    "<div class='experience-label'>"
                    f"{html.escape(_experience_label(entry))}"
                    "</div>"
                    f"<ul class='experience-list'>{bullet_html}</ul>"
                )
            history_blocks.append(
                "<article class='experience-card'>"
                f"<div class='experience-top'><h4>{html.escape(title)}</h4>{meta_html}</div>"
                f"{responsibilities_block}"
                "</article>"
            )

    if not parsed_history:
        for block in re.split(r"\n\s*\n+", state.get("career_history", "").strip()):
            lines = [line.strip(" •-") for line in block.splitlines() if _clean(line)]
            if not lines:
                continue
            title = html.escape(lines[0])
            bullets = "".join(f"<li>{html.escape(line)}</li>" for line in lines[1:7])
            history_list = f"<ul class='experience-list'>{bullets}</ul>" if bullets else ""
            history_blocks.append(
                "<article class='experience-card'>"
                f"<div class='experience-top'><h4>{title}</h4></div>"
                f"{history_list}"
                "</article>"
            )

    summary = _clean(state.get("summary"))
    name = html.escape(_clean(state.get("full_name")) or "Candidate Name")
    headline = html.escape(_clean(state.get("headline")) or "Professional Profile")

    meta_items = []
    for label, value in [
        ("Availability", _clean(state.get("availability"))),
        ("Region", _clean(state.get("region"))),
        ("Location", _clean(state.get("location"))),
    ]:
        if value:
            meta_items.append(
                f"<div class='meta-card'><div class='meta-label'>{html.escape(label)}</div><div class='meta-value'>{html.escape(value)}</div></div>"
            )

    banner = ""
    if issues:
        banner = (
            "<section class='report-alert report-alert-warning'><strong>Review recommended</strong><ul>"
            + "".join(f"<li>{html.escape(issue)}</li>" for issue in issues[:4])
            + "</ul></section>"
        )

    sections = [
        f"<section class='report-section span-2'><h3>Candidate Summary</h3><p>{html.escape(summary)}</p></section>" if summary else "",
        _skills_block(skills),
        _table("Qualification", ["Qualification", "Institution", "End Date"], qual_rows),
        (_table("Certifications", ["Name", "Issuer", "Date"], cert_rows) if cert_rows else _list_block("Certifications", cert_list)),
        _table("Career Summary", ["Company", "Position", "Start Date", "End Date"], career_summary_rows),
        f"<section class='report-section span-2'><h3>Career History</h3><div class='experience-stack'>{''.join(history_blocks)}</div></section>" if history_blocks else "",
    ]

    meta_section = f"<section class='report-meta-grid'>{''.join(meta_items)}</section>" if meta_items else ""
    header = (
        "<header class='report-header'>"
        "<div class='report-kicker'>Recruiter-ready professional profile</div>"
        f"<h1>{name}</h1>"
        f"<p class='report-headline'>{headline}</p>"
        f"{meta_section}"
        "</header>"
    )

    return (
        "<div class='report-preview report-sheet'>"
        f"{header}"
        f"{banner}"
        "<div class='report-grid'>"
        + "".join(section for section in sections if section)
        + "</div></div>"
    )
