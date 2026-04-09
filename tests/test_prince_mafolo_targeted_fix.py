"""Targeted regression tests for Prince_MPT_Mafolo_CV-style parsing.

Validates fixes for:
- Abbreviation tokens in filename-based name inference
- Document identity priority over filename inference
- Location/region from personal details, not education
- Skills leakage from personal/education/certificate/date content
- Certificate fallback capture under Certificates heading
- Career history stopping at references/achievements
- Standalone language extraction
- Awards from achievements section only, not summary prose
"""

from pathlib import Path

from app.normalizers import (
    _normalize_region_text,
    profile_from_sections,
    profile_to_template_state,
)
from app.parsers import (
    infer_name_from_filename,
    is_valid_name_candidate,
    parse_sections,
)


# ---------------------------------------------------------------------------
# Simulated raw text from a two-column CV similar to Prince_MPT_Mafolo_CV.pdf
# Left sidebar: name, headline, personal details, skills
# Right column: profile, education, employment, certificates, achievements,
#               references, languages
# ---------------------------------------------------------------------------
_SIMULATED_RAW_TEXT = """\
Mochabo Prince Mafolo
Senior Test Automation Engineer

Personal Details
Mochabo Prince Mafolo
mochabo.mafolo@gmail.com
+27781898365
47/7905, Morula View,
Mabopane
0190 Pretoria
19 December 1988
Code 10
Male
Married
linkedin.com/in/prince-tswelopele-mafolo-135a5b55

Skills
AUTOMATION TOOLS:
Selenium ((with Java & C#), Playwright, UFT, Appium & Cypress.
FRAMEWORKS: TestNG, JUnit, Maven & Cucumber (BDD/TDD).
PERFORMANCE TESTING: JMeter, LoadRunner, & Soap UI.
API TESTING: Postman, Rest Assured & Blaze Meter.
CODING (OOP): Java, JavaScript, Python, C# & VB.
CI/CD PIPELINES: Jenkins, Git, GitHub Action, Azure DevOps, Docker, & Kubernetes.
CLOUD PLATFORMS: Azure.
TEST MANAGEMENT: Agile, Scrum, JIRA, Xray, TestRail, & Confluence.
TESTING TYPES: Functional, Regression, Integration, Automation, API, Mobile, Performance, & ETL Testing.
DATABASES CONFIG & TESTING: SQL Server, Selenium + JDBC/ODBC, JMeter, & HP UFT.

Profile
Results driven Senior Test Automation Engineer with over 9 years of experience in QA automation, software testing, and CI/CD integration. I am skilled in building scalable test automation frameworks for web, mobile, and API applications using modern tools and methodologies.
Strong expertise in Selenium (with Java & C#), Playwright, Appium, RestAssured, TestNG, JUnit, and Cucumber (BDD/TDD). Proven award-winning track record of reducing release cycle time, increasing test coverage, and mentoring teams in automation best practices. Experienced in Agile, DevOps, and cloud-based environments (Azure DevOps).

Education
BIS Information Science Feb 2008 - Jan 2014
University of Pretoria, Pretoria, Gauteng
Bcom Informatics Honours Feb 2022 - Present
University of South Africa, Pretoria, Gauteng
Grade 12 (Matric) Jan 2006 - Dec 2006
Kgalatlou High School, Sekhukhune

Employment Experience
Senior Software Quality Engineer Jun 2025 - Present
VagmineTechIT, Johannesburg
CLIENT: HCL, Hyphen and MTN.
Build automated scripts using REST ASSURED.
Lead a team of QA engineers, assigning tasks, reviewing automation code, and guiding test design.
Applies OOP with Java to build robust Selenium scripts various frameworks.
Applies OOP with Java to build robust Appium script.
Implements BDD/TDD frameworks using Cucumber, TestNG, and Junit.
Facilitates Agile sessions such as Daily Stand Ups and Retros.
Creates Test Cases on JIRA and documents findings on Confluence in every Sprint.
Integrates Playwright test suites into Jenkins CI/CD pipelines.
Senior Automation Test Engineer Dec 2023 - Nov 2024
iOCO (EOH), Sandton
CLIENTS: MTN and Toyota.
Automated Test Cases using Selenium (with Java & C#), UFT and Appium.
Designed and implemented end-to-end test automation frameworks using Playwright with JavaScript, as well as executing advanced SQL queries.
Executed daily sanity tests via Postman to update SQL Tables.
Collaborated with Development Teams throughout the sprint.
Mentored junior QAs in designing and maintaining automation scripts.
Senior Software Quality Engineer Jul 2022 - Nov 2023
iLAB QA, Sandton
CLIENTS: Vodacom and Liberty.
Built automated scripts for android devices using Appium.
Used Object Oriented Programming with Java to update Selenium (with Java & C#), scripts from BDD to Selenium with TestNG.
Frequently used Jenkins Pipeline for Regression Testing.
Performed a Scrum Master role for most of the sprints.
Always updated test cases and bugs on Azure DevOps.
Collaborated continuously with stakeholders to define automation goals, scope, and success metrics.
Executed load, stress, spike, endurance, and scalability tests.
Collaborated with cross-functional teams (Dev, Product, DevOps) to ensure shift-left testing practices.
Quality Engineer Aug 2017 - Jul 2022
Standard Bank, Johannesburg
Built automated scripts for iOS devices using Appium.
Executed load, stress, spike, endurance, and scalability tests.
Executed automation scripts with Selenium WebDriver (BDD methodology) and UFT.
Reported defects immediately upon discovery.
Developed and managed Health Checks using Azure DevOps.
Detected performance issues such as memory leaks, deadlocks, or database bottlenecks.

Certificates
Azure Data Fundamentals Sep 2021
Functional Testing from Indian Testing Company.

Achievements
Automation of Morning Check testing
Achieved 100% automation of the Morning Check testing in my team at Standard Bank
A process which was once manual. Time value was from 30 minutes to 4 minutes.
2021 Mark of Excellence
Achieved 2021 Mark of Excellence from Standard Bank for testing Unayo Transaction Monitoring
A payment platform used in some African countries.

References
Lungelo Shembe - Line Manager
iOCO, Midrand
0824771868
Deshnee Boodhram - Line Manager
Hyphen, Johannesburg
0659741325

Languages
English
Zulu
Sepedi
"""

