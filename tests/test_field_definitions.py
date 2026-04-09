from app.constants import FIELD_DEFINITIONS


def test_profile_workflow_exposes_only_one_career_summary_field():
    career_summary_fields = [field for field in FIELD_DEFINITIONS if field["label"] == "Career Summary"]

    assert len(career_summary_fields) == 1
    assert career_summary_fields[0]["key"] == "summary"
    assert career_summary_fields[0]["category"] == "Core Profile"
    assert not any(
        field["category"] == "Experience" and field["label"] == "Career Summary"
        for field in FIELD_DEFINITIONS
    )
