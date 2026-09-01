"""Deterministic assessment planning shared by every generated quiz version."""

from __future__ import annotations

import json
import hashlib
import math
import random
import re
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Sequence


class QuestionKind(str, Enum):
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_SELECT = "multiple_select"
    OPEN_ENDED = "open_ended"


class Difficulty(str, Enum):
    FOUNDATIONAL = "foundational"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class AssessmentModality(str, Enum):
    CONCEPTUAL = "conceptual"
    FORMULA = "formula"
    CODE = "code"
    PLOT_INTERPRETATION = "plot_interpretation"


@dataclass(frozen=True)
class LearningOutcome:
    identifier: str
    statement: str
    category: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class BlueprintSlot:
    """A comparable assessment target reused at the same position in every version."""

    number: int
    topic: str
    learning_outcome: LearningOutcome
    question_kind: QuestionKind
    difficulty: Difficulty
    modality: AssessmentModality


@dataclass(frozen=True)
class QuizBlueprint:
    num_versions: int
    num_questions: int
    question_style: str
    topics: tuple[str, ...]
    slots: tuple[BlueprintSlot, ...]

    def version_plan(self, version: int) -> dict:
        if not 1 <= version <= self.num_versions:
            raise ValueError(f"Version must be between 1 and {self.num_versions}")
        count = len(self.slots)
        seed_material = "|".join(
            [str(version), *self.topics, *(slot.learning_outcome.identifier for slot in self.slots)]
        )
        seed = int(hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:16], 16)
        rng = random.Random(seed)
        content_order = list(range(count))
        modality_order = list(range(count))
        rng.shuffle(content_order)
        rng.shuffle(modality_order)
        requirements = []
        for index, position_slot in enumerate(self.slots):
            content_slot = self.slots[content_order[index]]
            modality_slot = self.slots[modality_order[index]]
            requirements.append({
                **asdict(content_slot),
                "number": position_slot.number,
                "question_kind": position_slot.question_kind.value,
                "difficulty": content_slot.difficulty.value,
                "modality": modality_slot.modality.value,
            })
        return {
            "version": version,
            "requirements": requirements,
        }

    def to_dict(self) -> dict:
        return {
            "num_versions": self.num_versions,
            "num_questions": self.num_questions,
            "question_style": self.question_style,
            "topics": list(self.topics),
            "slots": self.version_plan(1)["requirements"],
            "version_plans": [
                self.version_plan(version)
                for version in range(1, self.num_versions + 1)
            ],
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


_BULLET_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(.+?)\s*$")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")
_MATH_SPAN_RE = re.compile(r"\${1,2}(.+?)\${1,2}", re.DOTALL)
_LATEX_COMMANDS = {
    "alpha", "bar", "beta", "big", "bigg", "Big", "Bigg", "cdot", "delta", "epsilon", "exp", "frac",
    "gamma", "geq", "hat", "infty", "int", "lambda", "left", "leq",
    "log", "mathbb", "mathcal", "mu", "nu", "partial", "phi", "pi",
    "prod", "rho", "right", "sigma", "sqrt", "sum", "text", "textstyle", "theta",
    "times", "vec",
}


def _question_text_values(question: dict) -> list[str]:
    values = [question.get("question", ""), question.get("explanation", "")]
    options = question.get("options")
    if isinstance(options, dict):
        values.extend(options.values())
    return [value for value in values if isinstance(value, str)]