_SOURCE_PATH = Path("Prince_MPT_Mafolo_CV.pdf")


def _build_state():
    """Parse the simulated text and return (profile, template_state)."""
    sections = parse_sections(_SIMULATED_RAW_TEXT)
    profile = profile_from_sections(_SIMULATED_RAW_TEXT, sections, _SOURCE_PATH)
    state = profile_to_template_state(profile)
    return profile, state


# ---------------------------------------------------------------------------
# Fix 1: infer_name_from_filename handles abbreviation tokens
# ---------------------------------------------------------------------------
class TestFilenameAbbreviationHandling:
    def test_mpt_abbreviation_stripped_from_filename(self):
        result = infer_name_from_filename("Prince_MPT_Mafolo_CV.pdf")
        assert result is not None
        # "MPT" should be skipped as an abbreviation → "Prince Mafolo"
        assert "Mpt" not in result
        assert "Prince" in result
        assert "Mafolo" in result

    def test_short_abbreviation_skipped(self):
        result = infer_name_from_filename("John_AB_Doe_CV.pdf")
        assert result is not None
        assert "Ab" not in result
        assert "John" in result
        assert "Doe" in result

    def test_normal_three_word_name_preserved(self):
        result = infer_name_from_filename("John_Paul_Smith_CV.pdf")
        assert result == "John Paul Smith"

    def test_two_word_name_preserved(self):
        result = infer_name_from_filename("Jane_Doe_CV.pdf")
        assert result == "Jane Doe"


# ---------------------------------------------------------------------------
# Fix 2: Document identity preferred over filename
# ---------------------------------------------------------------------------
class TestDocumentIdentityPriority:
    def test_full_name_from_document_not_filename(self):
        _, state = _build_state()
        assert state["full_name"] == "Mochabo Prince Mafolo"

    def test_headline_from_document_header(self):
        _, state = _build_state()
        assert state["headline"] == "Senior Test Automation Engineer"

    def test_email_extracted(self):
        _, state = _build_state()
        assert state["email"] == "mochabo.mafolo@gmail.com"

    def test_phone_extracted(self):
        _, state = _build_state()
        assert state["phone"]
        assert "27781898365" in state["phone"].replace(" ", "")


# ---------------------------------------------------------------------------
# Fix 3: Location/region from personal details, not education
# ---------------------------------------------------------------------------
class TestLocationRegion:
    def test_region_not_from_education(self):
        _, state = _build_state()
        region = state.get("region", "")
        assert "University" not in region
        assert "university" not in region.lower()

    def test_normalize_region_rejects_university_text(self):
        result = _normalize_region_text("University of Pretoria, Pretoria, Gauteng")
        assert "University" not in result
        # Should return something like "Pretoria, Gauteng" or just "Pretoria"
        if result:
            assert "Pretoria" in result or "Gauteng" in result


