from pathlib import Path

from app.normalizers import profile_from_sections, profile_to_template_state, validate_profile_readiness
from app.parsers import extract_identity, parse_experience_section, parse_sections


def test_compressed_consulting_header_and_single_parent_role(tmp_path: Path):
    raw_text = """
    GEORGE THABISO MPOPO | Senior Software Engineering Consultant | george@example.com | +27 82 555 1111
    PROFESSIONAL SUMMARY
    Results-driven consultant delivering enterprise modernisation programmes.
    EXPERIENCE
    Gijima Technologies | Senior Software Engineering Consultant | Jan 2020 | Present
    Client: Standard Bank | Project: Enterprise Platform Modernisation
    Led integration planning across enterprise APIs and platforms.
    Client: Nedbank | Project: Core Banking Modernisation
    Coordinated migration planning and engineering delivery.
    """
    sections = parse_sections(raw_text)
    profile = profile_from_sections(raw_text, sections, tmp_path / "George Mpopo CV.docx")
    assert profile["identity"]["full_name"] == "GEORGE THABISO MPOPO"
    assert "Consultant" in profile["identity"]["headline"]
    assert len(profile["experience"]) == 1
    bullets = " ".join(profile["experience"][0]["responsibilities"])
    assert "Standard Bank" in bullets and "Nedbank" in bullets


def test_identity_can_appear_after_summary_without_reference_contamination(tmp_path: Path):
    raw_text = """
    PROFILE SUMMARY
    Experienced project coordinator supporting delivery teams across client-facing engagements.
    REFERENCES
    Dr Jane Smith
    Senior Lecturer
    082 000 0000
    jane.smith@example.com

    Lavina Jacobs
    Project Coordinator
    lavina@example.com
    083 111 2222
    Qualifications
    Diploma in Project Management | PM Institute | 2020
    """
    sections = parse_sections(raw_text)
    identity = extract_identity(raw_text, sections, tmp_path / "Share CV of Lavina Jacobs .docx")
    assert identity["full_name"] == "Lavina Jacobs"
    assert identity["email"] == "lavina@example.com"
    assert identity["phone"] == "083 111 2222"


def test_table_like_rows_separate_qualifications_and_certifications(tmp_path: Path):
    raw_text = """
    Qualifications
    Qualification | Institution | Year
    BCom Information Systems | University of Johannesburg | 2021
    Certifications
    Certification | Provider | Year
    SAP HANA Certified Associate | SAP | 2024
    """
    sections = parse_sections(raw_text)
    profile = profile_from_sections(raw_text, sections, tmp_path / "Share MC Mashau Resume 2025.docx")
    assert any(row["qualification"] == "BCom Information Systems" for row in profile["education"])
    assert any("SAP HANA Certified Associate" in cert for cert in profile["certifications"])


def test_academic_projects_do_not_become_career_history(tmp_path: Path):
    raw_text = """
    Career History
    OpenText | QA Intern | Jan 2025 | Present
    Executed regression testing across web and API workflows.
    Projects
    Student Feedback Platform | Honours Project | 2024
    Built using C# and HTML/CSS.
    References on Request
    """
    sections = parse_sections(raw_text)
    profile = profile_from_sections(raw_text, sections, tmp_path / "Thandokuhle Mntambo - CV.pdf")
    assert len(profile["experience"]) == 1
    assert profile["experience"][0]["company"] == "OpenText"
    assert profile["experience"][0]["position"] == "QA Intern"


def test_weak_summary_blocks_review_even_when_other_sections_exist():
    state = {
        "full_name": "Thandokuhle Mntambo",
        "headline": "QA Analyst",
        "summary": "I am a hardworking person seeking growth.",
        "skills": "Selenium\nAPI Testing",
        "education": "BSc IT | North-West University | 2024",
        "career_history": "OpenText | QA Intern | Jan 2025 | Present\nExecuted regression testing across web and API workflows.",
    }
    issues = validate_profile_readiness(state)
    assert any("Career Summary" in issue for issue in issues)


def test_profile_to_template_state_preserves_guarded_optional_defaults(tmp_path: Path):
    raw_text = """
    Thandokuhle Mntambo
    QA Analyst
    Skills
    Selenium | API Testing
    Qualifications
    BSc Information Technology | North-West University | 2024
    Career History
    OpenText | QA Intern | Jan 2025 | Present
    Executed regression testing across web and API workflows.
    """
    sections = parse_sections(raw_text)
    profile = profile_from_sections(raw_text, sections, tmp_path / "candidate.docx")
    state = profile_to_template_state(profile)
    assert state["availability"] == "Availability not provided"
    assert state["region"] in {"Region not provided", "South Africa"}


def test_career_history_responsibilities_are_not_duplicated(tmp_path: Path):
    raw_text = """
    Lindelwe Myeza
    COBOL SOFTWARE DEVELOPER
    Career History
    FIRST NATIONAL BANK | COBOL SOFTWARE DEVELOPER | Feb 2024 | Present
    Maintain legacy banking systems.
    Maintain legacy banking systems.
    """
    sections = parse_sections(raw_text)
    profile = profile_from_sections(raw_text, sections, tmp_path / 'candidate.docx')
    state = profile_to_template_state(profile)
    assert state['career_history'].count('Responsibilities:') == 1
    assert state['career_history'].count('Maintain legacy banking systems.') == 1