def normalize_formula_delimiters(quiz_data: dict, plan: dict) -> None:
    """Repair JSON-damaged LaTeX and use notebook-safe inline math delimiters."""
    questions = quiz_data.get("questions")
    if not isinstance(questions, list):
        return

    def repair_math_body(body: str) -> str:
        control_replacements = {
            "\b": r"\b",
            "\f": r"\f",
            "\n": r"\n",
            "\r": r"\r",
            "\t": r"\t",
        }
        for damaged, replacement in control_replacements.items():
            body = body.replace(damaged, replacement)

        def repair_command(match: re.Match[str]) -> str:
            command = match.group(1)
            damaged_aliases = {
                "regexpsilon": "epsilon",
                "xpsilon": "epsilon",
            }
            if command in damaged_aliases:
                return f"\\{damaged_aliases[command]}"
            if command in _LATEX_COMMANDS:
                return f"\\{command}"
            suffixes = [known for known in _LATEX_COMMANDS if command.endswith(known)]
            return f"\\{max(suffixes, key=len)}" if suffixes else command

        return re.sub(r"\\([A-Za-z]+)", repair_command, body).strip()

    def normalize(value: str) -> str:
        value = re.sub(r"(?i)(?<!\\)textstylebigg", r"\\textstyle\\bigg", value)
        value = re.sub(r"(?i)(?<!\\)textstyle", r"\\textstyle", value)
        value = re.sub(r"(?i)(?<!\\)bigg(?=\s*[()\[\]])", r"\\bigg", value)
        value = re.sub(r"\\\[(.*?)\\\]", r"$\1$", value, flags=re.DOTALL)
        value = re.sub(r"\\\((.*?)\\\)", r"$\1$", value, flags=re.DOTALL)
        return _MATH_SPAN_RE.sub(lambda match: f"${repair_math_body(match.group(1))}$", value)

    for question in questions:
        if isinstance(question.get("question"), str):
            question["question"] = normalize(question["question"])
        if isinstance(question.get("explanation"), str):
            question["explanation"] = normalize(question["explanation"])
        if isinstance(question.get("options"), dict):
            question["options"] = {
                key: normalize(value) if isinstance(value, str) else value
                for key, value in question["options"].items()
            }


def normalize_code_fences(quiz_data: dict) -> None:
    """Repair common LLM code-block escapes and malformed language fences."""
    questions = quiz_data.get("questions")
    if not isinstance(questions, list):
        return

    for question in questions:
        if question.get("modality") != AssessmentModality.CODE.value:
            continue
        prompt = question.get("question")
        if not isinstance(prompt, str):
            continue

        # Models occasionally return the two characters ``\n`` around code even
        # though the surrounding JSON has already been decoded.
        prompt = prompt.replace(r"\n", "\n")
        # Turn a one-backtick language block into an ordinary fenced block.
        prompt = re.sub(
            r"(?ms)(?<!`)`(?:python|py|r)\s*\n(.*?)\n`(?!`)",
            lambda match: f"```python\n{match.group(1).rstrip()}\n```",
            prompt,
        )
        prompt = re.sub(
            r"(?is)```(?:python|py|r)?\s*\n(.*?)```",
            lambda match: f"```python\n{match.group(1).rstrip()}\n```",
            prompt,
        )

        # Some otherwise valid model responses put the snippet in a separate
        # JSON field. Fold it into the student-facing prompt so it is rendered.
        if "```" not in prompt:
            for field in ("code", "code_snippet", "snippet"):
                snippet = question.get(field)
                if not isinstance(snippet, str) or not snippet.strip():
                    continue
                snippet = snippet.replace(r"\n", "\n").strip()
                snippet = re.sub(r"^```(?:python|py|r)?\s*|\s*```$", "", snippet, flags=re.IGNORECASE)
                prompt = f"{prompt.rstrip()}\n\n```python\n{snippet}\n```"
                break
        # Repair indented code emitted without a fence. Require at least two
        # code-like lines so ordinary prose is not accidentally fenced.
        if "```" not in prompt:
            lines = prompt.splitlines()
            code_indices = [
                index for index, line in enumerate(lines)
                if re.match(
                    r"^\s*(?:import\s+|from\s+\S+\s+import\s+|#|print\s*\(|"
                    r"[A-Za-z_]\w*\s*=|for\s+|while\s+|if\s+|def\s+|return\s+)",
                    line,
                )
            ]
            if len(code_indices) >= 2:
                start, end = min(code_indices), max(code_indices)
                code = "\n".join(lines[start : end + 1]).strip()
                lines[start : end + 1] = [f"```python\n{code}\n```"]
                prompt = "\n".join(lines)
        question["question"] = prompt


