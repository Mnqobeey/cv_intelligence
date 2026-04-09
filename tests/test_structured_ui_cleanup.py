import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def test_structured_preview_shows_location_separately_from_region():
    client = TestClient(create_app())
    payload = {
        "cestacv_version": 1,
        "identity": {
            "full_name": "Rudzani Mofokeng",
            "headline": "C# Developer",
            "availability": "",
            "region": "",
            "email": "rudzani902@gmail.com",
            "phone": "0623626109",
            "location": "3999 Crestfish street, Ext 20, Sky city",
            "linkedin": "",
            "portfolio": "",
        },
        "career_summary": "Experienced C# developer.",
        "skills": [{"category": "Technical Skills", "items": ["C#"]}],
        "qualifications": [],
        "certifications": [],
        "training": [],
        "achievements": [],
        "languages": [],
        "interests": [],
        "references": [],
        "projects": [],
        "career_history": [],
        "additional_sections": [],
    }
    response = client.post('/api/upload-text', json={'text': json.dumps(payload)})
    assert response.status_code == 200, response.text
    html = response.json()['preview_html']
    assert '<div class=\'meta-label\'>Location</div>' in html
    assert '3999 Crestfish street, Ext 20, Sky city' in html
    assert '<div class=\'meta-label\'>Region</div>' not in html


def test_structured_workspace_has_hook_to_hide_detected_blocks_panel():
    template = Path('app/templates/index.html').read_text()
    js = Path('app/static/js/app.js').read_text()
    assert 'id="detectedBlocksWrap"' in template
    assert 'state.structuredSource ? \'none\' : \'\'' in js
