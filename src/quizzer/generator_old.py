from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from .input_loader import collect_input_documents
from .parsers import parse_document


SUPPORTED_QUESTION_TYPES = {"multiple", "open"}


def _normalize_text(value: str) -> str:
    return " ".join(value.replace("\r", "\n").split())


def _extract_material_summary(document_map: Dict[str, List[Path]]) -> str:
    segments: List[str] = []
    for subdir, files in sorted(document_map.items()):
        if not files:
            continue
        names = ", ".join(path.name for path in files)
        segments.append(f"{subdir}: {names}")
    return "; ".join(segments) if segments else "No course materials detected."


def _matches_topic_filters(text: str, topics: List[str]) -> bool:
    if not topics:
        return True

    lowered_text = text.lower()
    normalized_topics = [topic.strip().lower() for topic in topics if topic and topic.strip()]
    return any(topic in lowered_text for topic in normalized_topics)


def _coerce_topic_phrases(topics: List[str] | None) -> List[str]:
    if not topics:
        return []

    phrases: List[str] = []
    for topic in topics:
        if topic is None:
            continue
        for fragment in topic.split(","):
            fragment = fragment.strip()
            if fragment:
                phrases.append(fragment)
    return phrases


def _read_course_materials(input_dir: str | Path, topics: List[str] | None = None) -> Dict[str, str]:
    collected = collect_input_documents(input_dir)
    documents: Dict[str, str] = {}

    selected_topics = _coerce_topic_phrases(topics)
    for subdir, file_paths in collected.items():
        for file_path in file_paths:
            try:
                text = parse_document(file_path)
            except ValueError:
                continue
            normalized_text = _normalize_text(text)
            if not _matches_topic_filters(normalized_text, selected_topics):
                continue
            documents[file_path.name] = normalized_text

    return documents


def _extract_course_concepts(course_material: Dict[str, str]) -> List[str]:
    stop_words = {
        "the", "this", "that", "with", "from", "into", "using", "course", "lecture",
        "notes", "probability", "statistics", "ai", "and", "for", "are", "was", "were",
        "their", "there", "then", "than", "also", "other", "about", "such", "same",
        "when", "what", "which", "where", "how", "why", "have", "has", "had", "each",
        "more", "most", "some", "over", "under", "through", "these", "those", "between",
        "among", "after", "before", "does", "will", "would", "could", "should", "just",
        "like", "both", "very", "only", "not", "but", "can", "may", "used", "know",
        "known", "syllabus", "topic", "topics", "lecture_notes", "course_topics", "mlo",
        "assignment", "homework", "module", "reading", "readings", "document", "documents",
        "html", "markdown", "tex", "pdf", "txt", "python", "r", "file", "files", "chapter",
        "section", "sections", "example", "examples", "content", "materials", "material"
    }
    generic_tokens = {"syllabus", "lecture", "notes", "topic", "topics", "mlo", "html", "markdown", "tex", "pdf", "txt", "content", "material", "materials"}

    candidates: List[str] = []
    seen = set()

    for value in course_material.values():
        text = re.sub(r"<[^>]+>", " ", value)
        text = re.sub(r"[\[\](){}/\\]", " ", text)
        text = text.replace("_", " ").replace("-", " ")
        words = re.findall(r"[A-Za-z]+", text.lower())
        cleaned_words = [word for word in words if len(word) > 2 and word not in stop_words and word not in generic_tokens]

        for idx in range(len(cleaned_words) - 1):
            phrase = f"{cleaned_words[idx]} {cleaned_words[idx + 1]}"
            if phrase not in seen and phrase not in stop_words:
                seen.add(phrase)
                candidates.append(phrase)

        for word in cleaned_words:
            if word not in seen:
                seen.add(word)
                candidates.append(word)

    if not candidates:
        return ["core concepts", "main ideas", "key methods"]

    return candidates[:8]


