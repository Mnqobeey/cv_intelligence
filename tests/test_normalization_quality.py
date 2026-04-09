from pathlib import Path

from app.normalizers import build_review_board, profile_from_sections, profile_to_template_state, validate_profile_readiness
from app.parsers import parse_sections


def test_missing_or_weak_headline_is_inferred_from_professional_role(tmp_path: Path):
    raw = """
    THANDOKUHLE MNQOBI MNTAMBO
    Objective
    I am looking for growth in the IT industry.

    Career History
    OpenText | QA Analyst | Jan 2025 | Present
    Executed regression and API test packs.
    """
    sections = parse_sections(raw)
    profile = profile_from_sections(raw, sections, tmp_path / "candidate.docx")
    state = profile_to_template_state(profile)
    assert state["headline"] == "QA Analyst"


def test_full_address_is_reduced_to_recruiter_friendly_region(tmp_path: Path):
    raw = """
    THANDOKUHLE MNQOBI MNTAMBO
    Address: 123 Main Street, Midrand, Gauteng, South Africa
    Career History
    OpenText | QA Analyst | Jan 2025 | Present
    Executed regression and API test packs.
    Qualifications
    BCom Information Systems | University of Johannesburg | 2021
    """
    sections = parse_sections(raw)
    profile = profile_from_sections(raw, sections, tmp_path / "candidate.docx")
    state = profile_to_template_state(profile)
    assert state["region"] == "Midrand, Gauteng"
    assert "123 Main Street" not in state["region"]


def test_summary_and_skills_preserve_source_wording_while_cleaning_format(tmp_path: Path):
    raw = """
    THANDOKUHLE MNQOBI MNTAMBO
    Professional Summary
    I am a hardworking team player with hands-on experience in api testing, java, jira, java and microsoft office.
    Skills
    api testing
    jira
    java
    Microsoft Office
    java
    Career History
    OpenText | QA Intern | Jan 2025 | Present
    Supported regression and API testing in Agile delivery teams.
    Qualifications
    BCom Information Systems | University of Johannesburg | 2021
    """
    sections = parse_sections(raw)
    profile = profile_from_sections(raw, sections, tmp_path / "candidate.docx")
    state = profile_to_template_state(profile)
    assert state["summary"].startswith("I am a hardworking team player")
    assert "hands-on experience in api testing" in state["summary"].lower()
    assert "Testing: API Testing" in state["skills"]
    assert "Programming Languages: Java" in state["skills"]
    assert state["skills"].count("Java") == 1
    assert "Tools: Jira, Microsoft Office" in state["skills"]


def test_qualification_pairing_and_academic_cleanup_keep_review_honest(tmp_path: Path):
    raw = """
    THANDOKUHLE MNQOBI MNTAMBO
    Qualifications
    Qualification | Institution | Year
    BCom Information Systems | University of Johannesburg | 2021

    Career History
    Honours Project | University of Johannesburg | 2021
    Built a student feedback platform.
    OpenText | QA Intern | Jan 2025 | Present
    Validated web and API workflows.
    """
    sections = parse_sections(raw)
    profile = profile_from_sections(raw, sections, tmp_path / "candidate.docx")
    state = profile_to_template_state(profile)
    issues = validate_profile_readiness(state)
    review = build_review_board(state, profile)

    assert state["education"] == "BCom Information Systems | University of Johannesburg | 2021"
    assert "Honours Project" not in state["education"]
    assert "Honours Project" not in state["career_history"]
    assert not any("Qualifications contain malformed" in issue for issue in issues)
    career_section = next(section for section in review["sections"] if section["key"] == "career_history")
    assert career_section["status"] == "Ready"
