import json

from fastapi.testclient import TestClient

from app.main import create_app


STRUCTURED_JSON_SAMPLE = {
    "cestacv_version": 1,
    "identity": {
        "full_name": "\n  Rudzani Mofokeng  \n",
        "headline": "C# Developer",
        "availability": "",
        "region": "",
        "email": "rudzani902@gmail.com\n",
        "phone": "0623626109",
        "location": "3999 Crestfish street, Ext 20, Sky city",
        "linkedin": "",
        "portfolio": "",
    },
    "career_summary": "C# developer with experience building business applications, maintaining clean delivery practices, and supporting recruiter-ready client profiles.",
    "skills": [
        {"category": "Technical Skills", "items": ["C#", ".NET", "SQL"]}
    ],
    "qualifications": [
        {"qualification": "Matric", "institution": "Sky City High School", "year": "2018"}
    ],
    "certifications": [],
    "training": [{"name": "Azure Fundamentals", "provider": "Microsoft", "year": "2024"}],
    "achievements": [{"title": "Top Performer", "year": "2024"}],
    "languages": [{"name": "English", "proficiency": "Native"}],
    "interests": [{"name": "Open source"}],
    "references": [{"name": "Jane Doe", "role": "Engineering Manager", "email": "jane@example.com"}],
    "projects": [{"name": "Internal Builder", "details": "Built recruiter workflow tooling"}],
    "career_history": [
        {
            "job_title": "C# Developer",
            "company": "CestaSoft",
            "start_date": "Jan 2024",
            "end_date": "Present",
            "responsibilities": ["  Built internal tools  ", "\nSupported client engagements\n"],
        }
    ],
    "additional_sections": [{"title": "Notice Period", "content": "\n30 days\n"}],
}

JOSHUA_RATAU_JSON = """{"cestacv_version":1,"identity":{"full_name":"Joshua Ratau","headline":"Full Stack Developer – Specializing in Web and Mobile Applications","availability":"","region":"","email":"Joshuaratau@gmail.com","phone":"0739395126","location":"","linkedin":"","portfolio":""},"career_summary":"Highly Skilled Full Stack Developer with 5 years of experience in both front-end and back-end web and mobile application development. Skilled in leveraging the latest technologies to build scalable, responsive, user-friendly applications. Demonstrated ability to work across the full Software development lifecycle, from ideation to deployment. Proficient in a multitude of languages and frameworks, and always eager to learn and adopt emerging trends. Passionate about delivering efficient, high-quality solutions that provides a seamless experience for end-users. Committed to collaborating with cross-functional teams to achieve project goals and exceed client expectations.","skills":[{"category":"Frontend","items":["WordPress","React","Angular","HTML5","CSS3","JavaScript (ES6+)"]},{"category":"Backend","items":["Node.js","Express.js","Laravel","ASP.NET (C#)"]}],"qualifications":[{"qualification":"Diploma In Information Technology","institution":"University Of South Africa","year":"2017"}],"certifications":[{"name":"Web And Mobile Development Certificate","provider":"Mlab","year":"2018"}],"training":[],"achievements":[],"languages":[],"interests":[],"references":[],"projects":[],"career_history":[{"job_title":"Full Stack Developer","company":"SA@Play","start_date":"October 2021","end_date":"October 2025","responsibilities":["Build and integrate secure RESTful APIs with structured JSON responses."]}],"additional_sections":[]}"""


def test_structured_json_import_uses_canonical_fields_and_skips_detected_blocks():
    client = TestClient(create_app())
    response = client.post("/api/upload-text", json={"text": json.dumps(STRUCTURED_JSON_SAMPLE)})
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["structured_source"] is True
    assert payload["import_mode"] == "structured_json"
    assert payload["structured_parse_strategy"] == "direct_json"
    assert payload["template_state"]["full_name"] == "Rudzani Mofokeng"
    assert payload["template_state"]["headline"] == "C# Developer"
    assert payload["template_state"]["email"] == "rudzani902@gmail.com"
    assert payload["profile"]["document_meta"]["structured_parse_strategy"] == "direct_json"
    assert payload["template_state"]["region"] == ""
    assert payload["template_state"]["location"] == "3999 Crestfish street, Ext 20, Sky city"
    assert payload["template_state"]["summary"] == STRUCTURED_JSON_SAMPLE["career_summary"]
    assert payload["detected_blocks"] == []
    assert payload["source_sections"] == []
    assert payload["text_blocks"] == []
    assert payload["template_state"]["career_history"].splitlines()[0] == "CestaSoft | C# Developer | Jan 2024 | Present"
    assert "Built internal tools" in payload["template_state"]["career_history"]
    assert payload["template_state"]["projects"] == "Internal Builder | Built recruiter workflow tooling"
    assert payload["template_state"]["references"] == "Jane Doe | Engineering Manager | jane@example.com"
    assert payload["template_state"]["languages"] == "English | Native"
    assert "Full Name is required before build can pass." not in payload["workflow_state"]["blocking_issues"]
    assert "Career History is required before build can pass." not in payload["workflow_state"]["blocking_issues"]
    assert payload["workflow_state"]["review_ready"] is True


