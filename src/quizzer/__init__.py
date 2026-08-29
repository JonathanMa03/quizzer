"""Quizzer package scaffold."""

__all__ = ["build_blueprint", "collect_input_documents", "generate_quizzes", "parse_document"]

from .blueprint import build_blueprint
from .generator import generate_quizzes
from .input_loader import collect_input_documents
from .parsers import parse_document

__version__ = "0.1.0"