def normalize_plot_specs(quiz_data: dict, plan: dict) -> None:
    """Make generated plots safe and expand underspecified clustering data."""
    questions = quiz_data.get("questions")
    requirements = plan.get("requirements", [])
    if not isinstance(questions, list):
        return

    for question, expected in zip(questions, requirements):
        if expected.get("modality") != AssessmentModality.PLOT_INTERPRETATION.value:
            continue
        spec = question.get("plot_spec")
        if not isinstance(spec, dict):
            continue

        # Titles are never pedagogical inputs: discard them deterministically
        # rather than spending another LLM attempt repairing presentation.
        spec["title"] = ""
        prompt = question.get("question")
        if isinstance(prompt, str):
            prompt = re.sub(
                r"(?im)^\s*(?:plot\s+points?|data\s+points?|coordinates?)\s*:.*(?:\n|$)",
                "",
                prompt,
            )
            prompt = re.sub(
                r"(?i)\s*(?:plot\s+points?|data\s+points?|coordinates?)\s*:\s*"
                r"(?:\([^)]*\)[,;\s]*)+",
                " ",
                prompt,
            )
            prompt = re.sub(
                r'(?is)\{\s*["\']x["\']\s*:\s*\[[^]]*\]\s*,\s*["\']y["\']\s*:\s*\[[^]]*\]\s*\}',
                "",
                prompt,
            )
            prompt = re.sub(
                r"(?im)^\s*[-*]?\s*[XY]\s+values?\s*:\s*\[[^]]*\]\s*$",
                "",
                prompt,
            )
            prompt = re.sub(
                r"(?i)(?:\s*\([-+]?\d+(?:\.\d+)?\s*,\s*[-+]?\d+(?:\.\d+)?\)\s*[,;-]?){2,}",
                " ",
                prompt,
            )
            question["question"] = re.sub(r"\n{3,}", "\n\n", prompt).strip()
        grounding_text = " ".join(
            str(value) for value in (
                question.get("question", ""),
                expected.get("topic", ""),
                expected.get("learning_outcome", {}).get("statement", ""),
            )
        ).lower()
        if any(term in grounding_text for term in (
            "cluster", "classification", "regression", "relationship", "statistical learning",
            "supervised", "unsupervised", "dimensionality reduction",
        )):
            spec["plot_type"] = "scatter"
        elif any(term in grounding_text for term in (
            "distribution", "dispersion", "skew", "kurtosis", "histogram", "mode", "median"
        )):
            spec["plot_type"] = "histogram"
        if isinstance(question.get("question"), str):
            if spec.get("plot_type") == "scatter":
                question["question"] = re.sub(
                    r"(?i)\bhistogram(?:\s+data)?\b", "scatter plot", question["question"]
                )
            elif spec.get("plot_type") == "histogram":
                question["question"] = re.sub(
                    r"(?i)\bscatter\s*plot\b", "histogram", question["question"]
                )
        if "cluster" not in grounding_text:
            continue

        x_values = spec.get("x")
        y_values = spec.get("y")
        if not (
            isinstance(x_values, list)
            and isinstance(y_values, list)
            and len(x_values) == len(y_values)
            and len(x_values) >= 2
            and all(isinstance(value, (int, float)) for value in x_values + y_values)
        ):
            continue

        groups = spec.get("groups")
        if isinstance(groups, list) and len(groups) == len(x_values) and len(set(map(str, groups))) >= 2 and len(x_values) >= 30:
            continue

        # Treat the supplied observations as cluster centers and add fixed,
        # symmetric offsets. This produces a reproducible point cloud without
        # introducing randomness or requiring another model response.
        centers = list(zip(x_values[:3], y_values[:3]))
        if len(centers) < 2:
            continue
        offsets = (
            (-0.24, -0.10), (-0.20, 0.12), (-0.14, -0.20), (-0.10, 0.22),
            (-0.04, -0.04), (0.02, 0.16), (0.08, -0.18), (0.12, 0.06),
            (0.16, 0.20), (0.20, -0.08), (0.24, 0.10), (0.05, 0.28),
            (-0.08, -0.28), (0.28, -0.22), (-0.28, 0.24),
        )
        spec["x"] = [round(cx + dx, 6) for cx, _ in centers for dx, _ in offsets]
        spec["y"] = [round(cy + dy, 6) for _, cy in centers for _, dy in offsets]
        spec["groups"] = [group for group in range(len(centers)) for _ in offsets]


