"""Notebook-friendly entry points for quiz generation from explicit files."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .generator import generate_quizzes


_GROUP_ALIASES = {
    "syllabus": "syllabus",
    "lecture_notes": "lecture_notes",
    "lectures": "lecture_notes",
    "notes": "lecture_notes",
    "mlo": "MLO",
    "learning_outcomes": "MLO",
    "outcomes": "MLO",
    "course_topics": "course_topics",
    "topics": "course_topics",
}

PathValue = str | Path
NamedPaths = Mapping[str, PathValue]
InputGroup = PathValue | Sequence[PathValue] | NamedPaths


def _group_files(value: InputGroup) -> list[tuple[str | None, Path]]:
    if isinstance(value, Mapping):
        return [(str(name), Path(path).expanduser()) for name, path in value.items()]
    if isinstance(value, (str, Path)):
        return [(None, Path(value).expanduser())]
    return [(None, Path(path).expanduser()) for path in value]


def _staged_filename(name: str | None, source: Path) -> str:
    if name is None:
        return source.name
    safe_name = Path(name).name
    if not safe_name:
        raise ValueError(f"Invalid empty input filename for {source}")
    if not Path(safe_name).suffix:
        safe_name += source.suffix
    return safe_name


def generate_quizzes_from_files(
    input_files: Mapping[str, InputGroup],
    output_dir: str | Path = "./outputs",
    *,
    num_versions: int = 1,
    num_questions: int = 10,
    question_type: str = "mixed",
    output_format: str = "markdown",
) -> dict[str, Any]:
    """Generate quizzes from explicit notebook-supplied files.

    ``input_files`` maps logical groups to paths. Supported groups are
    ``syllabus``, ``lecture_notes``, ``learning_outcomes``/``MLO``, and
    ``course_topics``. A group may contain one path, a sequence of paths, or a
    ``{filename: path}`` mapping when the staged filename should be explicit.
    Every supplied file is used; topic filtering is intentionally not part of
    this notebook API.
    """
    if not input_files:
        raise ValueError("input_files must contain at least one file")

    staged_manifest: dict[str, list[str]] = {}
    with tempfile.TemporaryDirectory(prefix="quizzer-notebook-") as temp_dir:
        staged_root = Path(temp_dir)
        for raw_group, group_value in input_files.items():
            group = _GROUP_ALIASES.get(raw_group.lower())
            if group is None:
                supported = ", ".join(sorted(_GROUP_ALIASES))
                raise ValueError(f"Unsupported input group '{raw_group}'. Choose from: {supported}")
            group_dir = staged_root / group
            group_dir.mkdir(parents=True, exist_ok=True)
            staged_manifest.setdefault(group, [])

            for explicit_name, source in _group_files(group_value):
                if not source.is_file():
                    raise FileNotFoundError(f"Notebook input file does not exist: {source}")
                filename = _staged_filename(explicit_name, source)
                destination = group_dir / filename
                if destination.exists():
                    raise ValueError(f"Duplicate notebook input filename in {group}: {filename}")
                shutil.copy2(source, destination)
                staged_manifest[group].append(str(source.resolve()))

        manifest = generate_quizzes(
            input_dir=staged_root,
            output_dir=output_dir,
            num_versions=num_versions,
            num_questions=num_questions,
            question_type=question_type,
            output_format=output_format,
            topics=None,
            source_description="Notebook-supplied files",
        )
    manifest["input_files"] = staged_manifest
    return manifest
