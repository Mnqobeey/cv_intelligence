import json

from fastapi.testclient import TestClient

from app.main import create_app


STRUCTURED_CV = {
    "cestacv_version": 1,
    "identity": {
        "full_name": "Lerato Mokoena",
        "headline": "Senior Software Developer",
        "availability": "Immediate",
        "region": "Gauteng",
        "email": "lerato@example.com",
        "phone": "+27 82 555 1234",
        "location": "Johannesburg, South Africa",
        "linkedin": "https://www.linkedin.com/in/lerato",
        "portfolio": "https://www.lerato.dev",
    },
    "career_summary": "Results-driven Senior Software Developer with extensive experience building scalable web applications, improving delivery quality, and mentoring teams across complex enterprise environments.",
    "skills": [{"category": "Programming Languages", "items": ["Python", "JavaScript"]}],
    "qualifications": [],
    "certifications": [{"name": "AWS Certified Developer", "provider": "AWS", "year": "2024"}],
    "training": ["Advanced REST API Design"],
    "achievements": ["Reduced processing time by 40%"],
    "languages": ["English"],
    "interests": ["Open-source software"],
    "references": ["Available on request"],
    "projects": ["Recruiter dashboard"],
    "career_history": [
        {
            "job_title": "Senior Software Developer",
            "company": "BrightPath Technologies",
            "start_date": "March 2022",
            "end_date": "Present",
            "responsibilities": ["Design backend services", "Mentor junior developers"],
        }
    ],
    "additional_sections": [{"title": "Driver's Licence", "content": "Code B"}],
}


def test_structuring_prompt_endpoint_exposes_prompt_and_schema():
    client = TestClient(create_app())
    response = client.get('/api/structuring-prompt')
    assert response.status_code == 200
    payload = response.json()
    assert payload['prompt_key'] == payload['recommended_prompt_key']
    assert 'Return ONLY valid raw JSON.' in payload['prompt']
    assert 'Do NOT use markdown code fences.' in payload['prompt']
    assert 'ensure the output parses successfully with JSON.parse' in payload['prompt']
    assert 'Self-Check Before Returning' in payload['prompt']
    assert payload['schema_example']['identity']['full_name'] == ''


def test_structured_json_ingest_bypasses_free_text_parser_and_returns_recommendations():
    client = TestClient(create_app())
    response = client.post('/api/upload-text', json={'text': json.dumps(STRUCTURED_CV)})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['structured_source'] is True
    assert payload['template_state']['full_name'] == 'Lerato Mokoena'
    assert 'Senior Software Developer' in payload['template_state']['career_history']
    assert isinstance(payload['recommendations'], list)
    assert 'education' in {item['target_key'] for item in payload['recommendations']}
    assert 'Qualifications are required before build can pass.' in payload['workflow_state']['warning_issues']
    assert payload['workflow_state']['blocking_issues'] == []


def test_structured_json_ingest_accepts_fenced_json_without_falling_back_to_free_text():
    client = TestClient(create_app())
    fenced = "```json\n" + json.dumps(STRUCTURED_CV, indent=2) + "\n```"
    response = client.post('/api/upload-text', json={'text': fenced})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['structured_source'] is True
    assert payload['template_state']['full_name'] == 'Lerato Mokoena'
    assert payload['detected_blocks'] == []
    assert payload['source_sections'] == []


def test_restore_field_reverts_latest_change_and_missing_qualification_no_longer_blocks_review():
    client = TestClient(create_app())
    uploaded = client.post('/api/upload-text', json={'text': json.dumps(STRUCTURED_CV)}).json()
    document_id = uploaded['document_id']

    update = client.post(f'/api/document/{document_id}/template', json={'headline': 'Principal Engineer'})
    assert update.status_code == 200, update.text
    assert 'headline' in update.json()['restorable_fields']

    restore = client.post(f'/api/document/{document_id}/restore-field', json={'target_key': 'headline'})
    assert restore.status_code == 200, restore.text
    restore_payload = restore.json()
    assert restore_payload['template_state']['headline'] == 'Senior Software Developer'

    review = client.post(f'/api/document/{document_id}/review-complete', json={'template_state': restore_payload['template_state']})
    assert review.status_code == 200, review.text
    review_payload = review.json()
    assert review_payload['workflow_state']['can_download'] is True
    assert 'Qualifications are required before build can pass.' in review_payload['workflow_state']['warning_issues']
