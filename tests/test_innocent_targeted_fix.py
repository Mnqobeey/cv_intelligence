from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.normalizers import profile_from_sections, profile_to_template_state, validate_profile_readiness
from app.parsers import parse_sections
from app.utils_text import extract_text


BASE_DIR = Path(__file__).resolve().parents[1]
INNOCENT_PDF = BASE_DIR / "uploads" / "24bb9db5-6662-4de2-a0d1-dd47820c5fa2.pdf"
INNOCENT_SOURCE_NAME = Path("CV_Innocent_Phiri.pdf")
EXPECTED_RESPONSIBILITIES = [
    "Designed and executed automated test scripts using Java + Selenium",
    "Developed structured manual test cases from system requirements",
    "Logged, tracked and verified defects using Jira",
    "Supported CI/CD pipeline processes alongside DevOps team",
    "Assisted with regression and release testing before deployments",
    "Worked in Agile/Scrum environment with developers and engineers",
]


def _upload(client: TestClient, source_path: Path) -> dict:
    response = client.post(
        "/api/upload",
        files={"file": (source_path.name, source_path.read_bytes(), "application/pdf")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_innocent_pdf_shared_pipeline_reclassifies_dense_leakage_cleanly():
    raw_text = extract_text(INNOCENT_PDF)
    sections = parse_sections(raw_text)
    profile = profile_from_sections(raw_text, sections, INNOCENT_SOURCE_NAME)
    state = profile_to_template_state(profile)
    issues = validate_profile_readiness(state)

    assert profile["identity"]["full_name"] == "Innocent Celimpilo Phiri"
    assert state["full_name"] == "Innocent Celimpilo Phiri"
    assert state["headline"] == "Junior Software Tester"
    assert state["email"] == "innocentmpilo1@gmail.com"
    assert state["phone"] == "+27 64 707 0704"
    assert "Midrand" in state["region"]
    assert state["linkedin"].endswith("innocent-celimpilo-phiri-632796279")
    assert state["summary"].startswith("Detail-oriented Software Tester with hands-on experience")
    assert state["summary"] != "Personal Details"

    skill_lines = state["skills"].splitlines()
    assert "Systems Networking" in skill_lines
    assert "Computer Literate (Proficiency in Microsoft Office)" in skill_lines
    assert "Mathematical and Computational thinking" in skill_lines
    assert "Java,Python,C++,C#,JavaScript,Php, SQL, HTML_5,CSS, XML" in skill_lines
    for forbidden in [
        "2 Diagonal Street Gauteng Midrand 1685",
        "+27 64 707 0704 | innocentmpilo1@gmail.com",
        "Date of Birth",
        "Marital Status",
        "Nationality",
        "Gender",
        "Race",
        "Criminal Offense : None",
        "Dannhauser Secondary School",
        "National Senior Certificate",
        "University Of Zululand",
        "BSc Applied Mathematics & Computer Science",
        "Cestasoft Solutions",
        "Junior Software Tester",
        "2024 - 2025",
        "Achievements & Awards",
    ]:
        assert forbidden not in state["skills"]

    education_rows = {
        (row["qualification"], row["institution"])
        for row in profile["education"]
    }
    assert ("National Senior Certificate", "Dannhauser Secondary School") in education_rows
    assert ("BSc Applied Mathematics & Computer Science", "University Of Zululand") in education_rows
    assert "National Senior Certificate" not in state["certifications"]
    assert state["certifications"] == "No certifications listed"

    assert state["languages"].splitlines() == ["English", "IsiZulu"]

    assert len(profile["experience"]) == 1
    experience = profile["experience"][0]
    assert experience["company"] == "Cestasoft Solutions"
    assert experience["position"] == "Junior Software Tester"
    assert experience["start_date"] == "2024"
    assert experience["end_date"] == "2025"
    assert experience["responsibilities"] == EXPECTED_RESPONSIBILITIES

    assert state["career_summary"] == "Junior Software Tester - Cestasoft Solutions (2024 – 2025)"
    assert "Cestasoft Solutions | Junior Software Tester | 2024 | 2025" in state["career_history"]
    for forbidden in [
        "2 Diagonal Street Gauteng Midrand 1685",
        "Date of Birth",
        ": Single",
        ": Male",
        ": African",
        "Criminal Offense : None",
        "BSc Applied Mathematics & Computer Science",
        "Read - English , IsiZulu",
        "Write - English , IsiZulu",
    ]:
        assert forbidden not in state["career_history"]

    assert "Distinctions" not in state["references"]
    assert "Top Achiever" in state["awards"]
    assert issues == []


def test_innocent_pdf_upload_flow_is_review_ready_without_cross_section_leakage():
    client = TestClient(create_app())
    payload = _upload(client, INNOCENT_PDF)

    state = payload["template_state"]
    workflow = payload["workflow_state"]
    review_sections = {section["key"]: section for section in payload["review_board"]["sections"]}

    assert state["full_name"] == "Innocent Celimpilo Phiri"
    assert state["headline"] == "Junior Software Tester"
    assert state["summary"].startswith("Detail-oriented Software Tester with hands-on experience")
    assert state["education"]
    assert state["career_summary"] == "Junior Software Tester - Cestasoft Solutions (2024 – 2025)"
    assert "National Senior Certificate" not in state["certifications"]
    assert state["languages"].splitlines() == ["English", "IsiZulu"]
    assert workflow["review_ready"] is True
    assert workflow["blocking_issues"] == []
    assert review_sections["summary"]["status"] == "Ready"
    assert review_sections["education"]["status"] == "Ready"
    assert review_sections["career_history"]["status"] == "Ready"
