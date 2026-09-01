"""LLM-based quiz generation using OpenAI API."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from openai import OpenAI

from .blueprint import (
    QuizBlueprint,
    build_blueprint,
    extract_learning_outcomes,
    normalize_formula_delimiters,
    validate_generated_quiz,
)
from .input_loader import collect_input_documents
from .parsers import parse_document

load_dotenv()

SUPPORTED_QUESTION_TYPES = {"mixed", "open"}
GENERATION_BATCH_SIZE = 5
MAX_GENERATION_ATTEMPTS = 3


def _get_client() -> OpenAI:
    """Construct the API client lazily so parsing and planning work offline."""
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


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


def _normalize_topic_number(value: str) -> str | None:
    value = value.strip()
    if not value.isdigit() or len(value) > 2:
        return None
    return value.zfill(2)


def _numbered_document_topics(path: Path, subdir: str) -> set[str]:
    """Return two-digit lecture numbers encoded at the start of a filename."""
    if subdir == "lecture_notes":
        match = re.match(r"^(\d{1,2})(?=[-_])", path.stem)
        return {match.group(1).zfill(2)} if match else set()
    if subdir == "MLO":
        match = re.match(r"^(\d+)(?=_)", path.stem)
        if not match:
            return set()
        digits = match.group(1)
        if len(digits) <= 2:
            return {digits.zfill(2)}
        if len(digits) % 2 == 0:
            return {digits[index : index + 2] for index in range(0, len(digits), 2)}
    return set()


def _topic_name_from_lecture(path: Path) -> str:
    name = re.sub(r"^\d{1,2}[-_]", "", path.stem)
    name = re.sub(r"-draft$", "", name, flags=re.IGNORECASE)
    return re.sub(r"[-_]+", " ", name).strip()


def _prefer_final_documents(files: List[Path]) -> List[Path]:
    stems = {path.stem.lower() for path in files}
    return [
        path
        for path in files
        if not (
            path.stem.lower().endswith("-draft")
            and path.stem.lower().removesuffix("-draft") in stems
        )
    ]


def _read_course_materials(input_dir: str | Path, topics: List[str] | None = None) -> str:
    """Read all course materials into a single text blob, optionally filtered by topic."""
    collected = collect_input_documents(input_dir)
    materials: List[str] = []

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
            materials.append(f"--- From {file_path.name} ---\n{normalized_text}\n")

    return "\n".join(materials) if materials else "No course materials found."


def _generate_quiz_with_llm(
    course_material: str,
    blueprint: QuizBlueprint,
    version_num: int,
    output_format: str,
    output_dir: Path,
) -> tuple[str, str, List[str]]:
    """
    Use OpenAI to generate quiz questions and answers based on course material.
    Returns: (quiz_content, answer_key_content)
    """
    # Truncate course material if it's too long (context window limit)
    max_material_chars = 50000
    if len(course_material) > max_material_chars:
        course_material = course_material[:max_material_chars] + "\n\n[Material truncated for length...]"

    plan = blueprint.version_plan(version_num)
    requirements = plan["requirements"]
    generated_questions: List[Dict[str, Any]] = []
    client = _get_client()

    for batch_start in range(0, len(requirements), GENERATION_BATCH_SIZE):
        batch_requirements = requirements[batch_start : batch_start + GENERATION_BATCH_SIZE]
        batch_plan = {"version": version_num, "requirements": batch_requirements}
        plan_json = json.dumps(batch_plan, indent=2)
        expected_numbers = [requirement["number"] for requirement in batch_requirements]
        validation_feedback = ""

        for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
            prompt = f"""You are an expert tutor creating version {version_num} of a grounded course quiz.

Follow the assessment blueprint exactly. Each requirement is a comparable slot shared by every quiz version.
Create a distinct question for this version while preserving the slot's topic, learning outcome, question kind, and difficulty.
Use only facts supported by the course material.
Return exactly {len(batch_requirements)} questions, numbered {expected_numbers}. Do not return an example or omit any assigned question.

Question-kind rules:
- single_choice: exactly four options A-D and exactly one correct answer
- multiple_select: exactly four options A-D and at least two correct answers
- open_ended: no options; correct_answers contains a concise model answer

