from pathlib import Path

from app.normalizers import profile_from_sections, profile_to_template_state, validate_profile_readiness
from app.parsers import parse_education_section, parse_sections


THANDOKUHLE_RAW = """
Thandokuhle Mnqobi Mntambo
QA Intern mnqobimntambo@gmail.com

078 568 3003

Bryanston, South Africa

za.linkedin.com/in/thandokuhle-mntambo

mnqobeey.netlify.app

Professional Summary
Information Systems Honours graduate with strong skills in SQL, Power BI, data analytics, and business intelligence.
Experienced in transforming raw data into actionable insights through data modelling, visualization, and reporting.

Education
BCom Honours - Information Systems and Business Management,
Nelson Mandela University
2023 – 2024
BCom - Information Systems and Business Management, Nelson Mandela University 2020 – 2022

Technical Skills
Data & Analytics
•Power BI
•Data Cleaning & Preparation
Programming
•Python
•C# (ASP.NET fundamentals)
Professional Skills
•Analytical Thinking & Problem Solving
•Communication & Team Collaboration
Productivity Tools
•Microsoft Excel (data analysis & visualization)
•Microsoft Office Suite
Automation Testing
•UFT One
•Selenium WebDriver
"""


def test_thandokuhle_identity_prefers_header_name_and_inline_role(tmp_path: Path):
    profile = profile_from_sections(
        THANDOKUHLE_RAW,
        parse_sections(THANDOKUHLE_RAW),
        tmp_path / "Thandokuhle_Mnqobi_Mntambo_FlowCV_Resume_2026-03-06 (1).pdf",
    )
    state = profile_to_template_state(profile)

    assert profile["identity"]["full_name"] == "Thandokuhle Mnqobi Mntambo"
    assert profile["identity"]["headline"] == "QA Intern"
    assert state["full_name"] == "Thandokuhle Mnqobi Mntambo"
    assert state["headline"] == "QA Intern"
    assert state["full_name"] != "Productivity Tools"
    assert state["headline"] != "•Microsoft Excel (data analysis & visualization)"


def test_thandokuhle_multiline_education_rows_are_reconstructed_cleanly(tmp_path: Path):
    education_section = """
    Education
    BCom Honours - Information Systems and Business Management,
    Nelson Mandela University
    2023 – 2024
    BCom - Information Systems and Business Management, Nelson Mandela University 2020 – 2022
    Technical Skills
    """
    rows = parse_education_section(education_section)
    profile = profile_from_sections(
        THANDOKUHLE_RAW,
        parse_sections(THANDOKUHLE_RAW),
        tmp_path / "Thandokuhle_Mnqobi_Mntambo_CV.pdf",
    )
    state = profile_to_template_state(profile)

    assert rows == [
        {
            "qualification": "BCom Honours - Information Systems and Business Management",
            "institution": "Nelson Mandela University",
            "start_date": "2023",
            "end_date": "2024",
            "sa_standard_hint": "NQF 8 Honours Degree",
        },
        {
            "qualification": "BCom - Information Systems and Business Management",
            "institution": "Nelson Mandela University",
            "start_date": "2020",
            "end_date": "2022",
            "sa_standard_hint": None,
        },
    ]
    assert state["education"].splitlines() == [
        "BCom Honours - Information Systems and Business Management | Nelson Mandela University | 2023 | 2024",
        "BCom - Information Systems and Business Management | Nelson Mandela University | 2020 | 2022",
    ]


def test_invalid_identity_heading_leak_cannot_pass_readiness():
    state = {
        "full_name": "Productivity Tools",
        "headline": "•Microsoft Excel (data analysis & visualization)",
        "summary": "QA Intern with hands-on validation experience across web and API workflows.",
        "skills": "Testing: API Testing\nTools: Jira",
        "education": "BCom Information Systems | University of Johannesburg | 2021",
        "career_history": "OpenText | QA Intern | Jan 2025 | Present\nExecuted regression and smoke testing.",
    }
    issues = validate_profile_readiness(state)

    assert any("Full Name needs a valid candidate name" in issue for issue in issues)
    assert any("Professional Headline needs a cleaner" in issue for issue in issues)
