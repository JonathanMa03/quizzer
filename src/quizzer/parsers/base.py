from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class BaseParser(ABC):
    """Base interface for format-specific document parsers."""

    file_extensions: tuple[str, ...] = ()

    @abstractmethod
    def extract_text(self, file_path: str | Path) -> str:
        """Return plain-text content from the given document."""
        raise NotImplementedError
