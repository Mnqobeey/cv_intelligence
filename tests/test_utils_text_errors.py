from pathlib import Path

import pytest

from app.utils_text import extract_text


def test_missing_pdf_reports_file_not_found_not_generic_read_error():
    missing = Path(__file__).resolve().parents[1] / "uploads" / "missing-audit.pdf"
    with pytest.raises(FileNotFoundError, match="File not found:"):
        extract_text(missing)


def test_missing_docx_reports_file_not_found_not_generic_read_error():
    missing = Path(__file__).resolve().parents[1] / "uploads" / "missing-audit.docx"
    with pytest.raises(FileNotFoundError, match="File not found:"):
        extract_text(missing)
