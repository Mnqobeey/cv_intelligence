from fastapi.testclient import TestClient

from app.main import create_app
from app.constants import TEMPLATE_COPY, FINAL_OUTPUT_TEMPLATE


def test_template_copy_alias_points_to_final_template():
    assert TEMPLATE_COPY == FINAL_OUTPUT_TEMPLATE


def test_preview_uses_inline_download_button_and_no_legacy_download_bar():
    app = create_app()
    client = TestClient(app)
    response = client.get('/')
    assert response.status_code == 200
    html = response.text
    assert 'id="downloadPreviewBtn"' in html
    assert 'id="downloadBar"' not in html
    assert 'id="downloadBarBtn"' not in html