def _render_question(index: int, prompt: str, question_type: str, correct_answer: str = "A", options: List[str] | None = None) -> str:
    if question_type == "open":
        return (
            f"{index}. {prompt}\n\n"
            "Answer in 1-3 paragraphs or a brief structured response.\n"
        )

    option_list = options or [
        "A. The course materials emphasize this idea as a central concept.",
        "B. This is a secondary idea rather than a primary concept.",
        "C. The materials present this as incompatible with the main topic.",
        "D. The provided materials do not justify this conclusion.",
    ]
    correct_line = f"Correct answer: {correct_answer}\n"
    return f"{index}. {prompt}\n\n" + "\n".join(option_list) + "\n\n" + correct_line


def _build_question_prompts(course_material: Dict[str, str], num_questions: int, topics: List[str] | None = None) -> List[str]:
    concepts = _extract_course_concepts(course_material)
    if not topics:
        topic_text = "the supplied course materials"
    else:
        topic_text = ", ".join(topics)

    prompts: List[str] = []
    for idx in range(num_questions):
        concept = concepts[idx % len(concepts)]
        prompts.append(f"Which statement best describes the role of {concept} in {topic_text}?")
    return prompts


def _render_quiz_content(quiz_number: int, material_summary: str, num_questions: int, question_type: str, output_format: str, topics: List[str] | None = None, course_material: Dict[str, str] | None = None) -> str:
    title = f"# Quiz {quiz_number}"
    intro = "\nThis quiz is based directly on the provided course materials and focuses on the main concepts and methods described there.\n"
    prompts = _build_question_prompts(course_material or {}, num_questions, topics)
    question_lines = []

    for idx, prompt in enumerate(prompts, start=1):
        concept = prompt.split("role of ", 1)[1].split(" in ", 1)[0]
        correct_answer = ["A", "B", "C", "D"][idx % 4]
        options = [
            f"A. {concept.title()} is a central idea in the course material and is emphasized as a core concept.",
            f"B. {concept.title()} is a secondary detail that supports a larger idea but is not the main focus.",
            f"C. {concept.title()} conflicts with the material's main explanation and should not be treated as central.",
            f"D. The course material does not provide enough evidence to evaluate {concept.title()} as a core concept.",
        ]
        question_lines.append(_render_question(idx, prompt, question_type, correct_answer, options))

    if output_format == "tex":
        rendered = "\n".join(f"\\textbf{{Question {idx}}}. {question.strip()}" for idx, question in enumerate(question_lines, start=1))
        return (
            "\\documentclass{article}\n"
            "\\usepackage[margin=1in]{geometry}\n"
            "\\begin{document}\n"
            f"\\section*{{Quiz {quiz_number}}}\n"
            f"{intro.replace(chr(10), chr(10) + '\\noindent ')}\n"
            f"{rendered}\n"
            "\\end{document}\n"
        )

    return title + intro + "\n" + "\n".join(question_lines)


def _render_answer_key(quiz_number: int, num_questions: int, output_format: str, answer_letters: List[str] | None = None) -> str:
    letters = answer_letters or ["A"] * num_questions
    lines = [
        "# Answer Key" if output_format == "markdown" else "\\section*{Answer Key}",
        "",
        *[
            f"{idx}. {letters[idx - 1]}" if output_format == "markdown" else f"\\textbf{{Question {idx}}}: {letters[idx - 1]}"
            for idx in range(1, num_questions + 1)
        ],
    ]
    return "\n".join(lines) + "\n"


def _output_extension(output_format: str) -> str:
    return ".md" if output_format == "markdown" else ".tex"


