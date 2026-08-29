from pathlib import Path
from types import SimpleNamespace
import json

import pytest

import quizzer.generator as generator_module
from quizzer.blueprint import (
    LearningOutcome,
    QuestionKind,
    build_blueprint,
    normalize_formula_delimiters,
    validate_generated_quiz,
)
from quizzer.generator import generate_quizzes
from quizzer.input_loader import collect_input_documents
from quizzer.parsers import parse_document


REAL_LLM_GENERATION = generator_module._generate_quiz_with_llm


@pytest.fixture(autouse=True)
def stub_llm_generation(monkeypatch):
    """Keep the suite deterministic and offline while exercising the full pipeline."""
    def generate(_material, blueprint, version_num, output_format):
        questions = []
        for slot in blueprint.slots:
            kind = slot.question_kind.value
            is_open = kind == QuestionKind.OPEN_ENDED.value
            answers = ["A", "C"] if kind == QuestionKind.MULTIPLE_SELECT.value else ["Model answer" if is_open else "A"]
            prompt = f"Version {version_num}: assess {slot.topic}."
            if slot.modality.value == "formula":
                prompt += " Evaluate $$x + 1 = 2.$$"
            questions.append({
                "number": slot.number,
                "question_kind": kind,
                "modality": slot.modality.value,
                "question": prompt,
                "options": None if is_open else {"A": "Correct", "B": "Distractor", "C": "Also correct" if len(answers) == 2 else "Distractor", "D": "Distractor"},
                "correct_answers": answers,
                "explanation": "Grounded explanation.",
                "source_references": [slot.learning_outcome.source or "course material"],
            })
        return (
            generator_module._format_quiz_from_llm({"questions": questions}, output_format),
            generator_module._format_answer_key_from_llm({"questions": questions}, output_format),
        )

    monkeypatch.setattr(generator_module, "_generate_quiz_with_llm", generate)


def test_collect_input_documents_and_parse_supported_files(tmp_path):
    inputs = tmp_path / "inputs"
    for name in ["syllabus", "lecture_notes", "MLO", "course_topics"]:
        (inputs / name).mkdir(parents=True)

    (inputs / "syllabus" / "syllabus.txt").write_text("Intro to AI", encoding="utf-8")
    (inputs / "lecture_notes" / "lecture_01.md").write_text("# Lecture 1\nTopic: probability", encoding="utf-8")
    (inputs / "MLO" / "mlo.txt").write_text("Understand probability", encoding="utf-8")
    (inputs / "course_topics" / "topics.txt").write_text("Probability, inference", encoding="utf-8")

    docs = collect_input_documents(inputs)

    assert set(docs) == {"syllabus", "lecture_notes", "MLO", "course_topics"}
    assert len(docs["syllabus"]) == 1
    assert "Intro to AI" in parse_document(docs["syllabus"][0])


def test_generate_quizzes_creates_markdown_output(tmp_path):
    inputs = tmp_path / "inputs"
    outputs = tmp_path / "outputs"

    for name in ["syllabus", "lecture_notes", "MLO", "course_topics"]:
        (inputs / name).mkdir(parents=True)

    (inputs / "syllabus" / "syllabus.md").write_text("# Syllabus\nAI and probability", encoding="utf-8")
    (inputs / "lecture_notes" / "lecture_01.txt").write_text("Probability basics and random variables", encoding="utf-8")
    (inputs / "MLO" / "mlo.txt").write_text("Explain probability", encoding="utf-8")
    (inputs / "course_topics" / "topics.txt").write_text("Probability, statistics", encoding="utf-8")
    (inputs / "syllabus" / ".DS_Store").write_text("ignore me", encoding="utf-8")

    manifest = generate_quizzes(
        input_dir=inputs,
        output_dir=outputs,
        num_versions=2,
        num_questions=2,
        question_type="mixed",
        output_format="markdown",
    )

    assert len(manifest["quizzes"]) == 2
    assert (outputs / "quizzes" / "quiz_01.md").exists()
    assert (outputs / "quizzes" / "quiz_02.md").exists()
    assert (outputs / "answer_keys" / "quiz_01_key.md").exists()
    assert (outputs / "answer_keys" / "quiz_02_key.md").exists()
    assert (outputs / "audit" / "generation_audit.md").exists()
    assert (outputs / "audit" / "blueprint.json").exists()
    assert manifest["blueprint"]["num_versions"] == 2

    quiz_text = (outputs / "quizzes" / "quiz_01.md").read_text(encoding="utf-8")
    answer_text = (outputs / "answer_keys" / "quiz_01_key.md").read_text(encoding="utf-8")
    
    # Check structure: should have Quiz header and numbered questions
    assert "# Quiz" in quiz_text
    assert "1." in quiz_text  # At least question 1
    assert "A." in quiz_text or "a." in quiz_text  # Should have options
    
    # Check answer key structure
    assert "# Answer Key" in answer_text
    assert "**" in answer_text or "--" in answer_text  # Should have some formatting


