"""Quizzer package scaffold."""

__all__ = [
    "build_blueprint",
    "collect_input_documents",
    "generate_quizzes",
    "generate_quizzes_from_files",
    "parse_document",
]

from .blueprint import build_blueprint
from .generator import generate_quizzes
from .input_loader import collect_input_documents
from .notebook import generate_quizzes_from_files
from .parsers import parse_document

__version__ = "0.1.0"
