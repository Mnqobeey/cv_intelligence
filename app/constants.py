from __future__ import annotations

"""Application constants and shared configuration."""

import base64
import os
import re
import shutil
from pathlib import Path
from typing import Dict, List

BASE_DIR = Path(__file__).resolve().parent.parent
EPHEMERAL_ROOT = Path(os.getenv("EPHEMERAL_ROOT", "/tmp/cv_intelligence"))
DEFAULT_DATA_ROOT = EPHEMERAL_ROOT / "data" if os.getenv("PORT") else BASE_DIR / "data"
DEFAULT_UPLOAD_ROOT = EPHEMERAL_ROOT / "uploads" if os.getenv("PORT") else BASE_DIR / "uploads"
DEFAULT_EXPORT_ROOT = EPHEMERAL_ROOT / "exports" if os.getenv("PORT") else BASE_DIR / "exports"
DATA_ROOT = Path(os.getenv("DATA_DIR", str(DEFAULT_DATA_ROOT)))
UPLOAD_ROOT = Path(os.getenv("UPLOAD_DIR", str(DEFAULT_UPLOAD_ROOT)))
EXPORT_ROOT = Path(os.getenv("EXPORT_DIR", str(DEFAULT_EXPORT_ROOT)))

UPLOAD_DIR = UPLOAD_ROOT
EXPORT_DIR = EXPORT_ROOT
ASSET_DIR = BASE_DIR / "assets"
DATA_DIR = DATA_ROOT
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
ASSET_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024
FILE_RETENTION_HOURS = 24
PDF_PREVIEW_DPI_SCALE = 1.3
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(DATA_DIR / "documents.sqlite3")))

TEMPLATE_SOURCE = Path("/mnt/data/Template Cestasoft Profile .docx")
FINAL_OUTPUT_TEMPLATE = ASSET_DIR / "Template Cestasoft Profile.docx"
if TEMPLATE_SOURCE.exists() and not FINAL_OUTPUT_TEMPLATE.exists():
    shutil.copy2(TEMPLATE_SOURCE, FINAL_OUTPUT_TEMPLATE)
BASE_TEMPLATE_PATH = FINAL_OUTPUT_TEMPLATE
MASTER_TEMPLATE_PATH = FINAL_OUTPUT_TEMPLATE
TEMPLATE_COPY = FINAL_OUTPUT_TEMPLATE

LOGO_PATH = BASE_DIR / "app" / "static" / "img" / "cestasoft-logo.png"
LOGO_DATA_URI = ""
if LOGO_PATH.exists():
    LOGO_DATA_URI = "data:image/png;base64," + base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:\+?\d[\d\s()/-]{7,}\d)")
LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/[^\s]+", re.I)
URL_RE = re.compile(r"(?:https?://)?(?:www\.)?[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:/[^\s]*)?", re.I)
MONTH = r"(?:Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|August|Sep|Sept|September|Oct|October|Nov|November|Dec|December)"
YEAR = r"(?:19\d{2}|20\d{2})"
DATE_RANGE_RE = re.compile(
    rf"(?P<start>{MONTH}[\s./-]*{YEAR}|{YEAR}[\s./-]*{MONTH}|{YEAR})"
    rf"\s*(?:[-–—to]+|until)\s*"
    rf"(?P<end>{MONTH}[\s./-]*{YEAR}|{YEAR}[\s./-]*{MONTH}|{YEAR}|[Pp]resent|[Cc]urrent|[Oo]ngoing|[Tt]o [Dd]ate|[Nn]ow)",
    re.I,
)
SINGLE_DATE_RE = re.compile(rf"\b({MONTH}[\s./-]*{YEAR}|{YEAR}[\s./-]*{MONTH}|{YEAR})\b", re.I)
BULLET_RE = re.compile(r"^[\s]*[•●○▪▸►✦✧–—\-*#→⮞>]+\s*")
LABEL_VALUE_RE = re.compile(r"^([A-Za-z][A-Za-z /&+-]{1,40}?)\s*:\s*(.+)$")

