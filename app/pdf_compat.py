from __future__ import annotations

"""PyMuPDF compatibility helpers.

Runtime environments sometimes expose the package as ``fitz`` and IDEs may only
resolve the distribution name ``pymupdf``. This module gives the project a
single stable import path.
"""

from typing import Any

try:  # pragma: no cover - exercised indirectly by consumers
    import pymupdf as _fitz
except Exception:  # pragma: no cover
    import fitz as _fitz  # pyright: ignore[reportMissingImports]

fitz: Any = _fitz

__all__ = ["fitz"]
