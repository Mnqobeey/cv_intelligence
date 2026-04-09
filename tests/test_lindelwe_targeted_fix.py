from pathlib import Path

from app.docx_exporter import build_final_profile_payload
from app.normalizers import profile_from_sections, profile_to_template_state
from app.parsers import parse_sections
from app.utils_text import extract_text


BASE_DIR = Path(__file__).resolve().parents[1]
LINDELWE_PDF = BASE_DIR / "uploads" / "fcd22d91-3baf-42a5-b10f-b06199029a11.pdf"
LINDELWE_SOURCE_NAME = Path("Lindelwe Myeza Resume 2025.pdf")


def test_lindelwe_pdf_skills_certifications_and_experience_render_cleanly():
    raw_text = extract_text(LINDELWE_PDF)
    sections = parse_sections(raw_text)
    profile = profile_from_sections(raw_text, sections, LINDELWE_SOURCE_NAME)
    state = profile_to_template_state(profile)
    payload = build_final_profile_payload(state, profile)

    expected_skills = [
        "Critical thinking",
        "Problem-solving",
        "Adaptability",
        "Self-learning",
        "Willingness to learn",
    ]
    expected_experience_rows = [
        ("FIRST NATIONAL BANK", "COBOL SOFTWARE DEVELOPER", "Feb 2024", "Present"),
        ("QUANTIFY YOUR FUTURE", "DATA SCIENCE INTERN", "Jan 2022", "Feb 2022"),
        ("DES SECURITY", "OFFICE ASSISTANT", "Oct 2018", "Jul 2019"),
        ("THE BONGS INTERNET CAFÉ", "ASSISTANT IT TECHNICIAN", "May 2018", "Sep 2018"),
    ]

    assert state["full_name"] == "Lindelwe Myeza"
    assert state["headline"] == "COBOL SOFTWARE DEVELOPER"
    assert state["summary"].startswith("Currently my short-term objectives are to gain new skills")

    assert "Core Skills:" not in state["skills"]
    assert state["skills"].splitlines() == expected_skills

    assert state["certifications"] == "No certifications listed"
    assert "Certificate no.: 20245807" not in state["certifications"]

    assert [
        (entry["company"], entry["position"], entry["start_date"], entry["end_date"])
        for entry in profile["experience"]
    ] == expected_experience_rows

    assert state["career_summary"].splitlines() == [
        "COBOL SOFTWARE DEVELOPER - FIRST NATIONAL BANK (Feb 2024 – Present)",
        "DATA SCIENCE INTERN - QUANTIFY YOUR FUTURE (Jan 2022 – Feb 2022)",
        "OFFICE ASSISTANT - DES SECURITY (Oct 2018 – Jul 2019)",
        "ASSISTANT IT TECHNICIAN - THE BONGS INTERNET CAFÉ (May 2018 – Sep 2018)",
    ]

    assert "COBOL SOFTWARE DEVELOPER - FIRST NATIONAL BANK" not in state["career_history"]
    assert "DATA SCIENCE INTERN - QUANTIFY YOUR FUTURE" not in state["career_history"]
    assert "OFFICE ASSISTANT - DES SECURITY" not in state["career_history"]
    assert "ASSISTANT IT TECHNICIAN - THE BONGS INTERNET CAFÉ" not in state["career_history"]
    assert "FIRST NATIONAL BANK | COBOL SOFTWARE DEVELOPER | Feb 2024 | Present" in state["career_history"]
    expected_responsibility_line = (
        "Responsibilities: As a COBOL software developer, we work to maintain the bank’s legacy systems "
        "which are responsible for processing the millions of transactions going through the bank every second."
    )
    fallback_responsibility_line = expected_responsibility_line.replace("bank’s", "bank's")
    extracted_fallback_responsibility_line = expected_responsibility_line.replace("bank’s", "bank?s")
    assert (
        expected_responsibility_line in state["career_history"]
        or fallback_responsibility_line in state["career_history"]
        or extracted_fallback_responsibility_line in state["career_history"]
    )
    responsibility_fragment = "As a COBOL software developer, we work to maintain the bank’s legacy systems"
    assert (
        state["career_history"].count(responsibility_fragment)
        or state["career_history"].count(responsibility_fragment.replace("bank’s", "bank's"))
        or state["career_history"].count(responsibility_fragment.replace("bank’s", "bank?s"))
    ) == 1
    assert "May 2018" in state["career_history"]
    assert "Sep 2018" in state["career_history"]

    assert [
        (row["company"], row["position"], row["start_date"], row["end_date"])
        for row in payload.career_summary
    ] == expected_experience_rows
    assert payload.career_history[0]["responsibilities"] in [
        [
            "As a COBOL software developer, we work to maintain the bank’s legacy systems which are responsible for processing the millions of transactions going through the bank every second."
        ],
        [
            "As a COBOL software developer, we work to maintain the bank's legacy systems which are responsible for processing the millions of transactions going through the bank every second."
        ],
        [
            "As a COBOL software developer, we work to maintain the bank?s legacy systems which are responsible for processing the millions of transactions going through the bank every second."
        ],
    ]
