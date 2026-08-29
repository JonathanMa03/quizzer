from __future__ import annotations

from pathlib import Path
from typing import Dict, List

SUPPORTED_INPUT_SUBDIRS = (
    "syllabus",
    "lecture_notes",
    "MLO",
    "course_topics",
)

SUPPORTED_FILE_EXTENSIONS = {
    ".pdf",
    ".txt",
    ".md",
    ".html",
    ".htm",
    ".tex",
    ".py",
    ".r",
}


def collect_input_documents(inputs_dir: str | Path) -> Dict[str, List[Path]]:
    """Collect supported course files from each configured inputs subdirectory."""
    root = Path(inputs_dir)
    collected: Dict[str, List[Path]] = {}

    for subdir in SUPPORTED_INPUT_SUBDIRS:
        folder = root / subdir
        if not folder.exists():
            collected[subdir] = []
            continue

        files = sorted(
            file_path
            for file_path in folder.iterdir()
            if file_path.is_file()
            and not file_path.name.startswith(".")
            and file_path.suffix.lower() in SUPPORTED_FILE_EXTENSIONS
        )
        collected[subdir] = files

    return collected
