"""Targeted regression tests for Lethu_wanda_CV.pdf parsing."""

from pathlib import Path

import pytest

RAW_TEXT = (
    "Lethukuthula Brian Wanda\n\n"
    "Cell Number: 0710093985/ 0720900034\n\n"
    "Email Address: ThulasMathetha@gmail.com\n\n"
    "PROFILE\n\n"
    "I am a Junior Software Developer with hands-on experience in Java Full stack and C#\n"
    "development. Skilled in building and supporting enterprise-level applications,\n"
    "working across both legacy and modern systems. Strong knowledge of java, spring\n"
    "boot, angular, and database (MySQL, PostgreSQL, DB2). Passionate about problem-\n"
    "solving, system optimization, and continuous learning, with proven ability to work in\n"
    "agile teams\n\n"
    "PERSONAL DETAILS\n\n"
    "Names\n\n"
    ": Lethukuthula Brian\n\n"
    "Surname\n\n"
    ": Wanda\n\n"
    "Date of Birth\n\n"
    ": 08 April 1995\n\n"
    "Nationality\n\n"
    ": South African\n\n"
    "Location : Durban, KwaZulu-Natal\n\n"
    "EE\n\n"
    ": Black male\n\n"
    "Driver\u2019s License : Code 10\n\n"
    "EDUCATION\n\n"
    "2026\n\n"
    "ISTQB Foundation\n"
    "Certificate : ISTQB Certificate\n\n"
    "2021\n\n"
    "National Diploma in Information Technology\n"
    ":\n"
    "Durban University of\n"
    "Technology 2013\n\n"
    "Grade 12\n"
    ":\n"
    "Umlazi Comtech High School\n\n"
    "WORKING HISTORY\n\n"
    "July 2024 \u2013 Present\n\n"
    "Company\n\n"
    ": FNB\n\n"
    "Position Held\n\n"
    ": Junior Developer\n\n"
    "Projects Worked on at FNB:\n\n"
    "\u2022 Credit Management system\n"
    "\u2022 Credit Application system\n"
    "\u2022 Credit Recoveries System Tools I use in FNB:\n\n"
    "Responsibilities at FNB:\n\n"
    "\u2022 I am doing system support (Doing Incidents) for the three Java systems\n"
    "\u2022 I add new features on both the front-end and the backend\n"
    "\u2022 I assist with creation of new APIs\n\n"
    "July 2023 \u2013 June 2024\n\n"
    "Company\n\n"
    ": Geeks4learning\n\n"
    "Position Held\n\n"
    ": Java Full Stack Developer Internship\n\n"
    "Responsibilities at Geeks4learning\n\n"
    "\u2022 The first seven months we were in a bootcamp\n"
    "\u2022 I sat with Business analysts to discuss new features\n\n"
    "March 2022 \u2013 March 2023\n\n"
    "Company\n\n"
    ": Toyota Tsusho\n\n"
    "Position Held\n\n"
    ": C# Developer Learnership\n\n"
    "Responsibilities at Toyota Tsusho\n\n"
    "\u2022 The first 8 to 9 months we were in a bootcamp\n"
    "\u2022 I sat with Business analysts to discuss implementation\n\n"
    "REFERENCES\n\n"
    "Available upon on request"
)


@pytest.fixture
def profile():
    from app.parsers import parse_sections
    from app.normalizers import profile_from_sections

    sections = parse_sections(RAW_TEXT)
    return profile_from_sections(RAW_TEXT, sections, Path("Lethu_wanda_CV.pdf"))


@pytest.fixture
def template_state(profile):
    from app.normalizers import profile_to_template_state

    return profile_to_template_state(profile)


# --- Identity ---

def test_full_name(profile):
    assert profile["identity"]["full_name"] == "Lethukuthula Brian Wanda"


def test_headline_not_professional_profile(template_state):
    headline = template_state.get("headline", "")
    assert headline != "Professional Profile"
    assert headline  # not empty


def test_phone_extracted(profile):
    phone = profile["identity"].get("phone") or ""
    assert "0710093985" in phone or "0720900034" in phone


# --- Summary ---

def test_summary_has_content(profile):
    summary = profile.get("summary") or ""
    assert "Junior Software Developer" in summary


def test_summary_stops_before_personal_details(profile):
    summary = (profile.get("summary") or "").lower()
    for bad_term in ["date of birth", "nationality", "south african", "black male", "driver"]:
        assert bad_term not in summary, f"Summary contains personal detail: {bad_term}"


# --- Education / Qualifications ---

def test_qualifications_include_national_diploma(profile):
    quals = [e.get("qualification", "").lower() for e in profile.get("education", [])]
    assert any("national diploma" in q for q in quals)


def test_qualifications_include_grade_12(profile):
    quals = [e.get("qualification", "").lower() for e in profile.get("education", [])]
    assert any("grade 12" in q for q in quals)


def test_national_diploma_correct_institution(profile):
    for e in profile.get("education", []):
        if "national diploma" in (e.get("qualification") or "").lower():
            assert "durban university" in (e.get("institution") or "").lower()
            break
    else:
        pytest.fail("National Diploma not found in education")


# --- Certifications ---

def test_certifications_contain_istqb(profile):
    certs = profile.get("certifications", [])
    cert_text = " ".join(certs).lower()
    assert "istqb" in cert_text


def test_certifications_no_work_history_text(profile):
    certs = profile.get("certifications", [])
    cert_text = " ".join(certs).lower()
    for bad in ["fnb", "geeks4learning", "toyota", "junior developer", "responsibilities"]:
        assert bad not in cert_text, f"Certification contains work-history text: {bad}"


# --- Experience ---

def test_experience_has_three_roles(profile):
    entries = profile.get("experience", [])
    assert len(entries) == 3


def test_experience_companies(profile):
    companies = [e.get("company", "").lower() for e in profile.get("experience", [])]
    assert any("fnb" in c for c in companies)
    assert any("geeks4learning" in c for c in companies)
    assert any("toyota" in c for c in companies)


def test_experience_positions(profile):
    positions = [e.get("position", "").lower() for e in profile.get("experience", [])]
    assert any("developer" in p or "junior" in p for p in positions)


def test_experience_dates(profile):
    entries = profile.get("experience", [])
    for e in entries:
        assert e.get("start_date") or e.get("end_date"), f"Missing dates for {e.get('company')}"


# --- Career Summary ---

def test_career_summary_has_three_roles(template_state):
    cs = template_state.get("career_summary", "")
    assert "FNB" in cs
    assert "Geeks4learning" in cs
    assert "Toyota Tsusho" in cs


# --- Career History ---

def test_career_history_has_three_roles(template_state):
    ch = template_state.get("career_history", "")
    assert "FNB" in ch
    assert "Geeks4learning" in ch
    assert "Toyota Tsusho" in ch


# --- Location cleanup ---

def test_location_stripped_of_label(template_state):
    loc = template_state.get("location", "")
    assert not loc.lower().startswith("location")
    assert "Durban" in loc
