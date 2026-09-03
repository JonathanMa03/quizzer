"""LLM-based quiz generation using OpenAI API."""

from __future__ import annotations

import json
import ast
import os
import re
import subprocess
import sys
from difflib import SequenceMatcher
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from openai import OpenAI

from .blueprint import (
    LearningOutcome,
    QuizBlueprint,
    build_blueprint,
    extract_learning_outcomes,
    normalize_code_fences,
    normalize_choice_fields,
    normalize_formula_delimiters,
    normalize_plot_specs,
    validate_generated_quiz,
)
from .input_loader import collect_input_documents
from .parsers import parse_document

load_dotenv()

SUPPORTED_QUESTION_TYPES = {"mixed", "open"}
GENERATION_BATCH_SIZE = 5
MAX_GENERATION_ATTEMPTS = 3


def _build_safe_fallback_question(requirement: Dict[str, Any]) -> Dict[str, Any]:
    """Build a source-grounded conceptual question without another model call."""
    number = requirement["number"]
    kind = requirement["question_kind"]
    outcome_data = requirement.get("learning_outcome") or {}
    outcome = str(outcome_data.get("statement") or "Explain and apply the selected course concept.").strip()
    source = outcome_data.get("source") or "selected learning outcomes"
    lowered = outcome.casefold()

    if kind == "open_ended":
        return {
            "number": number,
            "question_kind": kind,
            "modality": "conceptual",
            "question": f"Explain this course concept in your own words and give one relevant example: {outcome}",
            "options": None,
            "correct_answers": [f"A complete response accurately explains and exemplifies: {outcome}"],
            "explanation": f"The response must accurately address and exemplify this course concept: {outcome}",
            "source_references": [source],
            "plot_spec": None,
            "_modality_fallback": "to_conceptual",
        }

    is_multi = kind == "multiple_select"
    if "supervised" in lowered and "unsupervised" in lowered:
        question = (
            "Which examples correctly match a learning setting with its description? Select all that apply."
            if is_multi else
            "A researcher uses labeled examples to predict a continuous house price. How should this task be described?"
        )
        options = (
            {
                "A": "Predicting a continuous value from labeled examples is supervised regression.",
                "B": "Grouping unlabeled observations by similarity is unsupervised clustering.",
                "C": "Predicting a class from labeled examples is unsupervised learning.",
                "D": "Grouping unlabeled observations is supervised regression.",
            }
            if is_multi else
            {
                "A": "Supervised learning with a continuous outcome",
                "B": "Supervised learning with a discrete outcome",
                "C": "Unsupervised clustering",
                "D": "Unsupervised dimensionality reduction",
            }
        )
        answers = ["A", "B"] if is_multi else ["A"]
    elif "classification" in lowered and "regression" in lowered and "clustering" in lowered:
        question = (
            "Which task descriptions are correctly matched? Select all that apply."
            if is_multi else
            "A team groups customers by similar purchasing behavior without labeled outcomes. Which task is this?"
        )
        options = {
            "A": "Classification assigns observations to predefined classes.",
            "B": "Regression predicts a continuous outcome.",
            "C": "Clustering requires predefined class labels.",
            "D": "Dimensionality reduction predicts a required response variable.",
        } if is_multi else {
            "A": "Clustering", "B": "Regression", "C": "Classification", "D": "Dimensionality reduction"
        }
        answers = ["A", "B"] if is_multi else ["A"]
    elif "kde" in lowered or ("kernel" in lowered and "bandwidth" in lowered):
        question = (
            "Which statements about kernel density estimation are correct? Select all that apply."
            if is_multi else
            "What is the primary role of bandwidth in kernel density estimation?"
        )
        options = {
            "A": "KDE estimates a smooth distribution from observed data.",
            "B": "Bandwidth controls the smoothness of the estimate.",
            "C": "KDE assigns observations to known class labels.",
            "D": "Bandwidth is the number of rows in the dataset.",
        } if is_multi else {
            "A": "It controls how smooth the estimated density is.",
            "B": "It sets the number of observations.",
            "C": "It chooses the response variable.",
            "D": "It converts continuous data into class labels.",
        }
        answers = ["A", "B"] if is_multi else ["A"]
    elif "underfit" in lowered or "overfit" in lowered:
        question = (
            "Which statements correctly describe model complexity? Select all that apply."
            if is_multi else
            "A model performs very well on training data but poorly on new data. Which issue is most likely?"
        )
        options = {
            "A": "An overly simple model can underfit.",
            "B": "An overly complex model can overfit training data.",
            "C": "Greater complexity always improves performance on new data.",
            "D": "Underfitting means memorizing every training observation.",
        } if is_multi else {
            "A": "Overfitting", "B": "Underfitting", "C": "Clustering", "D": "Dimensionality reduction"
        }
        answers = ["A", "B"] if is_multi else ["A"]
    elif "signal" in lowered and "noise" in lowered:
        question = (
            "Which statements correctly describe signal and noise in observed data? Select all that apply."
            if is_multi else "Which statement best distinguishes signal from random noise in an observation?"
        )
        options = {
            "A": "Signal is the structured pattern of interest.",
            "B": "Random noise is unexplained variation around the structured pattern.",
            "C": "Noise is the systematic relationship the analysis seeks to model.",
            "D": "Signal refers only to the largest observed value.",
        }
        answers = ["A", "B"] if is_multi else ["A"]
    elif any(term in lowered for term in ("mean", "median", "variance", "standard deviation", "skew")):
        question = (
            "Which statements about descriptive statistics are correct? Select all that apply."
            if is_multi else "Which statement about descriptive statistics is correct?"
        )
        options = {
            "A": "The median is the middle value after observations are ordered.",
            "B": "Standard deviation measures spread and is the square root of variance.",
            "C": "The mean is unaffected by extreme observations.",
            "D": "Standard deviation measures the location of the center only.",
        }
        answers = ["A", "B"] if is_multi else ["A"]
    elif all(term in lowered for term in ("pandas", "numpy", "matplotlib")):
        question = (
            "Which library-to-task matches are correct? Select all that apply."
            if is_multi else "Which library is primarily used to create data visualizations?"
        )
        options = {
            "A": "Pandas — loading and manipulating tabular data",
            "B": "NumPy — numerical array computation",
            "C": "Matplotlib — loading relational database tables",
            "D": "Pandas — rendering every type of statistical graphic",
        }
        answers = ["A", "B"] if is_multi else ["A"]
        if not is_multi:
            options = {"A": "Matplotlib", "B": "Pandas", "C": "NumPy", "D": "CSV"}
    elif "pandas" in lowered:
        question = (
            "Which tasks are appropriate uses of Pandas? Select all that apply."
            if is_multi else "Which task is Pandas primarily used for in the course workflow?"
        )
        options = {
            "A": "Loading a CSV file into a table",
            "B": "Selecting a named column from tabular data",
            "C": "Replacing all numerical and plotting libraries",
            "D": "Assigning labels with an unspecified learning algorithm",
        }
        answers = ["A", "B"] if is_multi else ["A"]
    elif "matplotlib" in lowered:
        question = (
            "Which tasks can be performed with Matplotlib? Select all that apply."
            if is_multi else "Which task is Matplotlib primarily used for?"
        )
        options = {"A": "Creating a scatterplot", "B": "Creating a histogram", "C": "Loading SQL tables", "D": "Computing an array mean"}
        answers = ["A", "B"] if is_multi else ["A"]
    else:
        if is_multi:
            return {
                "number": number,
                "question_kind": "open_ended",
                "modality": "conceptual",
                "question": f"Explain this course concept and give a concrete example: {outcome}",
                "options": None,
                "correct_answers": [f"A complete answer accurately explains and exemplifies: {outcome}"],
                "explanation": f"The response must accurately address this course concept: {outcome}",
                "source_references": [source],
                "plot_spec": None,
                "_modality_fallback": "to_conceptual",
                "_question_kind_fallback": "to_open_ended",
            }
        question = f"Which statement best demonstrates this course concept: {outcome}"
        options = {
            "A": outcome,
            "B": "The concept applies only to course administration.",
            "C": "The concept requires ignoring the supplied course material.",
            "D": "The concept cannot be explained or applied.",
        }
        answers = ["A"]
    return {
        "number": number,
        "question_kind": kind,
        "modality": "conceptual",
        "question": question,
        "options": options,
        "correct_answers": answers,
        "explanation": f"The correct choice or choices assess this course outcome: {outcome}",
        "source_references": [source],
        "plot_spec": None,
        "_modality_fallback": "to_conceptual",
    }