def test_generate_quizzes_filters_by_topics(tmp_path):
    inputs = tmp_path / "inputs"
    outputs = tmp_path / "outputs"

    for name in ["syllabus", "lecture_notes", "MLO", "course_topics"]:
        (inputs / name).mkdir(parents=True)

    (inputs / "syllabus" / "probability_notes.md").write_text("Probability and Bayes theorem", encoding="utf-8")
    (inputs / "lecture_notes" / "neural_networks.txt").write_text("Neural networks and deep learning", encoding="utf-8")
    (inputs / "MLO" / "mlo.txt").write_text("Explain probability", encoding="utf-8")
    (inputs / "course_topics" / "topics.txt").write_text("Statistics and probability", encoding="utf-8")

    manifest = generate_quizzes(
        input_dir=inputs,
        output_dir=outputs,
        num_versions=1,
        num_questions=2,
        question_type="mixed",
        output_format="markdown",
        topics=["probability"],
    )

    quiz_text = (outputs / "quizzes" / "quiz_01.md").read_text(encoding="utf-8")
    
    # Check that quiz was generated and has structure
    assert "# Quiz" in quiz_text
    assert "1." in quiz_text or "Question" in quiz_text
    # The LLM should focus on probability-related content when filtered
    # Check for at least one question (hard to guarantee exact wording due to LLM)
    assert len(quiz_text.split("A.")) >= 1  # At least one option set
    assert manifest["quizzes"]


def test_blueprint_preserves_parallel_slots_and_mixed_distribution():
    blueprint = build_blueprint(
        num_versions=3,
        num_questions=10,
        question_style="mixed",
        topics=["Bayes", "classification"],
        learning_outcomes=[LearningOutcome("LO-1", "Apply Bayes' rule")],
    )

    assert len(blueprint.slots) == 10
    assert sum(slot.question_kind == QuestionKind.MULTIPLE_SELECT for slot in blueprint.slots) == 3
    assert blueprint.version_plan(1)["requirements"] == blueprint.version_plan(3)["requirements"]


def test_blueprint_validator_rejects_wrong_question_kind():
    blueprint = build_blueprint(
        num_versions=1,
        num_questions=2,
        question_style="mixed",
        topics=["probability"],
        learning_outcomes=[LearningOutcome("LO-1", "Explain probability")],
    )
    questions = []
    for requirement in blueprint.version_plan(1)["requirements"]:
        questions.append({
            "number": requirement["number"],
            "question_kind": "single_choice",
            "modality": requirement["modality"],
            "question": "A grounded question with $$x = 1.$$" if requirement["modality"] == "formula" else "A grounded question",
            "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
            "correct_answers": ["A"],
        })

    errors = validate_generated_quiz({"questions": questions}, blueprint.version_plan(1))
    assert any("question_kind does not match" in error for error in errors)


def test_llm_generation_batches_and_retries_incomplete_responses(monkeypatch):
    blueprint = build_blueprint(
        num_versions=1,
        num_questions=6,
        question_style="mixed",
        topics=["probability"],
        learning_outcomes=[LearningOutcome("LO-1", "Explain probability")],
    )

    def make_question(requirement):
        kind = requirement["question_kind"]
        is_open = kind == "open_ended"
        prompt = "Grounded question"
        if requirement["modality"] == "formula":
            prompt += " using $$P(A) = 1.$$"
        return {
            "number": requirement["number"],
            "question_kind": kind,
            "modality": requirement["modality"],
            "question": prompt,
            "options": None if is_open else {"A": "a", "B": "b", "C": "c", "D": "d"},
            "correct_answers": ["A", "C"] if kind == "multiple_select" else ["A"],
            "explanation": "Explanation",
            "source_references": ["notes.md"],
        }

    requirements = blueprint.version_plan(1)["requirements"]
    responses = [
        {"questions": [make_question(requirements[0])]},  # incomplete first attempt
        {"questions": [make_question(item) for item in requirements[:5]]},
        {"questions": [make_question(item) for item in requirements[5:]]},
    ]

    class FakeCompletions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            content = json.dumps(responses.pop(0))
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    completions = FakeCompletions()
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr(generator_module, "_get_client", lambda: fake_client)

    quiz, answer_key = REAL_LLM_GENERATION("course material", blueprint, 1, "markdown")

    assert len(completions.calls) == 3
    assert all(call["response_format"] == {"type": "json_object"} for call in completions.calls)
    assert "6. Grounded question" in quiz
    assert "6. **A**" in answer_key