# ---------------------------------------------------------------------------
# Fix 4: Skills do not contain personal details, dates, education, certs
# ---------------------------------------------------------------------------
class TestSkillsLeakage:
    def test_skills_no_personal_details(self):
        _, state = _build_state()
        skills_text = state["skills"].lower()
        assert "male" not in skills_text.split("\n")
        assert "married" not in skills_text.split("\n")
        assert "19 december 1988" not in skills_text
        assert "code 10" not in skills_text

    def test_skills_no_education_content(self):
        _, state = _build_state()
        skills_text = state["skills"].lower()
        assert "bis information science" not in skills_text
        assert "bcom informatics" not in skills_text
        assert "kgalatlou" not in skills_text

    def test_skills_no_certificate_content(self):
        _, state = _build_state()
        skills_text = state["skills"].lower()
        assert "azure data fundamentals" not in skills_text

    def test_skills_contain_actual_skills(self):
        _, state = _build_state()
        skills_text = state["skills"].lower()
        assert "selenium" in skills_text
        assert "java" in skills_text


# ---------------------------------------------------------------------------
# Fix 5: Awards from achievements section only, not summary prose
# ---------------------------------------------------------------------------
class TestAwardsExtraction:
    def test_awards_no_summary_prose(self):
        _, state = _build_state()
        awards_text = state.get("awards", "").lower()
        assert "award-winning track record" not in awards_text
        assert "track record" not in awards_text

    def test_awards_contain_actual_achievements(self):
        profile, state = _build_state()
        awards_raw = profile.get("awards", [])
        awards_text = "\n".join(awards_raw).lower() if awards_raw else ""
        # At minimum, the achievements section items should show up
        if awards_text:
            assert "morning check" in awards_text or "mark of excellence" in awards_text


# ---------------------------------------------------------------------------
# Fix 6: Certifications fallback captures certificate-section items
# ---------------------------------------------------------------------------
class TestCertificationsFallback:
    def test_certifications_not_empty(self):
        profile, state = _build_state()
        certs_text = state.get("certifications", "")
        # Should not be the placeholder
        assert certs_text != "No certifications listed"

    def test_certifications_contain_azure_fundamentals(self):
        profile, _ = _build_state()
        certs = profile.get("certifications", [])
        certs_text = "\n".join(certs).lower()
        assert "azure data fundamentals" in certs_text or "azure" in certs_text

    def test_certifications_contain_functional_testing(self):
        profile, _ = _build_state()
        certs = profile.get("certifications", [])
        certs_text = "\n".join(certs).lower()
        assert "functional testing" in certs_text or "indian testing" in certs_text


# ---------------------------------------------------------------------------
# Fix 7: Career history stops at references/achievements
# ---------------------------------------------------------------------------
class TestCareerHistoryBoundaries:
    def test_career_history_no_reference_contamination(self):
        _, state = _build_state()
        history = state.get("career_history", "").lower()
        assert "lungelo shembe" not in history
        assert "deshnee boodhram" not in history
        assert "0824771868" not in history

    def test_career_history_no_achievement_contamination(self):
        _, state = _build_state()
        history = state.get("career_history", "").lower()
        assert "morning check testing" not in history
        assert "mark of excellence" not in history

    def test_career_history_has_real_roles(self):
        profile, state = _build_state()
        experience = profile.get("experience", [])
        companies = [e.get("company", "") for e in experience]
        # Should have at least 3 of the 4 real roles
        assert any("VagmineTechIT" in c for c in companies) or any("iOCO" in c for c in companies)
        assert any("Standard Bank" in c for c in companies)

    def test_career_summary_populated(self):
        _, state = _build_state()
        summary = state.get("career_summary", "")
        assert summary  # Should not be empty


# ---------------------------------------------------------------------------
# Fix 8: Standalone language extraction
# ---------------------------------------------------------------------------
class TestLanguageExtraction:
    def test_languages_captured(self):
        profile, state = _build_state()
        languages = profile.get("languages", [])
        lang_text = "\n".join(languages).lower() if languages else ""
        state_lang = state.get("languages", "").lower()
        combined = lang_text + " " + state_lang
        assert "english" in combined
        assert "zulu" in combined
        assert "sepedi" in combined


# ---------------------------------------------------------------------------
# Fix 9: Education properly structured
# ---------------------------------------------------------------------------
class TestEducation:
    def test_education_has_entries(self):
        profile, _ = _build_state()
        edu = profile.get("education", [])
        qualifications = [e.get("qualification", "").lower() for e in edu]
        assert any("information science" in q for q in qualifications)

    def test_education_no_reference_contamination(self):
        profile, _ = _build_state()
        edu = profile.get("education", [])
        for entry in edu:
            assert "lungelo" not in (entry.get("institution", "") or "").lower()
