from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup

from .base import BaseParser


class HTMLParser(BaseParser):
    file_extensions = (".html", ".htm")

    def extract_text(self, file_path: str | Path) -> str:
        content = Path(file_path).read_text(encoding="utf-8")
        soup = BeautifulSoup(content, "html.parser")
        return soup.get_text(separator="\n")