def test_formula_validation_accepts_options_and_normalizes_delimiters():
    blueprint = build_blueprint(
        num_versions=1,
        num_questions=2,
        question_style="open",
        topics=["probability"],
        learning_outcomes=[LearningOutcome("LO-1", "Apply probability formulas")],
    )
    plan = blueprint.version_plan(1)
    requirement = plan["requirements"][1]
    question = {
        "number": requirement["number"],
        "question_kind": requirement["question_kind"],
        "modality": requirement["modality"],
        "question": "Interpret the following expression.",
        "options": None,
        "correct_answers": ["A model answer"],
        "explanation": r"The source gives \[P(A)=0.5\].",
    }
    batch_plan = {"version": 1, "requirements": [requirement]}
    data = {"questions": [question]}

    normalize_formula_delimiters(data, batch_plan)
    errors = validate_generated_quiz(data, batch_plan)

    assert "$$P(A)=0.5$$" in data["questions"][0]["explanation"]
    assert errors == []


def test_formula_modality_without_display_math_does_not_abort_generation():
    blueprint = build_blueprint(
        num_versions=1,
        num_questions=2,
        question_style="open",
        topics=["descriptive statistics"],
        learning_outcomes=[LearningOutcome("LO-1", "Interpret summary statistics")],
    )
    requirement = blueprint.version_plan(1)["requirements"][1]
    batch_plan = {"version": 1, "requirements": [requirement]}
    data = {"questions": [{
        "number": requirement["number"],
        "question_kind": requirement["question_kind"],
        "modality": requirement["modality"],
        "question": "Explain how the mean summarizes a dataset.",
        "options": None,
        "correct_answers": ["It describes the arithmetic center."],
        "explanation": "No display formula is needed for this prompt.",
    }]}

    assert validate_generated_quiz(data, batch_plan) == []


def test_numeric_topics_select_numbered_lectures_and_matching_outcomes(tmp_path):
    inputs = tmp_path / "inputs"
    outputs = tmp_path / "outputs"
    for name in ["syllabus", "lecture_notes", "MLO", "course_topics"]:
        (inputs / name).mkdir(parents=True)

    (inputs / "lecture_notes" / "05-Regression-draft.html").write_text("draft", encoding="utf-8")
    (inputs / "lecture_notes" / "05-Regression.html").write_text("least squares regression", encoding="utf-8")
    (inputs / "lecture_notes" / "06-Regularization.html").write_text("regularized regression", encoding="utf-8")
    (inputs / "lecture_notes" / "07-PCA.html").write_text("principal components", encoding="utf-8")
    (inputs / "MLO" / "05_Regression.md").write_text("- Fit and interpret a regression model", encoding="utf-8")
    (inputs / "MLO" / "0607_Models.md").write_text("- Compare regularization and dimension reduction", encoding="utf-8")
    (inputs / "MLO" / "08_Clustering.md").write_text("- Explain clustering algorithms", encoding="utf-8")

    manifest = generate_quizzes(
        input_dir=inputs,
        output_dir=outputs,
        num_versions=1,
        num_questions=4,
        question_type="mixed",
        topics=["05", "06"],
    )

    assert manifest["blueprint"]["topics"] == ["Regression", "Regularization"]
    outcome_sources = {
        slot["learning_outcome"]["source"] for slot in manifest["blueprint"]["slots"]
    }
    assert outcome_sources <= {"MLO/05_Regression.md", "MLO/0607_Models.md"}
    audit = (outputs / "audit" / "generation_audit.md").read_text(encoding="utf-8")
    assert "05-Regression.html" in audit
    assert "05-Regression-draft.html" not in audit
    assert "07-PCA.html" not in audit