def normalize_choice_fields(quiz_data: dict, plan: dict) -> None:
    """Canonicalize common model variants of A-D options and answer labels."""
    questions = quiz_data.get("questions")
    requirements = plan.get("requirements", [])
    if not isinstance(questions, list):
        return

    letters = ("A", "B", "C", "D")
    for question, expected in zip(questions, requirements):
        if expected.get("question_kind") not in {
            QuestionKind.SINGLE_CHOICE.value,
            QuestionKind.MULTIPLE_SELECT.value,
        }:
            continue

        options = question.get("options")
        if options is None:
            options = question.get("choices", question.get("answer_choices"))
        if isinstance(options, list) and len(options) == 4:
            if all(isinstance(option, dict) for option in options):
                option_values = [
                    option.get("text", option.get("value", option.get("option")))
                    for option in options
                ]
                options = dict(zip(letters, option_values))
            else:
                options = dict(zip(letters, options))
        elif isinstance(options, dict) and len(options) == 4:
            canonical: dict[str, object] = {}
            for index, (key, value) in enumerate(options.items()):
                raw_key = str(key).strip().upper().rstrip(".)")
                raw_key = re.sub(r"^(?:OPTION|CHOICE)[_\s-]*", "", raw_key)
                if raw_key in letters:
                    canonical[raw_key] = value
                elif raw_key in {"1", "2", "3", "4"}:
                    canonical[letters[int(raw_key) - 1]] = value
                else:
                    canonical[letters[index]] = value
            if set(canonical) == set(letters):
                options = canonical
        question["options"] = options

        answers = question.get("correct_answers")
        if answers is None:
            answers = question.get("correct_answer", question.get("answer"))
        if isinstance(answers, str) and re.fullmatch(r"\s*[A-D1-4](?:\s*[,;/]\s*[A-D1-4])+\s*", answers, re.IGNORECASE):
            answers = re.split(r"\s*[,;/]\s*", answers.strip())
        if not isinstance(answers, list):
            answers = [answers] if answers is not None else []
        normalized_answers: list[str] = []
        for answer in answers:
            if isinstance(answer, int) and 1 <= answer <= 4:
                normalized_answers.append(letters[answer - 1])
                continue
            raw_answer = str(answer).strip()
            label = raw_answer.upper().rstrip(".)")
            if label in letters:
                normalized_answers.append(label)
                continue
            if label in {"1", "2", "3", "4"}:
                normalized_answers.append(letters[int(label) - 1])
                continue
            if isinstance(options, dict):
                matching = [
                    letter for letter, text in options.items()
                    if str(text).strip().casefold() == raw_answer.casefold()
                ]
                if len(matching) == 1:
                    normalized_answers.append(matching[0])
        question["correct_answers"] = list(dict.fromkeys(normalized_answers))


def extract_learning_outcomes(files: Iterable[Path], root: Path) -> list[LearningOutcome]:
    outcomes: list[LearningOutcome] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines = text.splitlines()
        outcome_heading_index: int | None = None
        outcome_heading_level: int | None = None
        for index, line in enumerate(lines):
            heading = re.match(r"^\s*(#{1,6})\s+(.+?)\s*$", line)
            if heading and re.search(r"(?i)\b(?:learning outcomes?|learning objectives?|objectives?)\b", heading.group(2)):
                outcome_heading_index = index
                outcome_heading_level = len(heading.group(1))
                break

        category: str | None = None
        for index, line in enumerate(lines):
            if outcome_heading_index is not None:
                if index <= outcome_heading_index:
                    continue
                heading_match = re.match(r"^\s*(#{1,6})\s+", line)
                if heading_match and len(heading_match.group(1)) <= (outcome_heading_level or 6):
                    break
            heading = _HEADING_RE.match(line)
            if heading:
                category = heading.group(1).strip()
                continue
            bullet = _BULLET_RE.match(line)
            if not bullet:
                continue
            statement = bullet.group(1).strip()
            category_bullet = re.fullmatch(r"\*\*([^*]+)\*\*:?", statement)
            if category_bullet:
                category = category_bullet.group(1).strip()
                continue
            if len(statement.split()) < 3:
                continue
            outcomes.append(
                LearningOutcome(
                    identifier=f"LO-{len(outcomes) + 1}",
                    statement=statement,
                    category=category,
                    source=str(path.relative_to(root)),
                )
            )
    if outcomes:
        return outcomes
    return [
        LearningOutcome(
            identifier="LO-1",
            statement="Explain and apply the central concepts in the selected course materials.",
        )
    ]


