from pathlib import Path

from app.normalizers import profile_from_sections, profile_to_template_state, validate_profile_readiness
from app.parsers import parse_sections
from app.utils_text import extract_text


BASE_DIR = Path(__file__).resolve().parents[1]
SANDISIWE_DOCX = BASE_DIR / "uploads" / "9213916c-303d-4a2e-94dd-d26efa1bc9c5.docx"
SANDISIWE_SOURCE_NAME = Path("Sandisiwe_Vutula_JB.docx")


def test_sandisiwe_docx_shared_pipeline_keeps_identity_sections_and_experience_clean():
    raw_text = extract_text(SANDISIWE_DOCX)
    sections = parse_sections(raw_text)
    profile = profile_from_sections(raw_text, sections, SANDISIWE_SOURCE_NAME)
    state = profile_to_template_state(profile)
    issues = validate_profile_readiness(state)

    assert profile["identity"]["full_name"] == "SANDISIWE VUTULA"
    assert profile["identity"]["headline"] == "Senior Software Engineer"
    assert state["full_name"] == "SANDISIWE VUTULA"
    assert state["headline"] == "Senior Software Engineer"
    assert state["availability"] == "Notice period not applicable / immediate"
    assert state["region"] == "Johannesburg"
    assert state["phone"] == ""

    assert state["languages"].splitlines() == ["English"]

    assert "CERTIFICATES / COURSES / TRAINING" not in state["summary"]
    assert "Certificate / Course / Training" not in state["summary"]
    assert state["summary"].startswith("Senior Software Engineer with hands-on experience")

    skill_lines = state["skills"].splitlines()
    assert "C#" in skill_lines
    assert ".NET Frameworks" in skill_lines
    assert "Azure DevOps" in skill_lines
    assert "React.js" in skill_lines
    assert "SANDISIWE VUTULA" not in skill_lines
    assert "EDUCATION / QUALIFICATIONS" not in state["skills"]
    assert "Organisation:" not in state["skills"]

    education_lines = state["education"].splitlines()
    assert "National Diploma: Information Technology | Cape Peninsula University of Technology | Incomplete (2011 – 2014)" in education_lines
    assert "Senior Certificate (Grade 12 / Matric) | Mgomanzi Senior Secondary School | 2009" in education_lines
    assert all("Certificate / Course / Training" not in line for line in education_lines)

    assert "Software Development Bootcamp | EOH | 2014 (3 months)" in state["training"]
    assert "Certificate / Course / Training | Institution | Date" not in state["training"]
    assert "ADDITIONAL CERTIFICATES / COURSES / TRAINING" not in state["training"]
    assert "LinkedIn (2023 – 2024)" in state["training"]

    expected_roles = [
        ("DigiOutsource Services", "Senior Software Engineer", "Mar 2025", "Aug 2025"),
        ("BET Software (Hollywood Bets)", "Senior Software Developer (Withdrawals Team)", "Jun 2024", "Dec 2024"),
        ("E4 Strategic", "Software Engineer", "Mar 2023", "Feb 2024"),
        ("Life Healthcare Group (via CyberPro Consulting)", ".NET Developer", "Jul 2022", "Feb 2023"),
        ("MiX Telematics (via Immersant Data Solutions)", "Software Developer", "Sep 2020", "Jun 2022"),
        ("Avocado Chocolate", "Software Developer", "Feb 2020", "May 2020"),
        ("Capitec Bank", "Developer", "Jun 2019", "Dec 2019"),
        ("Unlimited Internet Play", "Intermediate Software Engineer", "Nov 2018", "Mar 2019"),
        ("Ipreo by IHS Markit", "SQA Engineer", "May 2018", "Oct 2018"),
        ("FinChoice", "Software Developer", "Jun 2016", "Apr 2018"),
        ("EOH Coastal", "Junior Developer (.NET)", "Oct 2014", "May 2016"),
    ]
    assert [
        (entry["company"], entry["position"], entry["start_date"], entry["end_date"])
        for entry in profile["experience"]
    ] == expected_roles

    assert state["career_summary"].splitlines()[0] == "Senior Software Engineer - DigiOutsource Services (Mar 2025 – Aug 2025)"
    assert "DigiOutsource Services | Senior Software Engineer | Mar 2025 | Aug 2025" in state["career_history"]
    assert "BET Software (Hollywood Bets) | Senior Software Developer (Withdrawals Team) | Jun 2024 | Dec 2024" in state["career_history"]
    assert "E4 Strategic | Software Engineer | Mar 2023 | Feb 2024" in state["career_history"]

    assert "After completing the 3-month software development bootcamp" in state["awards"]
    assert "Awards: | Key Achievements /" not in state["awards"]

    assert "Relocation: Yes" in state["additional_sections"]
    assert "Nationality: South African" in state["additional_sections"]
    assert "ID Number" not in state["additional_sections"]
    assert "Languages: | English" not in state["additional_sections"]

    assert not any("Professional Headline" in issue for issue in issues)
    assert not any("Qualifications contain malformed" in issue for issue in issues)
    assert not any("Career History contains malformed" in issue for issue in issues)
