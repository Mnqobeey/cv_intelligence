from __future__ import annotations

"""Text extraction and normalization helpers."""

from pathlib import Path
import re
from typing import List, Optional

from .pdf_compat import fitz
from docx import Document
from fastapi import HTTPException

from .constants import KNOWN_HEADING_TERMS, MONTH, SECTION_ALIASES

_PAGE_ARTIFACT_LINE_RE = re.compile(
    r"^(?:(?:curriculum vitae|resume|cv)\s*(?:[-|]\s*)?page\s+\d+(?:\s+of\s+\d+)?|page\s+\d+(?:\s+of\s+\d+)?)$",
    re.I,
)

# ---------------------------------------------------------------------------
def normalize_heading(text: str) -> str:
    text = text.strip().strip(":")
    text = re.sub(r"[_|]+", " ", text)
    text = re.sub(r"[^A-Za-z0-9/&+ -]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def map_heading_to_key(heading: str) -> Optional[str]:
    normalized = normalize_heading(heading)
    for key, aliases in SECTION_ALIASES.items():
        if normalized == key:
            return key
        if normalized in aliases:
            return key
        if any(normalized.startswith(alias) for alias in aliases if len(alias) >= 4):
            return key
    return None


def collapse_letter_spaced_text(text: str) -> str:
    fixed_lines: List[str] = []
    for line in text.splitlines():
        compact = line.strip()
        if not compact:
            fixed_lines.append("")
            continue
        alpha_chars = re.findall(r"[A-Za-z]", compact)
        spaces = compact.count(" ")
        looks_spaced = len(alpha_chars) >= 6 and spaces >= len(alpha_chars) * 0.55 and not re.search(r"\b[A-Za-z]{2,}\b", compact)
        if looks_spaced:
            repaired = re.sub(r"(?<=\b[A-Za-z])\s(?=[A-Za-z]\b)", "", compact)
            repaired = re.sub(r"\s{2,}", " ", repaired).strip()
            fixed_lines.append(repaired)
        else:
            fixed_lines.append(line.rstrip())
    return "\n".join(fixed_lines)


def split_inline_headings(text: str) -> str:
    patterns = []
    for alias in sorted(KNOWN_HEADING_TERMS, key=len, reverse=True):
        if len(alias) < 4:
            continue
        patterns.append(re.escape(alias))
    combined = "|".join(patterns)
    if not combined:
        return text
    return re.sub(rf"\s+(?=(?:{combined})\s*:)", "\n", text, flags=re.I)


def reconstruct_broken_lines(text: str) -> str:
    """Rejoin lines that were broken mid-sentence by PDF extraction."""
    lines = text.split("\n")
    rebuilt: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            rebuilt.append("")
            continue
        if rebuilt and rebuilt[-1] and not rebuilt[-1].endswith((".", ":", ";", "!", "?", "|")):
            prev = rebuilt[-1].rstrip()
            if stripped[0].islower() and len(stripped) > 3:
                rebuilt[-1] = prev + " " + stripped
                continue
        rebuilt.append(line.rstrip())
    return "\n".join(rebuilt)


def repair_wrapped_contact_lines(text: str) -> str:
    repaired = text or ""
    repaired = re.sub(
        r"(?im)\b([A-Z0-9._%+-]+@[A-Z0-9.-]+)\.\s*\n\s*([A-Z]{2,})\b",
        r"\1.\2",
        repaired,
    )
    repaired = re.sub(
        r"(?im)^((?:phone|mobile|telephone|tel|cell(?:phone)?)\s*:\s*\+?\d[\d\s()/-]{3,})\n\s*(\d[\d\s()/-]{2,}\d)\s*$",
        lambda match: f"{match.group(1).rstrip()} {match.group(2).lstrip()}",
        repaired,
    )
    return repaired


def strip_page_artifact_lines(text: str) -> str:
    cleaned_lines: List[str] = []
    for raw_line in (text or "").splitlines():
        stripped = raw_line.strip()
        if stripped and _PAGE_ARTIFACT_LINE_RE.match(stripped):
            continue
        cleaned_lines.append(raw_line)
    return "\n".join(cleaned_lines)


def clean_extracted_text(text: str) -> str:
    text = text.replace("\u200b", " ").replace("\xa0", " ")
    text = collapse_letter_spaced_text(text)
    text = split_inline_headings(text)
    text = reconstruct_broken_lines(text)
    text = repair_wrapped_contact_lines(text)
    text = strip_page_artifact_lines(text)
    text = re.sub(r"[\t\r]+", " ", text)
    text = re.sub(r"[ ]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Structured extraction helpers
# ---------------------------------------------------------------------------
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.document import Document as _DocxDocument


def _iter_docx_block_items(parent):
    """Yield paragraphs and tables in document order."""
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    if isinstance(parent, _DocxDocument):
        parent_elm = parent.element.body
    else:
        parent_elm = parent._tc
    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)



# ---------------------------------------------------------------------------
# Final PDF extraction stabilization for multi-column / sidebar CVs
# ---------------------------------------------------------------------------

def _pdf_block_text(block: tuple) -> str:
    text = (block[4] or "") if len(block) >= 5 else ""
    text = text.replace("\xa0", " ").strip()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _looks_like_multicolumn_page(blocks: List[tuple], page_width: float) -> bool:
    narrow = [b for b in blocks if (b[2] - b[0]) < page_width * 0.62]
    left = [b for b in narrow if b[0] < page_width * 0.33]
    right = [b for b in narrow if b[0] >= page_width * 0.33]
    return len(left) >= 3 and len(right) >= 3


def _ordered_pdf_blocks(page) -> List[tuple]:
    blocks = [b for b in (page.get_text("blocks") or []) if _pdf_block_text(b)]
    if not blocks:
        return []
    page_width = float(page.rect.width or 0)
    if not _looks_like_multicolumn_page(blocks, page_width):
        return sorted(blocks, key=lambda b: (round(b[1], 1), round(b[0], 1)))

    wide = [b for b in blocks if (b[2] - b[0]) >= page_width * 0.62]
    narrow = [b for b in blocks if b not in wide]
    left = [b for b in narrow if b[0] < page_width * 0.33]
    right = [b for b in narrow if b[0] >= page_width * 0.33]

    ordered: List[tuple] = []
    ordered.extend(sorted([b for b in wide if b[1] < 120], key=lambda b: (b[1], b[0])))
    ordered.extend(sorted(right, key=lambda b: (b[1], b[0])))
    ordered.extend(sorted([b for b in wide if 120 <= b[1] < 700], key=lambda b: (b[1], b[0])))
    ordered.extend(sorted(left, key=lambda b: (b[1], b[0])))
    ordered.extend(sorted([b for b in wide if b[1] >= 700], key=lambda b: (b[1], b[0])))
    return ordered


def _repair_pdf_line_breaks(text: str) -> str:
    lines = [ln.rstrip() for ln in text.splitlines()]
    repaired: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            repaired.append("")
            i += 1
            continue
        next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if next_line and (
            re.search(rf"\b(?:{MONTH})\b.*[–-]$", line, re.I)
            or (re.search(rf"\b(?:{MONTH})\b$", line, re.I) and re.search(r"^(?:19|20)\d{2}\b", next_line))
            or re.search(r"[|•]$", line)
        ):
            repaired.append(f"{line} {next_line}".strip())
            i += 2
            continue
        repaired.append(line)
        i += 1
    text = "\n".join(repaired)
    text = re.sub(r"(?m)^(PHONE:\s*[^\n]+)\s+EMAIL:\s*", r"\1\nEMAIL: ", text)
    return text


def extract_text_from_pdf(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    try:
        doc = fitz.open(str(path))
        pages: List[str] = []
        try:
            for page in doc:
                ordered = _ordered_pdf_blocks(page)
                if not ordered:
                    fallback = page.get_text("text") or ""
                    if fallback.strip():
                        pages.append(fallback.strip())
                    continue
                page_chunks: List[str] = []
                for block in ordered:
                    text = _pdf_block_text(block)
                    if text:
                        page_chunks.append(text)
                page_text = "\n\n".join(page_chunks).strip()
                page_text = _repair_pdf_line_breaks(page_text)
                if page_text:
                    pages.append(page_text)
        finally:
            doc.close()
        if pages:
            return "\n\n".join(pages).strip()
    except Exception:
        pass
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        pages = [(page.extract_text() or "") for page in reader.pages]
        return "\n\n".join(pages).strip()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to read PDF: {exc}")


# ---------------------------------------------------------------------------
# Final generic DOCX extraction refinements for textbox-heavy converted CVs
# ---------------------------------------------------------------------------
from zipfile import ZipFile
from xml.etree import ElementTree as ET

_W_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _repair_docx_ocr_artifacts(text: str) -> str:
    repaired = text or ""
    repaired = re.sub(r"\b[^\x00-\x7F](?=[A-Za-z]{3,}\b)", "J", repaired)
    repaired = re.sub(r"\bffi(?=[A-Za-z])", "N", repaired)
    repaired = re.sub(r"Iffi(?=[A-Z])", "IN", repaired)
    repaired = re.sub(r"\s+\|\s+", " | ", repaired)
    return repaired


def _extract_docx_textbox_lines(path: Path) -> List[str]:
    members = [r"word/document.xml", r"word/header\d+\.xml", r"word/footer\d+\.xml"]
    collected: List[str] = []
    try:
        with ZipFile(path) as archive:
            for member in archive.namelist():
                if not any(re.fullmatch(pattern, member) for pattern in members):
                    continue
                root = ET.fromstring(archive.read(member))
                for paragraph in root.findall(".//w:txbxContent//w:p", _W_NS):
                    text = "".join(node.text or "" for node in paragraph.findall(".//w:t", _W_NS))
                    text = _repair_docx_ocr_artifacts(re.sub(r"\s+", " ", text).strip())
                    if text:
                        collected.append(text)
    except Exception:
        return []
    return collected


def extract_text_from_docx(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    try:
        doc = Document(str(path))
        lines: List[str] = []
        textbox_lines = _extract_docx_textbox_lines(path)

        def append_line(text: str) -> None:
            cleaned = _repair_docx_ocr_artifacts((text or "").strip())
            if not cleaned:
                return
            if lines and lines[-1].casefold() == cleaned.casefold():
                return
            lines.append(cleaned)

        for text in textbox_lines:
            append_line(text)

        for block in _iter_docx_block_items(doc):
            if isinstance(block, Paragraph):
                append_line(block.text)
            else:
                for row in block.rows:
                    cells = [_repair_docx_ocr_artifacts(re.sub(r"\s+", " ", cell.text or "").strip()) for cell in row.cells]
                    cells = [cell for cell in cells if cell]
                    if cells:
                        append_line(" | ".join(cells))
                lines.append("")
        return "\n".join(lines).strip()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to read DOCX: {exc}")


def extract_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return clean_extracted_text(extract_text_from_pdf(path))
    if suffix == ".docx":
        return clean_extracted_text(extract_text_from_docx(path))
    if suffix == ".doc":
        raise HTTPException(status_code=400, detail="Legacy .doc format is not supported. Please convert to .docx first.")
    if suffix in {".txt", ".md"}:
        return clean_extracted_text(path.read_text(encoding="utf-8", errors="ignore"))
    raise HTTPException(status_code=400, detail="Unsupported file type. Use PDF, DOCX, TXT, or MD.")