def _question_kinds(style: str, count: int) -> list[QuestionKind]:
    if style == "open":
        return [QuestionKind.OPEN_ENDED] * count
    if style != "mixed":
        raise ValueError("question_style must be one of: mixed, open")
    if count < 2:
        raise ValueError("mixed quizzes require at least 2 questions")

    sata_count = min(count - 1, max(1, math.floor(count * 0.3 + 0.5)))

    # Spread SATA questions through the quiz rather than clustering them.
    sata_positions = {
        min(count - 1, math.floor((index + 0.5) * count / sata_count))
        for index in range(sata_count)
    }
    while len(sata_positions) < sata_count:
        sata_positions.add(next(i for i in range(count) if i not in sata_positions))
    return [
        QuestionKind.MULTIPLE_SELECT if index in sata_positions else QuestionKind.SINGLE_CHOICE
        for index in range(count)
    ]


def build_blueprint(
    *,
    num_versions: int,
    num_questions: int,
    question_style: str,
    topics: Sequence[str],
    learning_outcomes: Sequence[LearningOutcome],
) -> QuizBlueprint:
    if num_versions < 1:
        raise ValueError("num_versions must be at least 1")
    if num_questions < 1:
        raise ValueError("num_questions must be at least 1")

    normalized_topics = tuple(topic.strip() for topic in topics if topic.strip()) or ("course foundations",)
    normalized_outcomes = tuple(learning_outcomes) or (
        LearningOutcome("LO-1", "Explain and apply the selected course concepts."),
    )
    if len(normalized_outcomes) > num_questions:
        raise ValueError(
            f"num_questions must be at least {len(normalized_outcomes)} to assess every supplied learning outcome"
        )
    kinds = _question_kinds(question_style, num_questions)
    difficulty_cycle = (
        Difficulty.FOUNDATIONAL,
        Difficulty.INTERMEDIATE,
        Difficulty.INTERMEDIATE,
        Difficulty.ADVANCED,
    )
    modality_cycle = (
        AssessmentModality.CONCEPTUAL,
        AssessmentModality.FORMULA,
        AssessmentModality.CODE,
        AssessmentModality.PLOT_INTERPRETATION,
    )
    slots = tuple(
        BlueprintSlot(
            number=index + 1,
            topic=normalized_topics[index % len(normalized_topics)],
            learning_outcome=normalized_outcomes[index % len(normalized_outcomes)],
            question_kind=kinds[index],
            difficulty=difficulty_cycle[index % len(difficulty_cycle)],
            modality=modality_cycle[index % len(modality_cycle)],
        )
        for index in range(num_questions)
    )
    return QuizBlueprint(
        num_versions=num_versions,
        num_questions=num_questions,
        question_style=question_style,
        topics=normalized_topics,
        slots=slots,
    )


