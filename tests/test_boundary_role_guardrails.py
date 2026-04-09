from pathlib import Path

from app.normalizers import build_review_board, profile_from_sections, profile_to_template_state, validate_profile_readiness
from app.parsers import parse_sections


def test_skill_line_does_not_become_headline(tmp_path: Path):
    raw = """
    Thandokuhle Mntambo
    Selenium
    Jira
    API Testing
    Career History
    OpenText | Junior Software Tester | Jan 2025 | Present
    Executed regression and API tests.
    Qualifications
    BCom Information Systems | University of Johannesburg | 2021
    """
    profile = profile_from_sections(raw, parse_sections(raw), tmp_path / 'candidate.docx')
    state = profile_to_template_state(profile)
    assert state['headline'] == 'Junior Software Tester'


def test_national_senior_certificate_stays_in_qualifications_not_certifications(tmp_path: Path):
    raw = """
    Qualifications
    National Senior Certificate | Queens High School | 2018
    Certifications
    ISTQB Foundation Level | ISTQB | 2024
    Career History
    OpenText | QA Intern | Jan 2025 | Present
    Executed regression testing.
    """
    profile = profile_from_sections(raw, parse_sections(raw), tmp_path / 'candidate.docx')
    state = profile_to_template_state(profile)
    assert 'National Senior Certificate | Queens High School | 2018' in state['education']
    assert 'National Senior Certificate' not in state['certifications']
    assert 'ISTQB Foundation Level' in state['certifications']


def test_references_do_not_leak_into_career_history_and_headings_terminate_experience(tmp_path: Path):
    raw = """
    Career History
    OpenText | QA Intern | Jan 2025 | Present
    Executed regression testing.
    Achievements & Awards
    Dean's List 2024
    References
    Dr Jane Smith
    jane.smith@example.com
    Senior Lecturer
    Qualifications
    BSc Information Technology | North-West University | 2024
    """
    profile = profile_from_sections(raw, parse_sections(raw), tmp_path / 'candidate.docx')
    state = profile_to_template_state(profile)
    assert 'Dr Jane Smith' not in state['career_history']
    assert 'Dean\'s List' not in state['career_history']
    issues = validate_profile_readiness(state)
    assert not any('third-party contacts' in issue for issue in issues)


def test_email_domain_fragment_does_not_become_portfolio(tmp_path: Path):
    raw = """
    Thandokuhle Mntambo
    QA Analyst
    Email: thando@gmail.com
    Career History
    OpenText | QA Analyst | Jan 2025 | Present
    Validated API and web workflows.
    Qualifications
    BCom Information Systems | University of Johannesburg | 2021
    """
    profile = profile_from_sections(raw, parse_sections(raw), tmp_path / 'candidate.docx')
    state = profile_to_template_state(profile)
    assert state['portfolio'] == 'Portfolio not provided'


def test_most_recent_professional_role_becomes_headline_in_multi_role_cv(tmp_path: Path):
    raw = """
    Thandokuhle Mntambo
    Profile
    Aspiring technology professional with a passion for testing.
    Career History
    University Tutor | University of Johannesburg | Jan 2023 | Dec 2023
    Supported student learning sessions.
    OpenText | QA Analyst | Jan 2025 | Present
    Executed regression and API testing.
    Qualifications
    BCom Information Systems | University of Johannesburg | 2021
    """
    profile = profile_from_sections(raw, parse_sections(raw), tmp_path / 'candidate.docx')
    state = profile_to_template_state(profile)
    assert state['headline'] == 'QA Analyst'


def test_review_honesty_marks_reference_contaminated_history_for_review():
    state = {
        'full_name': 'Thandokuhle Mntambo',
        'headline': 'QA Analyst',
        'summary': 'QA Analyst with experience in web and API testing.',
        'skills': 'Testing: API Testing\nTools: Jira',
        'education': 'BCom Information Systems | University of Johannesburg | 2021',
        'career_history': 'OpenText | QA Analyst | Jan 2025 | Present\nExecuted testing.\nReferences\nDr Jane Smith\nSenior Lecturer',
    }
    issues = validate_profile_readiness(state)
    assert any('Career History appears contaminated' in issue for issue in issues)
    review = build_review_board(state, None)
    career_section = next(section for section in review['sections'] if section['key'] == 'career_history')
    assert career_section['status'] == 'Needs review'


def test_review_readiness_allows_academic_employment_roles():
    state = {
        'full_name': 'Thandokuhle Mntambo',
        'headline': 'Research Assistant',
        'summary': 'Research assistant supporting data collection, lab coordination, and delivery of structured reporting across university projects.',
        'skills': 'Research Tools: Excel\nDelivery: Documentation',
        'education': 'BCom Information Systems | University of Johannesburg | 2021',
        'career_summary': 'Research Assistant - University of Johannesburg (Jan 2024 – Present)',
        'career_history': 'University of Johannesburg | Research Assistant | Jan 2024 | Present\nSupported laboratory operations and documented findings.',
    }
    issues = validate_profile_readiness(state)
    assert not any('pure education records' in issue for issue in issues)