# ---------------------------------------------------------------------------
# Section aliases — comprehensive mapping
# ---------------------------------------------------------------------------
SECTION_ALIASES: Dict[str, List[str]] = {
    "summary": [
        "summary", "professional summary", "profile summary", "objective", "about me", "career objective",
        "professional profile", "professional overview", "profile snapshot", "career dna", "executive summary",
        "candidate summary", "summary of qualifications", "career profile", "personal statement",
        "about", "profile", "introduction", "personal profile", "career summary overview",
        "brief overview", "professional bio",
    ],
    "experience": [
        "experience", "work experience", "employment", "employment experience", "career history", "professional experience",
        "employment history", "work history", "consulting experience", "engagement history",
        "previous experience", "career summary", "professional history", "projects delivered for client organizations",
        "career experience", "relevant experience", "employment record", "working experience", "working history",
        "professional engagements", "consulting engagements", "contract history",
        "roles held", "positions held",
    ],
    "education": [
        "education", "academic background", "qualifications", "academic qualifications",
        "education and training", "qualification", "education history", "academic history",
        "educational background", "academic record", "tertiary education", "education qualifications",
        "formal education", "studies", "academic achievements",
    ],
    "skills": [
        "skills", "technical skills", "core competencies", "competencies", "expertise", "key skills",
        "core skills", "technical expertise", "technology stack", "tech stack", "technology capability matrix",
        "capability landscape", "professional skills", "tools", "frameworks", "technologies", "skills matrix",
        "technology capability landscape", "technical competencies", "areas of expertise",
        "technical proficiency", "it skills", "computer skills", "software skills",
        "soft skills", "hard skills", "digital skills", "key technologies",
    ],
    "projects": [
        "projects", "project experience", "key projects", "portfolio", "project portfolio",
        "selected projects", "major projects", "project highlights", "relevant projects",
        "notable projects", "project history", "project work",
        "project deliveries",
    ],
    "certifications": [
        "certifications", "certificates", "licenses", "accreditations", "professional certifications",
        "certificate", "professional development", "continuous professional development",
        "credentials", "licenses and certifications",
        "certificates / training", "certificates and training", "certifications and training",
        "certifications / training", "certificates & training", "certifications & training",
    ],
    "training": [
        "training", "courses", "workshops", "short courses", "professional training",
        "training courses", "additional training", "skills development",
        "seminars", "learning and development",
    ],
    "languages": ["languages", "language proficiency", "language skills", "language competence"],
    "awards": ["awards", "achievements", "honors", "accomplishments", "achievements awards", "honours", "recognitions", "distinctions"],
    "volunteering": ["volunteering", "volunteer experience", "volunteerism", "community service", "community involvement", "social responsibility", "pro bono work"],
    "publications": ["publications", "publication", "research", "papers", "research papers"],
    "interests": ["interests", "hobbies", "hobbies and interests", "personal interests", "extracurricular activities"],
    "references": ["references", "referees", "reference", "professional references", "character references"],
    "responsibilities": ["responsibilities", "primary responsibilities", "duties", "key responsibilities"],
    "personal_details": [
        "personal details", "personal information", "contact details", "contact information",
        "bio data", "biodata", "biographical details", "candidate details", "candidate information",
    ],
}