def validate_generated_quiz(quiz_data: dict, plan: dict) -> list[str]:
    """Return deterministic contract violations for one generated version."""
    errors: list[str] = []
    questions = quiz_data.get("questions")
    requirements = plan["requirements"]
    if not isinstance(questions, list):
        return ["questions must be a list"]
    if len(questions) != len(requirements):
        errors.append(f"expected {len(requirements)} questions, received {len(questions)}")
        return errors

    for expected, question in zip(requirements, questions):
        number = expected["number"]
        if question.get("number") != number:
            errors.append(f"question {number}: number does not match blueprint")
        if question.get("question_kind") != expected["question_kind"]:
            errors.append(f"question {number}: question_kind does not match blueprint")
        if question.get("modality") != expected["modality"]:
            errors.append(f"question {number}: modality does not match blueprint")
        if not str(question.get("question", "")).strip():
            errors.append(f"question {number}: prompt is empty")
        answers = question.get("correct_answers")
        if not isinstance(answers, list) or not answers:
            errors.append(f"question {number}: correct_answers must be a non-empty list")
        kind = expected["question_kind"]
        options = question.get("options")
        if kind in {QuestionKind.SINGLE_CHOICE.value, QuestionKind.MULTIPLE_SELECT.value}:
            if not isinstance(options, dict) or set(options) != {"A", "B", "C", "D"}:
                errors.append(f"question {number}: choice questions require options A-D")
            if kind == QuestionKind.SINGLE_CHOICE.value and isinstance(answers, list) and len(answers) != 1:
                errors.append(f"question {number}: single-choice questions require one answer")
            if kind == QuestionKind.MULTIPLE_SELECT.value and isinstance(answers, list) and len(answers) < 2:
                errors.append(f"question {number}: multiple-select questions require at least two answers")
            if isinstance(answers, list) and any(answer not in {"A", "B", "C", "D"} for answer in answers):
                errors.append(f"question {number}: choice answers must be letters A-D")
        elif options not in (None, {}):
            errors.append(f"question {number}: open-ended questions must not have options")
        if expected["modality"] == AssessmentModality.PLOT_INTERPRETATION.value:
            plot_spec = question.get("plot_spec")
            if not isinstance(plot_spec, dict):
                errors.append(f"question {number}: plot questions require a plot_spec object")
            else:
                x_values = plot_spec.get("x")
                y_values = plot_spec.get("y")
                plot_type = plot_spec.get("plot_type")
                title = plot_spec.get("title")
                if plot_type not in {"line", "scatter", "bar", "histogram"}:
                    errors.append(f"question {number}: plot_type must be line, scatter, bar, or histogram")
                if not isinstance(x_values, list) or (plot_type != "histogram" and not isinstance(y_values, list)):
                    errors.append(f"question {number}: plot_spec requires numeric x values and y values except for histograms")
                elif len(x_values) < 2 or (plot_type != "histogram" and len(x_values) != len(y_values)):
                    errors.append(f"question {number}: plot_spec values have an invalid length")
                elif any(not isinstance(value, (int, float)) for value in x_values + (y_values if isinstance(y_values, list) else [])):
                    errors.append(f"question {number}: plot_spec x and y values must be numeric")
                if title not in (None, ""):
                    errors.append(f"question {number}: generated plots must not have titles")

                prompt_text = str(question.get("question", ""))
                exposes_data = (
                    re.search(r"(?i)(?:plot\s+points?|data\s+points?|coordinates?|[xy]\s+values?)\s*:", prompt_text)
                    or re.search(r'(?i)["\']?[xy]["\']?\s*:\s*\[[^]]+\]', prompt_text)
                    or len(re.findall(r"\([-+]?\d+(?:\.\d+)?\s*,\s*[-+]?\d+(?:\.\d+)?\)", prompt_text)) >= 2
                )
                if exposes_data:
                    errors.append(f"question {number}: plot questions must not expose raw plotted data")

                grounding_text = " ".join(
                    str(value) for value in (
                        question.get("question", ""),
                        expected.get("topic", ""),
                        expected.get("learning_outcome", {}).get("statement", ""),
                    )
                ).lower()
                if "cluster" in grounding_text:
                    groups = plot_spec.get("groups")
                    if not isinstance(x_values, list) or len(x_values) < 30:
                        errors.append(f"question {number}: clustering plots require at least 30 points")
                    if (
                        not isinstance(groups, list)
                        or not isinstance(x_values, list)
                        or len(groups) != len(x_values)
                        or len(set(map(str, groups))) < 2
                    ):
                        errors.append(
                            f"question {number}: clustering plots require a groups list with at least two groups"
                        )

        if expected["modality"] == AssessmentModality.CODE.value:
            code_text = str(question.get("question", ""))
            has_fenced_code = re.search(
                r"```(?:python|py|r)?\s*\n.+?\n```", code_text, re.DOTALL | re.IGNORECASE
            )
            if not has_fenced_code:
                errors.append(f"question {number}: code questions require a fenced code block in the prompt")
            option_text = "\n".join(
                str(value) for value in question.get("options", {}).values()
            ) if isinstance(question.get("options"), dict) else ""
            if "```" in option_text or re.search(
                r"(?im)(?:^|<br>)\s*(?:import |from \w+ import |\w+\s*=|if |for |while |print\s*\()",
                option_text,
            ):
                errors.append(f"question {number}: code must be in the prompt and answer choices must be prose")
    return errors