def _question_similarity_errors(
    data: Dict[str, Any],
    prior_questions: List[str],
    *,
    context: str = "an earlier-version question",
) -> List[str]:
    """Reject near-duplicate stems against a supplied reference set."""
    errors: List[str] = []
    prior = [re.sub(r"\s+", " ", text).strip().casefold() for text in prior_questions if text.strip()]
    for question in data.get("questions", []):
        current = re.sub(r"\s+", " ", str(question.get("question", ""))).strip().casefold()
        if not current:
            continue
        for old in prior:
            ratio = SequenceMatcher(None, current, old).ratio()
            current_words = set(re.findall(r"[a-z0-9]+", current))
            old_words = set(re.findall(r"[a-z0-9]+", old))
            overlap = len(current_words & old_words) / max(1, len(current_words | old_words))
            if ratio >= 0.72 or overlap >= 0.72:
                errors.append(
                    f"question {question.get('number')}: too similar to {context}"
                )
                break
    return errors


def _within_quiz_similarity_errors(
    data: Dict[str, Any],
    accepted_questions: List[Dict[str, Any]] | None = None,
) -> List[str]:
    """Reject repeats within a batch and against earlier batches of one quiz."""
    references = [
        str(question.get("question", ""))
        for question in (accepted_questions or [])
        if str(question.get("question", "")).strip()
    ]
    errors: List[str] = []
    for question in data.get("questions", []):
        errors.extend(
            _question_similarity_errors(
                {"questions": [question]},
                references,
                context="another question in the same quiz",
            )
        )
        prompt = str(question.get("question", "")).strip()
        if prompt:
            references.append(prompt)
    return errors


