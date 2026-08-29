from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from .base import BaseParser


class PDFParser(BaseParser):
    file_extensions = (".pdf",)

    def extract_text(self, file_path: str | Path) -> str:
        reader = PdfReader(str(file_path))
        pages = []
        for page in reader.pages:
            extracted = page.extract_text() or ""
            pages.append(extracted)
        return "\n".join(pages)