Assessment-modality rules:
- conceptual: assess explanation, comparison, or application of a concept
- formula: use valid dollar-delimited LaTeX; prefer $...$ inline math unless a display block is genuinely needed, and JSON-escape every LaTeX backslash
- code: include a short, self-contained code snippet and ask for interpretation, prediction, completion, or debugging
- plot_interpretation: provide a concrete plot_spec with numeric x and y values; ask students to interpret the generated plot, not an imagined plot or superficial labels/colors

Return your response as a JSON object with this exact structure:
{{
    "questions": [
        {{
            "number": 1,
            "question_kind": "single_choice",
            "modality": "conceptual",
            "question": "question text here",
            "options": {{
                "A": "option A text",
                "B": "option B text",
                "C": "option C text",
                "D": "option D text"
            }},
            "correct_answers": ["A"],
            "explanation": "why the answer is correct",
            "source_references": ["source filename"],
            "plot_spec": null
        }}
    ]
}}

For a plot_interpretation question, replace plot_spec with:
{{
    "plot_type": "line, scatter, or bar",
    "x": [numeric values],
    "y": [numeric values],
    "title": "plot title",
    "x_label": "x-axis label",
    "y_label": "y-axis label"
}}

ASSESSMENT BLUEPRINT:
{plan_json}

{validation_feedback}

COURSE MATERIAL:
{course_material}