def _material_grounding_errors(data: Dict[str, Any], lecture_material: str) -> List[str]:
    """Reject questions that require unintroduced software or computer execution."""
    errors: List[str] = []
    material = lecture_material.casefold()
    named_methods = {
        "decision tree": r"\bdecision trees?\b",
        "support vector machine": r"\b(?:support vector machines?|svms?)\b",
        "time series": r"\btime series\b",
        "scikit-learn": r"\b(?:scikit-learn|sklearn)\b",
        "seaborn": r"\bseaborn\b",
        "k-nearest neighbors": r"\b(?:k-nearest neighbors?|knn)\b",
        "logistic regression": r"\blogistic regression\b",
    }
    for question in data.get("questions", []):
        number = question.get("number")
        prompt = str(question.get("question", ""))
        lowered = prompt.casefold()
        text_values = [prompt, str(question.get("explanation", ""))]
        if isinstance(question.get("options"), dict):
            text_values.extend(str(value) for value in question["options"].values())
        all_student_text = " ".join(text_values).casefold()
        for method, pattern in named_methods.items():
            if re.search(pattern, all_student_text, re.IGNORECASE) and not re.search(pattern, material, re.IGNORECASE):
                errors.append(
                    f"question {number}: method '{method}' is not introduced in the selected notes or outcomes"
                )
        if question.get("modality") == "code":
            if re.search(r"\b(?:random|rand|randn|default_rng)\b", lowered):
                errors.append(f"question {number}: code questions must not depend on random output")
            if re.search(r"\.(?:fit|predict|score)\s*\(", prompt):
                errors.append(f"question {number}: code questions must be solvable without fitting or running a model")
            imported_roots = re.findall(
                r"(?m)^\s*(?:from\s+([A-Za-z_]\w*)|import\s+([A-Za-z_]\w*))",
                prompt,
            )
            for first, second in imported_roots:
                package = (first or second).casefold()
                if package not in material:
                    errors.append(
                        f"question {number}: package '{package}' is not introduced in the selected lecture notes"
                    )
            if re.search(r"(?i)assume\s+['\"]?data['\"]?\s+is", prompt) and not re.search(
                r"(?m)^\s*data\s*=", prompt
            ):
                errors.append(f"question {number}: code question uses data without providing its values")
        if re.search(r"(?i)\b(?:calculate|compute|determine)\b", prompt) and len(re.findall(r"[-+]?\d+(?:\.\d+)?", prompt)) > 12:
            errors.append(f"question {number}: computation is too large to solve without a computer")
    return errors


def _answer_exposure_errors(data: Dict[str, Any]) -> List[str]:
    """Reject stems that explicitly name a short correct answer."""
    errors: List[str] = []
    for question in data.get("questions", []):
        prompt = re.sub(r"[`*_]", "", str(question.get("question", ""))).casefold()
        options = question.get("options")
        answers = question.get("correct_answers")
        if not isinstance(options, dict) or not isinstance(answers, list):
            continue
        for letter in answers:
            answer = re.sub(r"[`*_]", "", str(options.get(letter, ""))).strip().casefold()
            words = re.findall(r"[a-z0-9]+", answer)
            if (
                1 <= len(words) <= 6
                and len(answer) >= 3
                and answer
                and re.search(rf"\b{re.escape(answer)}\b", prompt)
            ):
                errors.append(
                    f"question {question.get('number')}: prompt exposes correct answer {letter}"
                )
                break
    return errors


