from __future__ import annotations

"""Document source preview builders used by the review workspace."""

import html
from pathlib import Path
from typing import Any, Dict

from .pdf_compat import fitz
from docx import Document

from .constants import PDF_PREVIEW_DPI_SCALE, UPLOAD_DIR


def build_pasted_text_source_view(raw_text: str) -> Dict[str, Any]:
    """Build an html_document source view from raw pasted text (no file)."""
    paras = [html.escape(line.strip()) for line in raw_text.splitlines() if line.strip()]
    return {"type": "html_document", "html": "".join(f"<p>{p}</p>" for p in paras)}


def build_source_view(file_path: Path, document_id: str) -> Dict[str, Any]:
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return build_pdf_source_view(file_path, document_id)
    if suffix == ".docx":
        return build_docx_source_view(file_path)
    if suffix in {".txt", ".md"}:
        txt = file_path.read_text(encoding="utf-8", errors="ignore")
        paras = [html.escape(x.strip()) for x in txt.splitlines() if x.strip()]
        return {"type": "html_document", "html": "".join(f"<p>{p}</p>" for p in paras)}
    return {"type": "file_link", "url": f"/uploads/{file_path.name}"}


def build_pdf_source_view(file_path: Path, document_id: str) -> Dict[str, Any]:
    doc = fitz.open(str(file_path))
    pages = []
    for idx, page in enumerate(doc):
        pix = page.get_pixmap(matrix=fitz.Matrix(1.3, 1.3), alpha=False)
        img_name = f"{document_id}_page_{idx+1}.png"
        img_path = UPLOAD_DIR / img_name
        pix.save(str(img_path))
        pd = page.get_text("dict")
        spans = []
        span_id = 0
        for block in pd.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for sp in line.get("spans", []):
                    text = (sp.get("text") or "").strip()
                    if not text:
                        continue
                    x0, y0, x1, y1 = sp.get("bbox", [0,0,0,0])
                    spans.append({
                        "id": f"p{idx+1}s{span_id}",
                        "text": text,
                        "x": round(x0,2),
                        "y": round(y0,2),
                        "w": round(max(1, x1-x0),2),
                        "h": round(max(1, y1-y0),2),
                        "font_size": round(sp.get("size", 12),2),
                    })
                    span_id += 1
        pages.append({
            "page_number": idx+1,
            "width": round(page.rect.width,2),
            "height": round(page.rect.height,2),
            "image_url": f"/uploads/{img_name}",
            "spans": spans,
        })
    doc.close()
    return {"type": "pdf_pages", "pages": pages, "url": f"/uploads/{file_path.name}"}


def build_docx_source_view(file_path: Path) -> Dict[str, Any]:
    doc = Document(str(file_path))
    chunks = []
    for p in doc.paragraphs:
        txt = p.text.strip()
