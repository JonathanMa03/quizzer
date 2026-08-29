from __future__ import annotations

from pathlib import Path
from typing import Dict, Type

from .base import BaseParser
from .html_parser import HTMLParser
from .markdown_parser import MarkdownParser
from .pdf_parser import PDFParser
from .plain_text_parser import PlainTextParser
from .python_parser import PythonParser
from .r_parser import RParser
from .tex_parser import TeXParser


class DocumentParser:
    """Dispatch document parsing by file extension."""

    _parsers: Dict[str, Type[BaseParser]] = {
        ".pdf": PDFParser,
        ".txt": PlainTextParser,
        ".md": MarkdownParser,
        ".html": HTMLParser,
        ".htm": HTMLParser,
        ".tex": TeXParser,
        ".py": PythonParser,
        ".r": RParser,
        ".R": RParser,
    }

    @classmethod
    def parse(cls, file_path: str | Path) -> str:
        path = Path(file_path)
        suffix = path.suffix.lower()

        parser_cls = cls._parsers.get(suffix)
        if parser_cls is None:
            supported = ", ".join(sorted({f"{ext.upper()}" for ext in cls._parsers.keys()}))
            raise ValueError(f"Unsupported document type: {path.name}. Supported types: {supported}")

        parser = parser_cls()
        return parser.extract_text(path)


def parse_document(file_path: str | Path) -> str:
    return DocumentParser.parse(file_path)


def parse_supported_document(file_path: str | Path) -> str:
    return parse_document(file_path)
