import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from docx import Document

from app.constants import UPLOAD_DIR
from app.pdf_compat import fitz

collect_ignore_glob = ["pytest-cache-files-*", ".pytest_tmp", "_inspect_signoff"]


class LocalTmpPathFactory:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._counters: dict[str, int] = {}

    def mktemp(self, basename: str, numbered: bool = True) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", basename).strip("._") or "tmp"
        if not numbered:
            target = self.root / safe
            target.mkdir(parents=True, exist_ok=True)
            return target
        index = self._counters.get(safe, 0)
        while True:
            target = self.root / f"{safe}_{index}"
            index += 1
            if not target.exists():
                target.mkdir(parents=True, exist_ok=True)
                self._counters[safe] = index
                return target


def _write_pdf(path: Path, lines: list[str]) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    rect = fitz.Rect(36, 36, 559, 806)
    text = "\n".join(lines)
    page.insert_textbox(rect, text, fontsize=10.5, fontname="helv", lineheight=1.25)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    doc.save(path)
    doc.close()


def _write_docx(path: Path, lines: list[str]) -> None:
    doc = Document()
    for line in lines:
        doc.add_paragraph(line)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


def _ensure_missing_targeted_fixtures() -> None:
    fixtures: dict[str, tuple[str, list[str]]] = {
        "24bb9db5-6662-4de2-a0d1-dd47820c5fa2.pdf": (
            "pdf",
            [
                "Innocent Celimpilo Phiri",
                "Junior Software Tester",
                "Email: innocentmpilo1@gmail.com",
                "Phone: +27 64 707 0704",
                "LinkedIn: https://www.linkedin.com/in/innocent-celimpilo-phiri-632796279",
                "Address: 2 Diagonal Street Gauteng Midrand 1685",
                "",
                "Candidate Summary",
                "Detail-oriented Software Tester with hands-on experience in test automation, structured manual testing, and collaborative delivery across modern software teams.",
                "",
                "Skills",
                "Systems Networking",
                "Computer Literate (Proficiency in Microsoft Office)",
                "Mathematical and Computational thinking",
                "Java,Python,C++,C#,JavaScript,Php, SQL, HTML_5,CSS, XML",
                "",
                "Qualifications",
                "National Senior Certificate | Dannhauser Secondary School | 2020",
                "BSc Applied Mathematics & Computer Science | University Of Zululand | 2024",
                "",
                "Languages",
                "English",
                "IsiZulu",
                "",
                "Achievements",
                "Top Achiever",
                "",
                "Career History",
                "Cestasoft Solutions | Junior Software Tester | 2024 | 2025",
                "Designed and executed automated test scripts using Java + Selenium",
                "Developed structured manual test cases from system requirements",
                "Logged, tracked and verified defects using Jira",
                "Supported CI/CD pipeline processes alongside DevOps team",
                "Assisted with regression and release testing before deployments",
                "Worked in Agile/Scrum environment with developers and engineers",
            ],
        ),
        "6d7364d2-bc09-46d8-aeb4-8efdfaccd4c5.pdf": (
            "pdf",
            [
                "Lavina Jacobs",
                "Project Co-ordinator",
                "Availability: Immediately",
                "Gender: Female",
                "Nationality: South African",
                "",
                "Candidate Summary",
                "I am a highly experienced Project Coordinator with delivery experience across enterprise programmes including Old Mutual and complex stakeholder environments.",
                "",
                "Skills",
                "Project Resource Planning and Allocation",
                "Azure DevOps",
                "Project Meetings",
                "",
                "Qualifications",
                "Matric | Southern Suburbs Youth Academy | 2018",
                "",
                "Certifications",
                "Scrum Master Certified | Agile Enterprise Coach | 2023",
                "Certificate - Allaboutxpert | 2013",
                "",
                "Training",
                "2019 | Microsoft Digital Dashboards | Alton",
                "2023 | Managing Change | Udemy",
                "",
                "Career History",
                "Old Mutual (OMSFIN) | Senior Project Coordinator/Project Manager | June 2023 | June 2025",
                "Co-ordinated enterprise project delivery across multiple workstreams.",
                "Sanlam | Junior Project Manager | March 2020 | March 2022",
                "Supported project planning, status reporting, and stakeholder updates.",
                "Interfront S.O.C | Senior Project Administrator | January 2019 | December 2019",
                "Managed project administration and governance tracking.",
                "Vodacom | Senior Project Administrator | February 2018 | December 2018",
                "Supported project documentation and milestone tracking.",
                "City of Cape Town | Specialist Clerk - Project Administrator- Co-Ordinator | July 2015 | December 2017",
                "Delivered co-ordination support for city project initiatives.",
            ],
        ),
        "6e70d4bc-9b01-4700-acd3-190bb375e723.docx": (
            "docx",
            [
                "Lavina Jacobs",
                "Project Co-ordinator",
                "Availability: Immediately",
                "Gender: Female",
                "Nationality: South African",
                "",
                "Candidate Summary",
                "I am a highly experienced Project Coordinator with delivery exposure across enterprise programmes and strong stakeholder management capability.",
                "",
                "Qualifications",
                "Matric | Southern Suburbs Youth Academy",
                "",
                "Certifications",
                "Scrum Master Certified | Agile Enterprise Coach",
                "Certificate - Allaboutxpert",
            ],
        ),
        "fcd22d91-3baf-42a5-b10f-b06199029a11.pdf": (
            "pdf",
            [
                "Lindelwe Myeza",
                "COBOL SOFTWARE DEVELOPER",
                "",
                "Candidate Summary",
                "Currently my short-term objectives are to gain new skills while contributing effectively as a COBOL software developer.",
                "",
                "Skills",
                "Critical thinking",
                "Problem-solving",
                "Adaptability",
                "Self-learning",
                "Willingness to learn",
                "",
                "Career History",
                "FIRST NATIONAL BANK | COBOL SOFTWARE DEVELOPER | Feb 2024 | Present",
                "- Responsibilities: As a COBOL software developer, we work to maintain the bank’s legacy systems which are responsible for processing the millions of transactions going through the bank every second.",
                "QUANTIFY YOUR FUTURE | DATA SCIENCE INTERN | Jan 2022 | Feb 2022",
                "Responsibilities: Supported entry-level data science delivery.",
                "DES SECURITY | OFFICE ASSISTANT | Oct 2018 | Jul 2019",
                "Responsibilities: Supported office operations and admin coordination.",
                "THE BONGS INTERNET CAFÉ | ASSISTANT IT TECHNICIAN | May 2018 | Sep 2018",
                "Responsibilities: Assisted customers and maintained internet cafe systems.",
            ],
        ),
        "9213916c-303d-4a2e-94dd-d26efa1bc9c5.docx": (
            "docx",
            [
                "SANDISIWE VUTULA",
                "Senior Software Engineer",
                "Availability: Notice period not applicable / immediate",
                "Region: Johannesburg",
                "Relocation: Yes",
                "Nationality: South African",
                "",
                "Candidate Summary",
                "Senior Software Engineer with hands-on experience delivering enterprise software solutions across .NET, cloud engineering, and cross-functional product teams.",
                "",
                "Skills",
                "C#",
                ".NET Frameworks",
                "Azure DevOps",
                "React.js",
                "",
                "Qualifications",
                "National Diploma: Information Technology | Cape Peninsula University of Technology | Incomplete (2011 â€“ 2014)",
                "Senior Certificate (Grade 12 / Matric) | Mgomanzi Senior Secondary School | 2009",
                "",
                "Training",
                "Software Development Bootcamp | EOH | 2014 (3 months)",
                "LinkedIn (2023 â€“ 2024)",
                "",
                "Languages",
                "English",
                "",
                "Awards",
                "After completing the 3-month software development bootcamp I transitioned into software development delivery.",
                "",
                "Career History",
                "DigiOutsource Services | Senior Software Engineer | Mar 2025 | Aug 2025",
                "Led engineering delivery for product enhancements.",
                "BET Software (Hollywood Bets) | Senior Software Developer (Withdrawals Team) | Jun 2024 | Dec 2024",
                "Delivered withdrawal-team software solutions.",
                "E4 Strategic | Software Engineer | Mar 2023 | Feb 2024",
                "Built enterprise integrations and services.",
                "Life Healthcare Group (via CyberPro Consulting) | .NET Developer | Jul 2022 | Feb 2023",
                "Delivered .NET development across healthcare platforms.",
                "MiX Telematics (via Immersant Data Solutions) | Software Developer | Sep 2020 | Jun 2022",
                "Implemented telematics product features.",
                "Avocado Chocolate | Software Developer | Feb 2020 | May 2020",
                "Developed internal web solutions.",
                "Capitec Bank | Developer | Jun 2019 | Dec 2019",
                "Supported banking software delivery.",
                "Unlimited Internet Play | Intermediate Software Engineer | Nov 2018 | Mar 2019",
                "Delivered software engineering tasks.",
                "Ipreo by IHS Markit | SQA Engineer | May 2018 | Oct 2018",
                "Supported software quality assurance execution.",
                "FinChoice | Software Developer | Jun 2016 | Apr 2018",
                "Built production software components.",
                "EOH Coastal | Junior Developer (.NET) | Oct 2014 | May 2016",
                "Contributed to .NET delivery work.",
            ],
        ),
    }

    for filename, (kind, lines) in fixtures.items():
        target = UPLOAD_DIR / filename
        if target.exists():
            continue
        normalized_lines = [
            line.replace("â€™", "'").replace("CAFÃ‰", "CAFE")
            for line in lines
        ]
        if kind == "pdf":
            _write_pdf(target, normalized_lines)
        else:
            _write_docx(target, normalized_lines)


# Materialize targeted binary fixtures as soon as pytest imports this conftest.
# Some tests reference uploads/ paths directly, so relying only on later fixture
# setup can leave the suite sensitive to bootstrap timing.
_ensure_missing_targeted_fixtures()


@pytest.fixture(scope="session")
def tmp_path_factory() -> LocalTmpPathFactory:
    root = UPLOAD_DIR / "_pytest_tmp"
    shutil.rmtree(root, ignore_errors=True)
    return LocalTmpPathFactory(root)


@pytest.fixture
def tmp_path(tmp_path_factory: LocalTmpPathFactory, request: pytest.FixtureRequest) -> Path:
    return tmp_path_factory.mktemp(request.node.name)


@pytest.fixture(scope="session", autouse=True)
def _prepare_test_environment(tmp_path_factory: LocalTmpPathFactory) -> None:
    _ensure_missing_targeted_fixtures()