def _write_supplementary_files(output_dir: Path, quiz_number: int) -> List[str]:
    code_dir = output_dir / "supplementary" / "code"
    plot_dir = output_dir / "supplementary" / "plots"
    code_dir.mkdir(parents=True, exist_ok=True)
    plot_dir.mkdir(parents=True, exist_ok=True)

    code_path = code_dir / f"quiz_{quiz_number:02d}_support.py"
    code_path.write_text(
        "# Generated by Quizzer\n"
        "# This script can be adapted to create a plot or analysis artifact for the associated quiz.\n\n"
        "def build_supporting_example():\n"
        "    return {\n"
        "        'quiz_number': 1,\n"
        "        'purpose': 'Generate a supporting plot or analysis artifact for this question set.',\n"
        "    }\n\n"
        "if __name__ == '__main__':\n"
        "    print(build_supporting_example())\n",
        encoding="utf-8",
    )

    plot_path = plot_dir / f"quiz_{quiz_number:02d}_plot.md"
    plot_path.write_text(
        f"# Quiz {quiz_number} Supporting Plot\n\n"
        "This file is a placeholder for a generated visualization or figure description.\n",
        encoding="utf-8",
    )

    return [str(code_path.relative_to(output_dir.parent)), str(plot_path.relative_to(output_dir.parent))]


def generate_quizzes(
    input_dir: str | Path,
    output_dir: str | Path,
    num_versions: int = 4,
    num_questions: int = 10,
    question_type: str = "multiple",
    output_format: str = "markdown",
    topics: List[str] | None = None,
) -> Dict[str, Any]:
    if question_type not in SUPPORTED_QUESTION_TYPES:
        raise ValueError(f"Unsupported question type '{question_type}'. Choose from: {sorted(SUPPORTED_QUESTION_TYPES)}")

    selected_topics = _coerce_topic_phrases(topics)
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    for folder in ["quizzes", "answer_keys", "audit", "supplementary/code", "supplementary/plots"]:
        (output_path / folder).mkdir(parents=True, exist_ok=True)

    normalized_topics = _coerce_topic_phrases(topics)
    document_map = collect_input_documents(input_path)
    filtered_map = {}
    for subdir, files in document_map.items():
        included: List[Path] = []
        for path in files:
            try:
                text = parse_document(path)
            except ValueError:
                continue
            if normalized_topics and not _matches_topic_filters(_normalize_text(text), normalized_topics):
                continue
            included.append(path)
        filtered_map[subdir] = included

    material_summary = _extract_material_summary(filtered_map if normalized_topics else document_map)
    course_material = _read_course_materials(input_path, normalized_topics)

    quiz_files: List[str] = []
    key_files: List[str] = []
    supplementary_files: List[str] = []

    for version in range(1, num_versions + 1):
        answer_letters = ["A", "B", "C", "D"][0:num_questions]
        if num_questions > 4:
            answer_letters = ["A", "B", "C", "D"] * ((num_questions + 3) // 4)
            answer_letters = answer_letters[:num_questions]

        quiz_text = _render_quiz_content(
            version,
            material_summary or "the uploaded course materials",
            num_questions,
            question_type,
            output_format,
            selected_topics,
            course_material,
        )
        answer_key = _render_answer_key(version, num_questions, output_format, answer_letters)

        extension = _output_extension(output_format)
        quiz_filename = f"quiz_{version:02d}{extension}"
        key_filename = f"answer_key_{version:02d}{extension}"

        quiz_path = output_path / "quizzes" / quiz_filename
        key_path = output_path / "answer_keys" / key_filename
        quiz_path.write_text(quiz_text, encoding="utf-8")
        key_path.write_text(answer_key, encoding="utf-8")

        quiz_files.append(str(quiz_path.relative_to(output_path.parent)))
        key_files.append(str(key_path.relative_to(output_path.parent)))

        supplementary_files.extend(_write_supplementary_files(output_path, version))

    audit_path = output_path / "audit" / "audit_report.md"
    audit_path.write_text(
        "# Audit Report\n\n"
        f"- Generated versions: {num_versions}\n"
        f"- Questions per version: {num_questions}\n"
        f"- Question type: {question_type}\n"
        f"- Output format: {output_format}\n"
        f"- Course materials found: {len(course_material)}\n"
        f"- Material summary: {material_summary}\n",
        encoding="utf-8",
    )

    return {
        "quizzes": quiz_files,
        "answer_keys": key_files,
        "audit": [str(audit_path.relative_to(output_path.parent))],
        "supplementary": supplementary_files,
    }
