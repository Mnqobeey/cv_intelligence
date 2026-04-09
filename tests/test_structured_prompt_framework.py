from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def test_structuring_prompt_endpoint_exposes_recommended_prompt_framework():
    client = TestClient(create_app())
    response = client.get('/api/structuring-prompt')
    assert response.status_code == 200
    payload = response.json()

    assert payload['prompt_key'] == payload['recommended_prompt_key']
    assert payload['prompt_label'] == payload['recommended_prompt_label']
    assert payload['pre_paste_guidance'].startswith('Paste only valid raw JSON.')
    assert 'Strict JSON Repair / Cleanup' in payload['pre_paste_guidance']
    assert isinstance(payload['prompts'], list)
    assert len(payload['prompts']) >= 5
    assert payload['schema_json'] in payload['prompt']
    assert 'Return ONLY valid raw JSON.' in payload['prompt']
    assert 'Do NOT use markdown code fences.' in payload['prompt']
    assert 'Trim leading and trailing whitespace from every string value.' in payload['prompt']
    assert 'Do NOT insert literal line breaks inside JSON string values.' in payload['prompt']
    assert 'Treat placeholder tokens such as (LinkedIn_link), (Portfolio link), N/A, null, or undefined as missing values' in payload['prompt']
    assert 'If the source CV clearly contains a recruiter-facing professional title, populate identity.headline rather than leaving it blank.' in payload['prompt']
    assert 'ensure the output parses successfully with JSON.parse' in payload['prompt']
    assert 'Verify the first character of the final answer is {.' in payload['prompt']
    assert 'Verify the last character of the final answer is }.' in payload['prompt']
    assert "Verify identity.full_name is populated when the source CV contains the candidate's name." in payload['prompt']
    assert "If the draft violates any schema or formatting rule above, silently repair it before returning the answer." in payload['prompt']
    assert 'After this self-check, return ONLY the final JSON object.' in payload['prompt']


def test_structuring_prompt_endpoint_exposes_expected_prompt_variants():
    client = TestClient(create_app())
    response = client.get('/api/structuring-prompt')
    assert response.status_code == 200
    prompts = response.json()['prompts']

    prompt_map = {prompt['key']: prompt for prompt in prompts}
    assert {
        'raw_cv_to_json',
        'pasted_cv_text_to_json',
        'strict_json_repair',
        'structured_section_text_to_json',
        'recruiter_safe_normalization',
    }.issubset(prompt_map)
    assert prompt_map['raw_cv_to_json']['recommended'] is True
    assert 'Do NOT place pure education records in career_history.' in prompt_map['raw_cv_to_json']['prompt']
    assert 'Perform the extraction in two silent passes' in prompt_map['raw_cv_to_json']['prompt']
    assert 'Treat section headers as authoritative boundaries.' in prompt_map['structured_section_text_to_json']['prompt']
    assert 'Fix malformed JSON, trim strings, and remove literal line breaks inside string values.' in prompt_map['strict_json_repair']['prompt']


def test_prompt_framework_ui_files_include_variant_controls_and_copy_support():
    template = Path('app/templates/index.html').read_text()
    js = Path('app/static/js/app.js').read_text()

    assert 'id="promptPresetList"' in template
    assert 'id="promptGuidance"' in template
    assert 'renderStructuringPromptFramework' in js
    assert 'recommended_prompt_key' in js
    assert "navigator.clipboard.writeText(activePrompt.prompt || '')" in js
