"""Deterministic assessment planning shared by every generated quiz version."""

from __future__ import annotations

import json
import math
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
        return {
            "version": version,
            "requirements": [
                {
                    **asdict(slot),
                    "question_kind": slot.question_kind.value,
                    "difficulty": slot.difficulty.value,
                    "modality": slot.modality.value,
                }
                for slot in self.slots
            ],
        }

    def to_dict(self) -> dict:
        return {
            "num_versions": self.num_versions,
            "num_questions": self.num_questions,
            "question_style": self.question_style,
            "topics": list(self.topics),
            "slots": self.version_plan(1)["requirements"],
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


_BULLET_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(.+?)\s*$")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")
_SINGLE_DOLLAR_MATH_RE = re.compile(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", re.DOTALL)


def _question_text_values(question: dict) -> list[str]:
    values = [question.get("question", ""), question.get("explanation", "")]
    options = question.get("options")
    if isinstance(options, dict):
        values.extend(options.values())
    return [value for value in values if isinstance(value, str)]


def normalize_formula_delimiters(quiz_data: dict, plan: dict) -> None:
    """Normalize generated display math in formula slots to Markdown $$ blocks."""
    questions = quiz_data.get("questions")
    if not isinstance(questions, list):
        return
    modalities = {item["number"]: item["modality"] for item in plan["requirements"]}
    for question in questions:
        if modalities.get(question.get("number")) != AssessmentModality.FORMULA.value:
            continue
        if "$$" in "\n".join(_question_text_values(question)):
            continue

        def normalize(value: str) -> str:
            value = re.sub(r"\\\[(.*?)\\\]", r"$$\1$$", value, flags=re.DOTALL)
            value = re.sub(r"\\\((.*?)\\\)", r"$$\1$$", value, flags=re.DOTALL)
            return _SINGLE_DOLLAR_MATH_RE.sub(r"$$\1$$", value)

        if isinstance(question.get("question"), str):
            question["question"] = normalize(question["question"])
        if isinstance(question.get("explanation"), str):
            question["explanation"] = normalize(question["explanation"])
        if isinstance(question.get("options"), dict):
            question["options"] = {
                key: normalize(value) if isinstance(value, str) else value
                for key, value in question["options"].items()
            }


def extract_learning_outcomes(files: Iterable[Path], root: Path) -> list[LearningOutcome]:
    outcomes: list[LearningOutcome] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        category: str | None = None
        for line in text.splitlines():
            heading = _HEADING_RE.match(line)
            if heading:
                category = heading.group(1).strip()
                continue
            bullet = _BULLET_RE.match(line)
            if not bullet:
                continue
            statement = bullet.group(1).strip()
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
    return errors