# ---------------------------------------------------------------------------
# Field definitions — what the CV builder exposes
# ---------------------------------------------------------------------------
FIELD_DEFINITIONS = [
    {"key": "full_name", "label": "Full Name", "kind": "atomic", "group": "identity", "category": "Identity", "required_for_build": True},
    {"key": "headline", "label": "Professional Headline", "kind": "atomic", "group": "identity", "category": "Identity", "required_for_build": True},
    {"key": "availability", "label": "Availability", "kind": "atomic", "group": "identity", "category": "Identity"},
    {"key": "region", "label": "Region", "kind": "atomic", "group": "identity", "category": "Identity"},
    {"key": "email", "label": "Email", "kind": "atomic", "group": "identity", "category": "Identity"},
    {"key": "phone", "label": "Phone", "kind": "atomic", "group": "identity", "category": "Identity"},
    {"key": "location", "label": "Location", "kind": "atomic", "group": "identity", "category": "Identity"},
    {"key": "linkedin", "label": "LinkedIn", "kind": "atomic", "group": "identity", "category": "Identity"},
    {"key": "portfolio", "label": "Portfolio / Website", "kind": "atomic", "group": "identity", "category": "Identity"},
    {"key": "summary", "label": "Career Summary", "kind": "rich", "group": "core", "category": "Core Profile", "required_for_build": True},
    {"key": "skills", "label": "Skills", "kind": "rich", "group": "core", "category": "Core Profile", "required_for_build": True},
    {"key": "education", "label": "Qualifications", "kind": "rich", "group": "core", "category": "Core Profile", "required_for_build": True},
    {"key": "certifications", "label": "Certifications", "kind": "rich", "group": "core", "category": "Core Profile", "required_for_build": False},
    {"key": "training", "label": "Training & Courses", "kind": "rich", "group": "core", "category": "Core Profile"},
    {"key": "career_history", "label": "Career History", "kind": "rich", "group": "experience", "category": "Experience", "required_for_build": True},
    {"key": "projects", "label": "Projects", "kind": "rich", "group": "experience", "category": "Experience"},
    {"key": "volunteering", "label": "Volunteering", "kind": "rich", "group": "experience", "category": "Experience"},
    {"key": "publications", "label": "Publications", "kind": "rich", "group": "experience", "category": "Experience"},
    {"key": "languages", "label": "Languages", "kind": "rich", "group": "capabilities", "category": "Capabilities"},
    {"key": "awards", "label": "Awards", "kind": "rich", "group": "capabilities", "category": "Capabilities"},
    {"key": "interests", "label": "Interests", "kind": "rich", "group": "capabilities", "category": "Capabilities"},
    {"key": "references", "label": "References", "kind": "rich", "group": "closing", "category": "Closing"},
    {"key": "additional_sections", "label": "Additional Information", "kind": "rich", "group": "closing", "category": "Closing"},
]
FIELD_MAP = {f["key"]: f for f in FIELD_DEFINITIONS}
KNOWN_HEADING_TERMS = {re.sub(r"\s+", " ", alias.strip().lower()) for aliases in SECTION_ALIASES.values() for alias in aliases} | set(SECTION_ALIASES.keys())

GENERIC_UPPER_RE = re.compile(r"^[A-Z][A-Z0-9/&+,'() .-]{2,80}$")
LABEL_ONLY_TERMS = {
    "email", "cell no", "cellphone", "phone", "mobile", "location", "address",
    "employer", "occupation", "role", "duration", "period employed", "date of birth",
    "marital status", "nationality", "gender", "race", "id number", "company",
    "company name", "position", "job title", "contract type", "notice period",
    "salary", "current salary", "expected salary", "date", "name", "surname",
    "first name", "last name", "tel", "telephone", "cell", "fax",
    "certificate",
    "drivers license", "work permit", "citizenship", "visa status", "id no",
    "passport number", "home language", "contact number", "physical address",
    "residential address", "province", "country", "age",
}
ROLE_KEYWORDS = [
    "engineer", "developer", "analyst", "tester", "manager", "consultant", "intern", "specialist",
    "scientist", "representative", "architect", "administrator", "officer", "coordinator", "lead",
    "qa", "software", "data", "business development", "support", "project manager", "systems",
    "director", "head", "senior", "junior", "trainee", "associate", "principal", "technician",
    "designer", "strategist", "planner", "accountant", "auditor", "clerk",
    "advisor", "supervisor", "executive", "researcher", "lecturer", "facilitator",
    "scrum master", "product owner", "controller", "recruiter", "trainer",
]

SECTION_SIGNAL_TERMS: Dict[str, List[str]] = {
    "summary": ["profile", "summary", "objective", "about me", "professional", "career objective", "introduction"],
    "experience": ["experience", "responsibilities", "client", "project", "employer", "occupation", "worked at", "role", "position held"],
    "education": ["university", "college", "diploma", "degree", "bachelor", "honours", "certificate", "nqf", "matric", "grade 12",
                   "higher certificate", "advanced diploma", "national diploma", "btech", "masters", "phd", "doctorate",
                   "unisa", "wits", "uj", "tut", "dut", "uct", "ukzn", "nmmu", "up", "stellenbosch", "cput",
                   "mancosa", "north-west"],
    "skills": ["skills", "tools", "frameworks", "languages", "technologies", "stack", "competencies", "proficient", "proficiency"],
    "projects": ["project", "portfolio", "implementation", "built", "developed", "delivered"],
    "certifications": ["certified", "certificate", "certification", "accredited", "accreditation"],
    "training": ["training", "course", "workshop", "short course", "cpd", "professional development", "seminar", "bootcamp"],
    "languages": ["english", "afrikaans", "zulu", "xhosa", "sepedi", "sotho", "tswana", "swati", "tshivenda", "itsonga",
                   "isizulu", "isixhosa", "setswana", "sesotho", "siswati", "xitsonga", "tshivenda", "isindebele",
                   "french", "portuguese", "german", "mandarin", "spanish"],
    "volunteering": ["volunteer", "community", "ngo", "charity", "outreach", "pro bono"],
    "publications": ["publication", "journal", "conference", "paper", "research", "published"],
    "awards": ["award", "achievement", "won", "recognition", "honour", "honor", "distinction"],
    "references": ["reference", "referee", "available upon request", "on request"],
}

