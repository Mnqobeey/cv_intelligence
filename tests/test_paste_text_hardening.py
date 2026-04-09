from fastapi.testclient import TestClient

from app.main import create_app


MESSY_HEADING_TEXT = """
 personal details
Lerato Mokoena
Senior Software Developer
Email : lerato@example.com   Phone: +27 82 555 1234
Location : Johannesburg, South Africa

PROFILE
Results-driven developer with strong enterprise platform delivery experience across backend services and release quality work.

technical   skills
C#
.NET
React
SQL
Azure DevOps

work   experience
BrightPath Technologies | Senior Software Developer | March 2022 | Present
Designed backend services and mentored developers.

education
BSc Computer Science | University of Johannesburg | 2019
""".strip()

BROKEN_WRAP_TEXT = """
Lerato Mokoena
Senior Software Developer
Email: lerato@example.
com
Phone: +27 82 555
1234
Johannesburg, South Africa

Professional Summary
Results-driven Senior Software Developer with strong experience delivering enterprise platforms
and improving release quality across modern teams.

Skills
C#
.NET
React
SQL
Azure DevOps

Employment History
BrightPath Technologies | Senior Software Developer |
March 2022 | Present
Designed backend services and mentored developers.

Education
BSc Computer Science | University of Johannesburg | 2019
""".strip()

SAME_LINE_IDENTITY_TEXT = """
Name: Rudzani Mofokeng | Email: rudzani902@gmail.com | Phone: +27 82 000 0000 | Location: Sky City
Headline: C# Developer

Professional Summary: Results-driven C# Developer with experience building reliable software platforms and supporting enterprise teams.

Skills: C#; .NET; SQL; Azure DevOps

Work Experience
Research Assistant - University of Johannesburg (January 2024 to Present)
Responsibilities: Supported lab operations; Documented findings

Qualifications
BSc Computer Science | University of Johannesburg | 2022
""".strip()

HEADER_FOOTER_NOISE_TEXT = """
Curriculum Vitae - Page 1
Naledi Khumalo
Platform Engineer
Email: naledi@example.com | Phone: +27 82 999 8888

Profile
Platform Engineer focused on backend services, deployment quality, and enterprise workflow tooling.

Skills
Python
TypeScript
Azure DevOps
Docker

Work Experience
Northstar Systems | Platform Engineer | 2022 | Present
Built deployment tooling and backend services.

Curriculum Vitae - Page 2
Education
BSc Information Technology | University of Johannesburg | 2020
Curriculum Vitae - Page 2
""".strip()

PORTFOLIO_LABEL_TEXT = """
Naledi Khumalo
Platform Engineer
Portfolio: https://naledikhumalo.dev
Email: naledi@example.com
Phone: +27 82 999 8888

Summary
Platform Engineer focused on backend services and delivery quality across modern enterprise teams.

Skills
Python
TypeScript
Docker

Experience
Northstar Systems | Platform Engineer | 2022 | Present
Built deployment tooling and backend services.

Education
BSc Information Technology | University of Johannesburg | 2020
""".strip()

PURE_EDUCATION_RAW_TEXT = """
Name: Student Example | Email: student@example.com | Phone: +27 82 123 4567 | Location: Johannesburg
Headline: Software Developer

Professional Summary: Graduate candidate with strong academic performance and project work across structured technical coursework.

Skills: Python; SQL

Work Experience
Database Systems Module - University of Johannesburg (January 2024 to November 2024)
Responsibilities: Completed coursework; Submitted assignments

Qualifications
BSc Computer Science | University of Johannesburg | 2025
""".strip()


def _review_and_export(client: TestClient, payload: dict):
    review = client.post(
        f"/api/document/{payload['document_id']}/review-complete",
        json={"template_state": payload["template_state"]},
    )
    export = None
    if review.status_code == 200:
        export = client.post(
            f"/api/document/{payload['document_id']}/export",
            json={"template_state": payload["template_state"]},
        )
    return review, export


def test_paste_text_handles_inconsistent_heading_spacing_and_case():
    client = TestClient(create_app())
    response = client.post("/api/upload-text", json={"text": MESSY_HEADING_TEXT})
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["template_state"]["full_name"] == "Lerato Mokoena"
    assert payload["template_state"]["headline"] == "Senior Software Developer"
    assert "Employment History" not in payload["template_state"]["skills"]

    review, export = _review_and_export(client, payload)
    assert review.status_code == 200, review.text
    assert export is not None and export.status_code == 200, export.text


def test_paste_text_repairs_wrapped_email_and_phone_lines():
    client = TestClient(create_app())
    response = client.post("/api/upload-text", json={"text": BROKEN_WRAP_TEXT})
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["template_state"]["email"] == "lerato@example.com"
    assert payload["template_state"]["phone"] == "+27 82 555 1234"


def test_paste_text_same_line_identity_fields_and_academic_role_complete_review():
    client = TestClient(create_app())
    response = client.post("/api/upload-text", json={"text": SAME_LINE_IDENTITY_TEXT})
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["template_state"]["full_name"] == "Rudzani Mofokeng"
    assert payload["template_state"]["headline"] == "C# Developer"
    assert payload["template_state"]["location"] == "Sky City"
    assert "Research Assistant" in payload["template_state"]["career_history"]
    assert "University of Johannesburg" in payload["template_state"]["career_history"]

    review, export = _review_and_export(client, payload)
    assert review.status_code == 200, review.text
    assert export is not None and export.status_code == 200, export.text


def test_paste_text_strips_page_header_footer_noise_from_experience_and_education():
    client = TestClient(create_app())
    response = client.post("/api/upload-text", json={"text": HEADER_FOOTER_NOISE_TEXT})
    assert response.status_code == 200, response.text
    payload = response.json()

    assert "Curriculum Vitae - Page 2" not in payload["template_state"]["career_history"]
    assert "Curriculum Vitae - Page 2" not in payload["template_state"]["education"]


def test_paste_text_does_not_treat_portfolio_label_as_projects_section():
    client = TestClient(create_app())
    response = client.post("/api/upload-text", json={"text": PORTFOLIO_LABEL_TEXT})
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["template_state"]["portfolio"] == "https://naledikhumalo.dev"
    assert "https://naledikhumalo.dev" not in payload["template_state"]["projects"]
    assert "naledi@example.com" not in payload["template_state"]["projects"]
    assert "+27 82 999 8888" not in payload["template_state"]["projects"]


def test_invalid_raw_paste_text_fails_cleanly_for_pure_education_history():
    client = TestClient(create_app())
    response = client.post("/api/upload-text", json={"text": PURE_EDUCATION_RAW_TEXT})
    assert response.status_code == 200, response.text
    payload = response.json()

    review = client.post(
        f"/api/document/{payload['document_id']}/review-complete",
        json={"template_state": payload["template_state"]},
    )
    assert review.status_code == 400, review.text
    detail = review.json()["detail"]
    assert detail["message"] == "Profile is not ready for review completion."
    assert "Career History contains pure education records that must be removed." in detail["issues"]