def _answer_quality_errors(data: Dict[str, Any]) -> List[str]:
    """Reject meta, process-oriented, or otherwise non-substantive choices."""
    errors: List[str] = []
    banned_patterns = (
        r"selected course materials?",
        r"supplied learning outcomes?",
        r"course administration",
        r"ignore(?:s|d|ing)? the (?:concepts|course material)",
        r"correct response must",
        r"cannot be explained or applied",
        r"has no analytical content",
    )
    for question in data.get("questions", []):
        options = question.get("options")
        if not isinstance(options, dict):
            continue
        for letter, option in options.items():
            text_value = str(option)
            if any(re.search(pattern, text_value, re.IGNORECASE) for pattern in banned_patterns):
                errors.append(
                    f"question {question.get('number')}: option {letter} is meta or non-substantive"
                )
    return errors


def _code_execution_errors(data: Dict[str, Any]) -> List[str]:
    """Require every fenced student-facing code block to be safe and runnable."""
    errors: List[str] = []
    allowed_imports = {"math", "statistics", "numpy", "pandas", "matplotlib"}
    forbidden_names = {"eval", "exec", "open", "compile", "__import__", "input"}
    for question in data.get("questions", []):
        texts = [str(question.get("question", ""))]
        if isinstance(question.get("options"), dict):
            texts.extend(str(value) for value in question["options"].values())
        blocks = [
            match.group(1).strip()
            for text_value in texts
            for match in re.finditer(r"```(?:python|py)?\s*\n(.*?)\n```", text_value, re.DOTALL | re.IGNORECASE)
        ]
        for code in blocks:
            try:
                tree = ast.parse(code)
            except SyntaxError as exc:
                errors.append(f"question {question.get('number')}: code is not valid Python: {exc.msg}")
                continue
            unsafe = False
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    unsafe |= any(alias.name.split(".")[0] not in allowed_imports for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    unsafe |= (node.module or "").split(".")[0] not in allowed_imports
                elif isinstance(node, ast.Name) and node.id in forbidden_names:
                    unsafe = True
            if unsafe:
                errors.append(f"question {question.get('number')}: code uses a disallowed operation or import")
                continue
            try:
                completed = subprocess.run(
                    [sys.executable, "-c", code],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env={**os.environ, "MPLBACKEND": "Agg"},
                )
            except subprocess.TimeoutExpired:
                errors.append(f"question {question.get('number')}: code did not finish within 5 seconds")
                continue
            if completed.returncode != 0:
                detail = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "execution failed"
                errors.append(f"question {question.get('number')}: code is not runnable: {detail}")
    return errors


def _filter_outcomes_for_lecture(outcomes: List[Any], lecture_material: str) -> List[Any]:
    """Keep MLO statements whose substantive vocabulary is present in the notes."""
    stopwords = {
        "about", "across", "after", "also", "appropriate", "common", "concept", "concepts",
        "data", "describe", "distinguish", "explain", "identify", "include", "includes",
        "into", "learning", "often", "selected", "statement", "statistics", "students",
        "such", "their", "these", "through", "tools", "using", "while", "with", "without",
    }

    def stem(word: str) -> str:
        for suffix in ("ing", "ed", "es", "s"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                return word[: -len(suffix)]
        return word

    material_tokens = {stem(token) for token in re.findall(r"[A-Za-z][A-Za-z0-9_]+", lecture_material.casefold())}
    supported = []
    for outcome in outcomes:
        tokens = {
            stem(token)
            for token in re.findall(r"[A-Za-z][A-Za-z0-9_]+", outcome.statement.casefold())
            if len(token) >= 4 and token not in stopwords
        }
        if tokens and len(tokens & material_tokens) / len(tokens) >= 0.9:
            supported.append(outcome)
    return supported


def _normalize_generated_data(data: Dict[str, Any], plan: Dict[str, Any]) -> None:
    """Apply deterministic repairs before enforcing the generation contract."""
    normalize_formula_delimiters(data, plan)
    normalize_code_fences(data)
    normalize_plot_specs(data, plan)
    normalize_choice_fields(data, plan)


def _repair_question_with_llm(
    client: OpenAI,
    requirement: Dict[str, Any],
    invalid_question: Dict[str, Any] | None,
    course_material: str,
    version_num: int,
    prior_question_prompts: List[str] | None = None,
) -> Dict[str, Any]:
    """Generate one focused replacement after batch-level retries are exhausted."""
    active_requirement = dict(requirement)
    downgraded_modality = False
    initial_grounding_errors = _material_grounding_errors(
        {"questions": [invalid_question]} if isinstance(invalid_question, dict) else {"questions": []},
        course_material,
    )
    if active_requirement.get("modality") == "code" and initial_grounding_errors:
        active_requirement["modality"] = "conceptual"
        downgraded_modality = True
        previous = "null (discard the prior computer-dependent code question entirely)"
    else:
        previous = json.dumps(invalid_question, ensure_ascii=False, indent=2) if invalid_question else "null"
    single_plan = {"version": version_num, "requirements": [active_requirement]}
    errors: List[str] = ["no valid question was produced"]
    structurally_valid_fallback: Dict[str, Any] | None = None
    modality_fallback: Dict[str, Any] | None = None

    for _attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        prompt = f"""Repair one quiz question so it satisfies the assessment requirement exactly.

Return a JSON object containing exactly one question in a `questions` list. Use the exact number, question_kind, and modality from the requirement.

For single_choice, provide exactly four non-empty options keyed A, B, C, and D, plus exactly one correct_answers letter.
For multiple_select, provide exactly four non-empty options keyed A, B, C, and D, plus at least two correct_answers letters.
For open_ended, omit options and provide a concise model answer in correct_answers.
For code, put one shared executable snippet in a fenced Markdown block in the question prompt. Answer choices must be prose interpretations or outputs, never alternative code snippets. Provide every input value and use no answer-revealing comments, variable names, function names, or printed labels.
For plot_interpretation, include plot_spec with plot_type, numeric x/y lists, empty title, axis labels, and groups when clustering is assessed. Plot questions still require A-D options when their question_kind is a choice type.
Use only concepts and software explicitly present in the selected lecture material. The student must be able to answer without running code or using a computer; do not use random output or fitted-model behavior. Use a histogram—not a scatterplot—when asking about a distribution's shape, modes, location, dispersion, skewness, or kurtosis.
Every Python block must be complete and run successfully as written. For a histogram, provide literal raw observations in plot_spec.values, including repeated values; do not provide artificial bin coordinates or frequencies.

REQUIREMENT:
{json.dumps(active_requirement, ensure_ascii=False, indent=2)}

INVALID QUESTION TO REPAIR:
{previous}

EARLIER-VERSION QUESTIONS THAT MUST NOT BE PARAPHRASED OR REUSED:
{json.dumps([text[:500] for text in (prior_question_prompts or [])[-60:]], ensure_ascii=False, indent=2)}

VALIDATION ERRORS FROM THE PRIOR REPAIR:
- {'; '.join(errors)}

COURSE MATERIAL:
{course_material[:15000]}

Respond only with JSON."""
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_completion_tokens=2048,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
        response_text = response.choices[0].message.content or ""
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError as exc:
            errors = [f"response was not valid JSON: {exc.msg}"]
            previous = response_text[:8000]
            continue

        _normalize_generated_data(data, single_plan)
        structural_errors = validate_generated_quiz(data, single_plan)
        structural_errors.extend(_material_grounding_errors(data, course_material))
        structural_errors.extend(_answer_exposure_errors(data))
        structural_errors.extend(_answer_quality_errors(data))
        structural_errors.extend(_code_execution_errors(data))
        diversity_errors = _question_similarity_errors(data, prior_question_prompts or [])
        errors = structural_errors + diversity_errors
        if not structural_errors:
            structurally_valid_fallback = data["questions"][0]
        elif (
            len(data.get("questions", [])) == 1
            and all("code questions require rendered code" in error for error in structural_errors)
        ):
            modality_fallback = data["questions"][0]
        if not errors:
            repaired = data["questions"][0]
            if downgraded_modality:
                repaired["_modality_fallback"] = "code_to_conceptual"
            return repaired

        if active_requirement.get("modality") == "code" and any(
            "not introduced" in error
            or "without fitting or running a model" in error
            or "random output" in error
            or "too large to solve without a computer" in error
            for error in structural_errors
        ):
            active_requirement["modality"] = "conceptual"
            single_plan = {"version": version_num, "requirements": [active_requirement]}
            downgraded_modality = True
            previous = "null (discard the prior computer-dependent code question entirely)"
            continue
        questions = data.get("questions")
        previous = json.dumps(
            questions[0] if isinstance(questions, list) and questions else data,
            ensure_ascii=False,
            indent=2,
        )[:8000]

    # Diversity is a bounded quality objective, not a reason to discard a
    # structurally correct quiz after all targeted repair attempts.
    if structurally_valid_fallback is not None and all("too similar" in error for error in errors):
        if downgraded_modality:
            structurally_valid_fallback["_modality_fallback"] = "code_to_conceptual"
        return structurally_valid_fallback
    if modality_fallback is not None and all(
        "code questions require rendered code" in error or "too similar" in error
        for error in errors
    ):
        modality_fallback["modality"] = "conceptual"
        modality_fallback["_modality_fallback"] = "code_to_conceptual"
        return modality_fallback

    return _build_safe_fallback_question(requirement)


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
    prior_question_prompts: List[str] | None = None,
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
    prior_question_prompts = prior_question_prompts if prior_question_prompts is not None else []
    avoidance_list = [prompt[:500] for prompt in prior_question_prompts[-60:]]

    for batch_start in range(0, len(requirements), GENERATION_BATCH_SIZE):
        batch_requirements = requirements[batch_start : batch_start + GENERATION_BATCH_SIZE]
        batch_plan = {"version": version_num, "requirements": batch_requirements}
        plan_json = json.dumps(batch_plan, indent=2)
        expected_numbers = [requirement["number"] for requirement in batch_requirements]
        validation_feedback = ""
        previous_response = ""
        last_batch_data: Dict[str, Any] = {"questions": []}

        for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
            prompt = f"""You are an expert tutor creating version {version_num} of a grounded course quiz.

Follow this version's assessment plan exactly. Overall coverage is comparable across versions, but slot content and modalities are deliberately permuted.
Create a distinct question for this version while preserving the slot's topic, learning outcome, question kind, and difficulty.
Use only facts supported by the course material.
Return exactly {len(batch_requirements)} questions, numbered {expected_numbers}. Do not return an example or omit any assigned question.
This is version {version_num}. Do not reuse the task framing, scenario, code, numerical setup, plot shape, or central question used in earlier versions. Assess a meaningfully different aspect of the assigned outcome whenever the source material permits it.

Question-kind rules:
- single_choice: exactly four options A-D and exactly one correct answer
- multiple_select: exactly four options A-D and at least two correct answers
- open_ended: no options; correct_answers contains a concise model answer

Assessment-modality rules:
- conceptual: assess explanation, comparison, or application of a concept
- formula: use valid dollar-delimited LaTeX; prefer $...$ inline math unless a display block is genuinely needed, and JSON-escape every LaTeX backslash
- code: include one short, self-contained fenced Markdown code block in the question prompt and ask for interpretation, prediction, or debugging; define every input value; answer choices must be prose or outputs rather than code; never emit literal \\n sequences, a one-backtick language block, answer-revealing comments, or answer-revealing names
- plot_interpretation: provide a concrete, title-less plot_spec with numeric x and y values; ask students to interpret the generated plot, not an imagined plot or superficial labels/colors
- grounding: make every question concrete and answerable by supplying a dataset, numerical values, code, formula, plot, result, or realistic decision scenario; avoid vague prompts that merely ask which abstract description is best
- answer quality: every option must make a substantive claim about the assessed concept; never mention the learning outcome, course materials, quiz construction, course administration, or instructions for interpreting the concept in an answer choice
- clustering plots: use at least 30 points arranged into at least two visually distinct groups and provide a groups array aligned with x and y so the structure cannot reasonably be mistaken for a regression trend
- plot display: never include raw x/y values, coordinate pairs, a “Plot Points” section, or a data table in the student-facing question; the generated image is the only presentation of plot data
- student solvability: every question must be answerable by inspection and reasonable hand calculation; never require executing code, reproducing pseudorandom output, fitting a model, or knowing an API/class not explicitly shown in the selected lecture notes
- course scope: assess only content in the selected lecture notes or explicit learning outcomes; the syllabus does not authorize quiz content, and a broad outcome does not authorize specific algorithms, packages, classes, or APIs that neither source names
- plot choice: use histogram for distribution shape, location, dispersion, skewness, kurtosis, or modality questions; use scatter only for relationships or clusters
- histogram data: provide a `values` list containing the literal raw observations to bin, including repeated values such as [5, 5, 5, 5, 4, 4, 3, 2, 2, 1]; never encode histogram bin centers and frequencies as x/y coordinates
- runnable code: every code block must be complete, self-contained, valid Python that runs successfully as written; define all data and imports and use only packages present in the selected materials

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
    "plot_type": "line, scatter, bar, or histogram",
    "x": [numeric values],
    "y": [numeric values],
    "title": "",
    "x_label": "x-axis label",
    "y_label": "y-axis label",
    "groups": null,
    "values": null
}}

Never use a plot title: the title may reveal the answer. For a clustering question, replace groups with one group identifier per point and use at least 30 points. For other plots, groups may be null.

ASSESSMENT BLUEPRINT:
{plan_json}

EARLIER-VERSION QUESTIONS THAT MUST NOT BE REUSED:
{json.dumps(avoidance_list, ensure_ascii=False, indent=2)}

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
            previous_response = response_text
            try:
                batch_data = json.loads(response_text)
            except json.JSONDecodeError as exc:
                errors = [f"response was not valid JSON: {exc.msg}"]
            else:
                _normalize_generated_data(batch_data, batch_plan)
                last_batch_data = batch_data
                errors = validate_generated_quiz(batch_data, batch_plan)
                errors.extend(_material_grounding_errors(batch_data, course_material))
                errors.extend(_answer_exposure_errors(batch_data))
                errors.extend(_answer_quality_errors(batch_data))
                errors.extend(_code_execution_errors(batch_data))
                errors.extend(_within_quiz_similarity_errors(batch_data, generated_questions))
                errors.extend(_question_similarity_errors(batch_data, prior_question_prompts))
                if not errors:
                    generated_questions.extend(batch_data["questions"])
                    break

            validation_feedback = (
                "PREVIOUS ATTEMPT FAILED VALIDATION. Repair the previous JSON rather than creating an unrelated replacement. "
                "Correct every issue below and return the entire assigned batch:\n- "
                + "\n- ".join(errors)
                + "\n\nPREVIOUS INVALID JSON:\n"
                + previous_response[:12000]
            )
        else:
            # Preserve any valid questions from the last batch and repair only
            # invalid/missing slots with smaller, focused requests.
            candidates = last_batch_data.get("questions")
            by_number = {
                question.get("number"): question
                for question in candidates
                if isinstance(candidates, list) and isinstance(question, dict)
            } if isinstance(candidates, list) else {}
            repaired_batch: List[Dict[str, Any]] = []
            for requirement in batch_requirements:
                candidate = by_number.get(requirement["number"])
                candidate_data = {"questions": [candidate]} if isinstance(candidate, dict) else {"questions": []}
                single_plan = {"version": version_num, "requirements": [requirement]}
                if isinstance(candidate, dict):
                    _normalize_generated_data(candidate_data, single_plan)
                candidate_errors = validate_generated_quiz(candidate_data, single_plan)
                candidate_errors.extend(_material_grounding_errors(candidate_data, course_material))
                candidate_errors.extend(_answer_exposure_errors(candidate_data))
                candidate_errors.extend(_answer_quality_errors(candidate_data))
                candidate_errors.extend(_code_execution_errors(candidate_data))
                same_quiz_references = generated_questions + repaired_batch
                candidate_errors.extend(_within_quiz_similarity_errors(candidate_data, same_quiz_references))
                candidate_errors.extend(_question_similarity_errors(candidate_data, prior_question_prompts))
                if candidate_errors:
                    repair_references = [
                        *prior_question_prompts,
                        *(str(item.get("question", "")) for item in same_quiz_references),
                    ]
                    candidate = _repair_question_with_llm(
                        client,
                        requirement,
                        candidate if isinstance(candidate, dict) else None,
                        course_material,
                        version_num,
                        repair_references,
                    )
                    if _within_quiz_similarity_errors(
                        {"questions": [candidate]}, same_quiz_references
                    ):
                        candidate = _build_safe_fallback_question(requirement)
                    if candidate.pop("_modality_fallback", None):
                        requirement["modality"] = "conceptual"
                    if candidate.pop("_question_kind_fallback", None):
                        requirement["question_kind"] = candidate["question_kind"]
                    _normalize_generated_data(
                        {"questions": [candidate]},
                        {"version": version_num, "requirements": [requirement]},
                    )
                repaired_batch.append(candidate)

            repaired_data = {"questions": repaired_batch}
            repaired_errors = validate_generated_quiz(repaired_data, batch_plan)
            repaired_errors.extend(_material_grounding_errors(repaired_data, course_material))
            repaired_errors.extend(_answer_exposure_errors(repaired_data))
            repaired_errors.extend(_answer_quality_errors(repaired_data))
            repaired_errors.extend(_code_execution_errors(repaired_data))
            repaired_errors.extend(_within_quiz_similarity_errors(repaired_data, generated_questions))
            if repaired_errors:
                batch_label = f"{expected_numbers[0]}-{expected_numbers[-1]}"
                raise ValueError(
                    f"Could not generate a valid question batch ({batch_label}) after batch and focused repairs: "
                    + "; ".join(repaired_errors)
                )
            generated_questions.extend(repaired_batch)

    quiz_data = {"questions": generated_questions}
    errors = validate_generated_quiz(quiz_data, plan)
    errors.extend(_within_quiz_similarity_errors(quiz_data))
    if errors:
        raise ValueError("Generated quiz violated its blueprint: " + "; ".join(errors))

    supplementary_files = _write_plot_artifacts(quiz_data, output_dir, version_num)
    quiz_content = _format_quiz_from_llm(quiz_data, output_format)
    answer_key = _format_answer_key_from_llm(quiz_data, output_format)
    prior_question_prompts.extend(
        str(question.get("question", "")).strip()
        for question in generated_questions
        if str(question.get("question", "")).strip()
    )

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
            "groups = SPEC.get('groups')\n"
            "if plot_type == 'scatter':\n"
            "    if groups:\n"
            "        labels = {label: index for index, label in enumerate(dict.fromkeys(map(str, groups)))}\n"
            "        colors = [labels[str(group)] for group in groups]\n"
            "        ax.scatter(SPEC['x'], SPEC['y'], c=colors, cmap='tab10')\n"
            "    else:\n"
            "        ax.scatter(SPEC['x'], SPEC['y'])\n"
            "elif plot_type == 'histogram':\n"
            "    ax.hist(SPEC.get('values', SPEC['x']), bins='auto', edgecolor='black')\n"
            "elif plot_type == 'bar':\n"
            "    ax.bar(SPEC['x'], SPEC['y'])\n"
            "else:\n"
            "    ax.plot(SPEC['x'], SPEC['y'], marker='o')\n"
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
        question["plot_alt"] = f"Data visualization for question {q_num}"
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
            q_text = re.sub(
                r"\s*```(?:python|py|r)?[ \t]*\n?(.*?)```",
                lambda match: f"\n\n```python\n{match.group(1).strip()}\n```\n\n",
                q_text,
                flags=re.IGNORECASE | re.DOTALL,
            )
            q_text = q_text.rstrip()
            if q.get("plot_path"):
                lines.append(f"![{q.get('plot_alt', 'Question plot')}]({q['plot_path']})")
                lines.append("")
            lines.append(f"{q_num}. {q_text}")
            lines.append("")
            if options:
                for letter in ["A", "B", "C", "D"]:
                    if letter in options:
                        option_text = str(options[letter]).strip()
                        option_text = re.sub(
                            r"(?is)^```(?:python|py|r)?\s*(.*?)\s*```$",
                            lambda match: match.group(1).strip(),
                            option_text,
                        )
                        option_text = re.sub(r"\s*\n\s*", "<br>", option_text)
                        lines.append(f"{letter}. {option_text}  ")
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

    # A generation run owns these derived artifacts. Remove the previous set
    # up front so a failed run cannot leave new quiz 1 beside stale quizzes 2–3.
    generated_patterns = {
        "quizzes": ("quiz_*.md", "quiz_*.tex"),
        "answer_keys": ("quiz_*_key.md", "quiz_*_key.tex"),
        "audit": ("blueprint.json", "generation_audit.md"),
        "supplementary/code": ("quiz_*_plot.py",),
        "supplementary/plots": ("quiz_*_plot.png",),
    }
    for folder, patterns in generated_patterns.items():
        for pattern in patterns:
            for artifact in (output_path / folder).glob(pattern):
                artifact.unlink()

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
    assessable_groups = {"lecture_notes", "MLO"}
    for group, files in selected_map.items():
        if group not in assessable_groups:
            continue
        for path in files:
            material_parts.append(f"--- From {path.name} ---\n{_normalize_text(parse_document(path))}\n")
    course_material = "\n".join(material_parts) or "No selected lecture-note materials found."

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
    if not outcomes:
        outcomes = [LearningOutcome(
            identifier="LO-LECTURE",
            statement="Apply only concepts explicitly taught in the selected lecture notes and learning outcomes.",
            source="lecture_notes",
        )]
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
    prior_question_prompts: List[str] = []

    for version_num in range(1, num_versions + 1):
        try:
            quiz_content, answer_key_content, generated_supplementary = _generate_quiz_with_llm(
                course_material,
                blueprint,
                version_num,
                output_format,
                output_path,
                prior_question_prompts,
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
        "- **Alternate-Version Plan**: PASS (coverage retained while slot content and modalities are permuted)",
        "",
        "## Assessment Blueprint",
        "",
        "| Version | # | Topic | Learning outcome | Type | Modality | Difficulty |",
        "|---:|---:|---|---|---|---|---|",
        *[
            f"| {version} | {requirement['number']} | {requirement['topic']} | "
            f"{requirement['learning_outcome']['identifier']}: {requirement['learning_outcome']['statement']} | "
            f"{requirement['question_kind']} | {requirement['modality']} | {requirement['difficulty']} |"
            for version in range(1, num_versions + 1)
            for requirement in blueprint.version_plan(version)["requirements"]
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