def test_structured_json_import_preserves_empty_sections_without_leakage():
    client = TestClient(create_app())
    response = client.post("/api/upload-text", json={"text": json.dumps(STRUCTURED_JSON_SAMPLE)})
    assert response.status_code == 200, response.text
    payload = response.json()

    assert '"qualification": "Matric"' not in payload["template_state"]["projects"]
    assert '"skills": [' not in payload["template_state"]["additional_sections"]
    assert "{'name': 'Internal Builder'" not in payload["template_state"]["projects"]
    assert "{'name': 'Jane Doe'" not in payload["template_state"]["references"]
    assert '"name": "Jane Doe"' not in payload["preview_html"]


def test_invalid_json_paste_falls_back_to_raw_text_mode_safely():
    client = TestClient(create_app())
    raw_text = '{"identity":{"full_name":"Broken JSON"'
    response = client.post("/api/upload-text", json={"text": raw_text})
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload.get("import_mode") != "structured_json"
    assert payload.get("structured_source") is not True
    assert payload.get("structured_parse_strategy") is None
    assert payload["raw_text"] == raw_text


def test_non_json_cv_text_still_uses_raw_cv_text_mode():
    client = TestClient(create_app())
    raw_cv_text = """Joshua Ratau
Full Stack Developer
0739395126
Joshuaratau@gmail.com

Experience
SA@Play
Full Stack Developer
October 2021 - October 2025
Built and integrated secure RESTful APIs.
"""
    response = client.post("/api/upload-text", json={"text": raw_cv_text})
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload.get("import_mode") != "structured_json"
    assert payload.get("structured_source") is not True
    assert payload.get("structured_parse_strategy") is None
    assert payload["raw_text"].startswith("Joshua Ratau")
    assert isinstance(payload["text_blocks"], list)
    assert isinstance(payload["source_sections"], list)


def test_structured_json_import_repairs_literal_newlines_inside_string_values():
    client = TestClient(create_app())
    broken_json = """{"cestacv_version":1,"identity":{"full_name":"Joshua Ratau","headline":"Full Stack Developer","availability":"","region":"","email":"Joshuaratau@gmail.com
","phone":"0739395126","location":"","linkedin":"","portfolio":""},"career_summary":"Experienced full stack developer delivering reliable web and mobile applications across the full software lifecycle.","skills":[{"category":"Frontend","items":["React","Angular"]}],"qualifications":[{"qualification":"Diploma In Information Technology","institution":"University Of South Africa","year":"2017"}],"certifications":[{"name":"Web And Mobile Development Certificate","provider":"Mlab","year":"2018"}],"training":[],"achievements":[],"languages":[],"interests":[],"references":[],"projects":[],"career_history":[{"job_title":"Full Stack Developer","company":"SA@Play","start_date":"October 2021","end_date":"October 2025","responsibilities":["Built and maintained scalable web applications."]}],"additional_sections":[]}"""
    response = client.post("/api/upload-text", json={"text": broken_json})
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["structured_source"] is True
    assert payload["import_mode"] == "structured_json"
    assert payload["structured_parse_strategy"] == "repaired_json"
    assert payload["template_state"]["full_name"] == "Joshua Ratau"
    assert payload["template_state"]["email"] == "Joshuaratau@gmail.com"
    assert "Full Name is required before build can pass." not in payload["workflow_state"]["blocking_issues"]
    assert "Career History is required before build can pass." not in payload["workflow_state"]["blocking_issues"]
    assert payload["detected_blocks"] == []
    assert '"cestacv_version":1' not in payload["preview_html"]


def test_structured_json_import_extracts_json_from_polluted_ui_text_and_hydrates_joshua_case():
    client = TestClient(create_app())
    polluted_text = f"Upload File\nPaste Text\nPaste CV Text\n{JOSHUA_RATAU_JSON}"
    response = client.post("/api/upload-text", json={"text": polluted_text})
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["structured_source"] is True
    assert payload["import_mode"] == "structured_json"
    assert payload["structured_parse_strategy"] == "embedded_json"
    assert payload["detected_blocks"] == []
    assert payload["source_sections"] == []
    assert payload["text_blocks"] == []
    assert payload["template_state"]["full_name"] == "Joshua Ratau"
    assert payload["template_state"]["headline"] == "Full Stack Developer – Specializing in Web and Mobile Applications"
    assert payload["template_state"]["phone"] == "0739395126"
    assert payload["template_state"]["email"] == "Joshuaratau@gmail.com"
    assert payload["template_state"]["education"] == "Diploma In Information Technology | University Of South Africa | 2017"
    assert "Upload File" not in payload["template_state"]["full_name"]
    assert "Upload File" not in payload["preview_html"]
    assert '"cestacv_version":1' not in payload["preview_html"]
    assert '"headline"' not in payload["preview_html"]
    assert '"responsibilities"' not in payload["preview_html"]
    assert "Full Name is required before build can pass." not in payload["workflow_state"]["blocking_issues"]
    assert "Career History is required before build can pass." not in payload["workflow_state"]["blocking_issues"]


