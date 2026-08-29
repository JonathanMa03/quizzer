from __future__ import annotations

from pathlib import Path

from .base import BaseParser


class MarkdownParser(BaseParser):
    file_extensions = (".md",)

    def extract_text(self, file_path: str | Path) -> str:
        return Path(file_path).read_text(encoding="utf-8")