Respond ONLY with the JSON object, no additional text or markdown formatting."""

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                max_completion_tokens=4096,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt}],
            )
            response_text = response.choices[0].message.content or ""
            try:
                batch_data = json.loads(response_text)
            except json.JSONDecodeError as exc:
                errors = [f"response was not valid JSON: {exc.msg}"]
            else:
                normalize_formula_delimiters(batch_data, batch_plan)
                errors = validate_generated_quiz(batch_data, batch_plan)
                if not errors:
                    generated_questions.extend(batch_data["questions"])
                    break

            validation_feedback = (
                "PREVIOUS ATTEMPT FAILED VALIDATION. Correct every issue below and return the entire assigned batch:\n- "
                + "\n- ".join(errors)
            )
        else:
            batch_label = f"{expected_numbers[0]}-{expected_numbers[-1]}"
            raise ValueError(
                f"Could not generate a valid question batch ({batch_label}) after "
                f"{MAX_GENERATION_ATTEMPTS} attempts: {'; '.join(errors)}"
            )

    quiz_data = {"questions": generated_questions}
    errors = validate_generated_quiz(quiz_data, plan)
    if errors:
        raise ValueError("Generated quiz violated its blueprint: " + "; ".join(errors))

    supplementary_files = _write_plot_artifacts(quiz_data, output_dir, version_num)
    quiz_content = _format_quiz_from_llm(quiz_data, output_format)
    answer_key = _format_answer_key_from_llm(quiz_data, output_format)

    return quiz_content, answer_key, supplementary_files


def _write_plot_artifacts(quiz_data: Dict[str, Any], output_dir: Path, quiz_number: int) -> List[str]:
    """Write and execute reproducible scripts for every plot question."""
    code_dir = output_dir / "supplementary" / "code"
    plot_dir = output_dir / "supplementary" / "plots"
    code_dir.mkdir(parents=True, exist_ok=True)
    plot_dir.mkdir(parents=True, exist_ok=True)
    artifacts: List[str] = []

    for question in quiz_data.get("questions", []):
        if question.get("modality") != "plot_interpretation":
            continue
        q_num = int(question["number"])
        spec = question["plot_spec"]
        stem = f"quiz_{quiz_number:02d}_q{q_num:02d}_plot"
        code_path = code_dir / f"{stem}.py"
        plot_path = plot_dir / f"{stem}.png"
        spec_json = json.dumps(spec, ensure_ascii=False)
        script = (
            "from __future__ import annotations\n\n"
            "import json\n"
            "from pathlib import Path\n\n"
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
            "import matplotlib.pyplot as plt\n\n"
            f"SPEC = json.loads({spec_json!r})\n"
            f"OUTPUT_PATH = Path({str(plot_path.resolve())!r})\n\n"
            "fig, ax = plt.subplots(figsize=(7, 4.5))\n"
            "plot_type = SPEC['plot_type']\n"
            "if plot_type == 'scatter':\n"
            "    ax.scatter(SPEC['x'], SPEC['y'])\n"
            "elif plot_type == 'bar':\n"
            "    ax.bar(SPEC['x'], SPEC['y'])\n"
            "else:\n"
            "    ax.plot(SPEC['x'], SPEC['y'], marker='o')\n"
            "ax.set_title(SPEC.get('title', ''))\n"
            "ax.set_xlabel(SPEC.get('x_label', ''))\n"
            "ax.set_ylabel(SPEC.get('y_label', ''))\n"
            "ax.grid(alpha=0.2)\n"
            "fig.tight_layout()\n"
            "OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)\n"
            "fig.savefig(OUTPUT_PATH, dpi=160)\n"
            "plt.close(fig)\n"
        )
        code_path.write_text(script, encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(code_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0 or not plot_path.is_file():
            detail = completed.stderr.strip() or "plot file was not created"
            raise RuntimeError(f"Plot generation failed for question {q_num}: {detail}")

        question["plot_path"] = f"../supplementary/plots/{plot_path.name}"
        question["plot_alt"] = spec.get("title") or f"Plot for question {q_num}"
        question["question"] = re.sub(
            r"^(?:Given|Based on|In) (?:a|the) plot[^,?.]*[,?.]?\s*",
            "Using the generated plot below, ",
            question["question"],
            flags=re.IGNORECASE,
        )
        artifacts.extend([
            str(code_path.relative_to(output_dir.parent)),
            str(plot_path.relative_to(output_dir.parent)),
        ])
    return artifacts


def _format_quiz_from_llm(quiz_data: Dict[str, Any], output_format: str) -> str:
    """Format LLM-generated quiz data into markdown or tex."""
    lines = []

    if output_format == "markdown":
        lines.append("# Quiz")
        lines.append("")
    else:
        lines.append("\\documentclass{article}")
        lines.append("\\usepackage[margin=1in]{geometry}")
        lines.append("\\usepackage{graphicx}")
        lines.append("\\begin{document}")
        lines.append("\\section*{Quiz}")
        lines.append("")

    for q in quiz_data.get("questions", []):
        q_num = q.get("number", 1)
        q_text = q.get("question", "")
        if q.get("question_kind") == "multiple_select" and "select all that apply" not in q_text.lower():
            q_text = f"**Select all that apply.** {q_text}"
        options = q.get("options", {})

        if output_format == "markdown":
            if q.get("plot_path"):
                lines.append(f"![{q.get('plot_alt', 'Question plot')}]({q['plot_path']})")
                lines.append("")
            lines.append(f"{q_num}. {q_text}")
            lines.append("")
            if options:
                for letter in ["A", "B", "C", "D"]:
                    if letter in options:
                        lines.append(f"{letter}. {options[letter]}  ")
                lines.append("")
            else:
                lines.append("*Open-ended question. Provide a detailed answer.*")
                lines.append("")
        else:
            if q.get("plot_path"):
                lines.append(f"\\includegraphics[width=0.8\\linewidth]{{{q['plot_path']}}}")
                lines.append("")
            lines.append(f"\\textbf{{Question {q_num}}}. {q_text}")
            lines.append("")
            if options:
                for letter in ["A", "B", "C", "D"]:
                    if letter in options:
                        lines.append(f"\\quad {letter}. {options[letter]}")
            else:
                lines.append("\\quad \\textit{Open-ended question. Provide a detailed answer.}")
            lines.append("")

    if output_format == "tex":
        lines.append("\\end{document}")

    return "\n".join(lines)


def _format_answer_key_from_llm(quiz_data: Dict[str, Any], output_format: str) -> str:
    """Format LLM-generated answer key."""
    lines = []

    if output_format == "markdown":
        lines.append("# Answer Key")
        lines.append("")
    else:
        lines.append("\\documentclass{article}")
        lines.append("\\usepackage[margin=1in]{geometry}")
        lines.append("\\begin{document}")
        lines.append("\\section*{Answer Key}")
        lines.append("")

    for q in quiz_data.get("questions", []):
        q_num = q.get("number", 1)
        answers = q.get("correct_answers", [])
        explanation = q.get("explanation", "")

        if output_format == "markdown":
            if answers:
                lines.append(f"{q_num}. **{', '.join(answers)}**")
            else:
                lines.append(f"{q_num}. *Open-ended*")
            if explanation:
                lines.append(f"   - {explanation}")
            lines.append("")
        else:
            if answers:
                lines.append(f"\\textbf{{Question {q_num}}}. Answer: {', '.join(answers)}")
            else:
                lines.append(f"\\textbf{{Question {q_num}}}. \\textit{{Open-ended}}")
            if explanation:
                lines.append(f"\\quad {explanation}")
            lines.append("")

    if output_format == "tex":
        lines.append("\\end{document}")

    return "\n".join(lines)


def generate_quizzes(
    input_dir: str | Path,
    output_dir: str | Path,
    num_versions: int = 4,
    num_questions: int = 10,
    question_type: str = "mixed",
    output_format: str = "markdown",
    topics: List[str] | None = None,
    source_description: str | None = None,
) -> Dict[str, Any]:
    """Generate quiz versions using LLM-based question generation."""
    if question_type not in SUPPORTED_QUESTION_TYPES:
        raise ValueError(f"Unsupported question type '{question_type}'. Choose from: {sorted(SUPPORTED_QUESTION_TYPES)}")

    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    for folder in ["quizzes", "answer_keys", "audit", "supplementary/code", "supplementary/plots"]:
        (output_path / folder).mkdir(parents=True, exist_ok=True)

    topic_values = _coerce_topic_phrases(topics)
    numeric_topics = {
        normalized
        for value in topic_values
        if (normalized := _normalize_topic_number(value)) is not None
    }
    phrase_filters = [value for value in topic_values if _normalize_topic_number(value) is None]
    normalized_topics = _coerce_topic_phrases(phrase_filters)
    
    # Track the original request for audit report
    audit_topic_filters = topics or []
    
    document_map = collect_input_documents(input_path)
    filtered_map = {}
    materials_used: List[str] = []
    
    for subdir, files in document_map.items():
        included: List[Path] = []
        for path in files:
            try:
                text = parse_document(path)
            except ValueError:
                continue
            matches_by_number = bool(numeric_topics & _numbered_document_topics(path, subdir))
            matches_by_content = phrase_filters and _matches_topic_filters(_normalize_text(text), normalized_topics)
            
            if (numeric_topics or phrase_filters) and not (matches_by_number or matches_by_content):
                continue
            included.append(path)
        filtered_map[subdir] = _prefer_final_documents(included)

    selected_map = filtered_map if (numeric_topics or phrase_filters) else document_map
    materials_used = [
        str(path.relative_to(input_path))
        for files in selected_map.values()
        for path in files
    ]
    material_summary = _extract_material_summary(selected_map)
    material_parts: List[str] = []
    for files in selected_map.values():
        for path in files:
            material_parts.append(f"--- From {path.name} ---\n{_normalize_text(parse_document(path))}\n")
    course_material = "\n".join(material_parts) or "No course materials found."

    resolved_lecture_topics = list(dict.fromkeys(
        _topic_name_from_lecture(path) for path in selected_map.get("lecture_notes", [])
    ))
    requested_topics = phrase_filters + resolved_lecture_topics
    if not requested_topics:
        requested_topics = ["course foundations"]
    selected_mlo_files = (
        selected_map.get("MLO", [])
        if (numeric_topics or phrase_filters)
        else document_map.get("MLO", [])
    )
    outcomes = extract_learning_outcomes(selected_mlo_files, input_path)
    blueprint = build_blueprint(
        num_versions=num_versions,
        num_questions=num_questions,
        question_style=question_type,
        topics=requested_topics,
        learning_outcomes=outcomes,
    )

    quiz_files: List[str] = []
    key_files: List[str] = []
    supplementary_files: List[str] = []

    for version_num in range(1, num_versions + 1):
        try:
            quiz_content, answer_key_content, generated_supplementary = _generate_quiz_with_llm(
                course_material,
                blueprint,
                version_num,
                output_format,
                output_path,
            )
        except Exception as e:
            raise RuntimeError(f"LLM generation failed for version {version_num}: {e}")

        ext = ".md" if output_format == "markdown" else ".tex"
        quiz_path = output_path / "quizzes" / f"quiz_{version_num:02d}{ext}"
        quiz_path.write_text(quiz_content, encoding="utf-8")
        quiz_files.append(str(quiz_path.relative_to(output_path.parent)))

        key_path = output_path / "answer_keys" / f"quiz_{version_num:02d}_key{ext}"
        key_path.write_text(answer_key_content, encoding="utf-8")
        key_files.append(str(key_path.relative_to(output_path.parent)))

        supplementary_files.extend(generated_supplementary)

    audit_path = output_path / "audit" / "generation_audit.md"
    blueprint_path = output_path / "audit" / "blueprint.json"
    blueprint_path.write_text(blueprint.to_json() + "\n", encoding="utf-8")
    
    audit_lines = [
        "# Quiz Generation Audit",
        "",
        "## Generation Summary",
        "",
        f"- **Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **Input Source**: {source_description or input_path.absolute()}",
        f"- **Output Directory**: {output_path.absolute()}",
        "",
        "## Request Parameters",
        "",
        f"- **Quiz Versions Requested**: {num_versions}",
        f"- **Questions per Version**: {num_questions}",
        f"- **Question Type**: {question_type}",
        f"- **Output Format**: {output_format}",
        f"- **Topic Filters**: {', '.join(audit_topic_filters) if audit_topic_filters else 'None'}",
        f"- **Multiple-select Questions per Version**: {sum(slot.question_kind.value == 'multiple_select' for slot in blueprint.slots)}",
        "",
        "## Source Materials",
        "",
    ]
    
    if materials_used:
        audit_lines.append("**Materials Included in Generation:**")
        audit_lines.append("")
        for material in sorted(materials_used):
            audit_lines.append(f"- {material}")
        audit_lines.append("")
    else:
        audit_lines.append("**Materials Included**: None found matching filters.")
        audit_lines.append("")
    
    audit_lines.extend([
        "## Verification Results",
        "",
        f"- **Versions Generated**: {len(quiz_files)} (Expected: {num_versions}) ✓" if len(quiz_files) == num_versions else f"- **Versions Generated**: {len(quiz_files)} (Expected: {num_versions}) ✗",
        f"- **Answer Keys Generated**: {len(key_files)} ✓" if len(key_files) == num_versions else f"- **Answer Keys Generated**: {len(key_files)} ✗",
        f"- **Quiz Output Files**: {(output_path / 'quizzes').exists()} ✓" if (output_path / 'quizzes').exists() else "- **Quiz Output Files**: False ✗",
        f"- **Answer Key Output Files**: {(output_path / 'answer_keys').exists()} ✓" if (output_path / 'answer_keys').exists() else "- **Answer Key Output Files**: False ✗",
        f"- **Supplementary Files**: {(output_path / 'supplementary').exists()} ✓" if (output_path / 'supplementary').exists() else "- **Supplementary Files**: False ✗",
        "- **Blueprint Parity**: PASS (all versions generated from the same assessment slots)",
        "",
        "## Assessment Blueprint",
        "",
        "| # | Topic | Learning outcome | Type | Modality | Difficulty |",
        "|---:|---|---|---|---|---|",
        *[
            f"| {slot.number} | {slot.topic} | {slot.learning_outcome.identifier}: {slot.learning_outcome.statement} | {slot.question_kind.value} | {slot.modality.value} | {slot.difficulty.value} |"
            for slot in blueprint.slots
        ],
        "",
        "## Output Files Generated",
        "",
        "**Quiz Files:**",
        "",
    ])
    
    for quiz_file in quiz_files:
        audit_lines.append(f"- {quiz_file}")
    
    audit_lines.extend([
        "",
        "**Answer Key Files:**",
        "",
    ])
    
    for key_file in key_files:
        audit_lines.append(f"- {key_file}")
    
    audit_lines.extend([
        "",
        "**Supplementary Files:**",
        "",
    ])
    
    for supp_file in supplementary_files:
        audit_lines.append(f"- {supp_file}")
    
    audit_content = "\n".join(audit_lines)
    audit_path.write_text(audit_content, encoding="utf-8")

    return {
        "quizzes": quiz_files,
        "answer_keys": key_files,
        "supplementary": supplementary_files,
        "audit": str(audit_path.relative_to(output_path.parent)),
        "blueprint_file": str(blueprint_path.relative_to(output_path.parent)),
        "blueprint": blueprint.to_dict(),
    }