SA_QUALIFICATION_HINTS = {
    "honours": "NQF 8 Honours Degree",
    "honor": "NQF 8 Honours Degree",
    "btech": "Legacy BTech / Advanced Diploma equivalent",
    "national diploma": "NQF 6 National Diploma",
    "higher certificate": "NQF 5 Higher Certificate",
    "advanced diploma": "NQF 7 Advanced Diploma",
    "postgraduate diploma": "NQF 8 Postgraduate Diploma",
    "n6": "National N Diploma level",
    "n5": "National N5 Certificate",
    "n4": "National N4 Certificate",
    "n3": "National N3 Certificate",
    "n2": "National N2 Certificate",
    "n1": "National N1 Certificate",
    "nqf": "South African NQF terminology detected",
    "matric": "NQF 4 National Senior Certificate",
    "grade 12": "NQF 4 National Senior Certificate",
    "national senior certificate": "NQF 4 National Senior Certificate",
    "bachelor": "NQF 7 Bachelor's Degree",
    "bcom": "NQF 7 Bachelor of Commerce",
    "bsc": "NQF 7 Bachelor of Science",
    "masters": "NQF 9 Master's Degree",
    "doctoral": "NQF 10 Doctoral Degree",
    "phd": "NQF 10 Doctoral Degree",
}

SKILL_BUCKETS = {
    "languages_programming": ["python", "java", "c#", "c++", "javascript", "typescript", "sql", "r", "php", "kotlin", "html", "css", "go", "rust", "scala", "ruby", "swift", "dart", "perl", "vba", "bash", "powershell", "t-sql", "pl/sql", "cobol", "abap", "delphi", "groovy"],
    "frameworks": ["react", "angular", "vue", "spring", "django", "flask", "asp.net", "node", "fastapi", "selenium", "pytest", "bootstrap", "next.js", "nuxt", "express", "laravel", "rails", "flutter", "ionic", "tailwind", ".net", "blazor", "graphql", "spring boot", "react native", "hibernate"],
    "tools_platforms": ["jira", "confluence", "postman", "git", "github", "gitlab", "figma", "power bi", "tableau", "excel", "azure devops", "microsoft office", "vs code", "visual studio", "intellij", "slack", "trello", "notion", "sharepoint", "servicenow", "sap", "bitbucket", "sonarqube", "swagger", "grafana", "splunk"],
    "cloud_devops": ["aws", "azure", "gcp", "docker", "kubernetes", "jenkins", "terraform", "linux", "ci/cd", "ansible", "puppet", "chef", "openshift", "heroku", "vercel", "netlify", "cloudflare", "github actions", "gitlab ci", "lambda", "cloudformation"],
    "testing_qa": ["uft", "loadrunner", "jmeter", "api testing", "manual testing", "automation testing", "performance testing", "testng", "selenium", "cypress", "playwright", "jest", "mocha", "junit", "nunit", "cucumber", "karate", "appium", "soapui", "robot framework", "k6", "gatling"],
    "data_bi": ["snowflake", "pandas", "numpy", "etl", "data analysis", "machine learning", "power bi", "sql server", "reporting", "analytics", "bi", "databricks", "spark", "hadoop", "tableau", "qlik", "looker", "dax", "ssis", "ssrs", "ssas", "airflow", "kafka", "dbt", "metabase", "power automate"],
    "databases": ["mysql", "postgresql", "mongodb", "oracle", "sql server", "redis", "elasticsearch", "dynamodb", "cosmos db", "firebase", "sqlite", "cassandra", "neo4j", "mariadb"],
    "methodologies": ["agile", "scrum", "kanban", "waterfall", "devops", "itil", "prince2", "safe", "lean", "six sigma", "togaf", "cobit", "tdd", "bdd"],
}
