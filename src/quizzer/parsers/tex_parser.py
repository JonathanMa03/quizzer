from __future__ import annotations

from pathlib import Path

from .base import BaseParser


class TeXParser(BaseParser):
    file_extensions = (".tex",)

    def extract_text(self, file_path: str | Path) -> str:
        return Path(file_path).read_text(encoding="utf-8")