def test_structured_json_ignores_unrelated_embedded_json_and_selects_cestacv_schema_match():
    client = TestClient(create_app())
    polluted_text = f'{{"foo":"bar"}}\nUpload File\nPaste Text\n{JOSHUA_RATAU_JSON}'
    response = client.post("/api/upload-text", json={"text": polluted_text})
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["structured_source"] is True
    assert payload["import_mode"] == "structured_json"
    assert payload["structured_parse_strategy"] == "embedded_json"
    assert payload["template_state"]["full_name"] == "Joshua Ratau"
    assert payload["template_state"]["headline"] == "Full Stack Developer – Specializing in Web and Mobile Applications"
    assert payload["template_state"]["phone"] == "0739395126"
    assert payload["raw_text"].lstrip().startswith("{\n  \"cestacv_version\"")
    assert '"foo": "bar"' not in payload["raw_text"]
    assert '"foo":"bar"' not in payload["preview_html"]


def test_structured_json_preview_renders_clean_values_from_hydrated_state():
    client = TestClient(create_app())
    response = client.post("/api/upload-text", json={"text": json.dumps(STRUCTURED_JSON_SAMPLE)})
    assert response.status_code == 200, response.text
    payload = response.json()
    html = payload["preview_html"]

    assert "Rudzani Mofokeng" in html
    assert "C# Developer" in html
    assert "Built internal tools" in html
    assert "Internal Builder | Built recruiter workflow tooling" not in html
    assert '"headline": "C# Developer"' not in html
    assert '"category": "Technical Skills"' not in html
    assert '"location": "3999 Crestfish street, Ext 20, Sky city"' not in html


def test_structured_json_preview_uses_all_profile_experience_rows_when_flat_text_parser_is_partial():
    client = TestClient(create_app())
    payload = {
        "cestacv_version": 1,
        "identity": {
            "full_name": "THANDOKUHLE MNQOBI MNTAMBO",
            "headline": "Junior Data Analyst | Power BI | SQL | Excel | Reporting & Data Quality",
            "availability": "",
            "region": "",
            "email": "mnqobimntambo@gmail.com",
            "phone": "078 568 3003",
            "location": "Johannesburg, South Africa",
            "linkedin": "za.linkedin.com/in/thandokuhle-mntambo",
            "portfolio": "mnqobeey.netlify.app",
        },
        "career_summary": "Structured summary for preview validation across all imported experience rows.",
        "skills": [{"category": "Data & Analytics", "items": ["Power BI", "SQL"]}],
        "qualifications": [],
        "certifications": [],
        "training": [],
        "achievements": [],
        "languages": [],
        "interests": [],
        "references": [],
        "projects": [],
        "career_history": [
            {"job_title": "QA Intern", "company": "Cestasoft Solutions", "start_date": "Jun 2025", "end_date": "Present", "responsibilities": ["A"]},
            {"job_title": "Student Assistant", "company": "Nelson Mandela University", "start_date": "Feb 2022", "end_date": "Oct 2024", "responsibilities": ["B"]},
            {"job_title": "DigiReady Buddy", "company": "Nelson Mandela University", "start_date": "Feb 2022", "end_date": "Mar 2022", "responsibilities": ["C"]},
        ],
        "additional_sections": [],
    }
    response = client.post("/api/upload-text", json={"text": json.dumps(payload)})
    assert response.status_code == 200, response.text
    html = response.json()["preview_html"]

    assert "QA Intern" in html
    assert "Student Assistant" in html
    assert "DigiReady Buddy" in html
    assert html.count("experience-card") == 3


def test_structured_json_review_completion_passes_when_required_json_fields_exist():
    client = TestClient(create_app())
    upload = client.post("/api/upload-text", json={"text": json.dumps(STRUCTURED_JSON_SAMPLE)})
    assert upload.status_code == 200, upload.text
    uploaded = upload.json()

    review = client.post(
        f"/api/document/{uploaded['document_id']}/review-complete",
        json={"template_state": uploaded["template_state"]},
    )
    assert review.status_code == 200, review.text
    review_payload = review.json()

    assert review_payload["workflow_state"]["can_download"] is True
    assert review_payload["validated_export_json"]["identity"]["full_name"] == "Rudzani Mofokeng"
    assert review_payload["validated_export_json"]["identity"]["headline"] == "C# Developer"
    assert review_payload["validated_export_json"]["identity"]["region"] == ""
    assert review_payload["validated_export_json"]["career_summary"] == STRUCTURED_JSON_SAMPLE["career_summary"]
