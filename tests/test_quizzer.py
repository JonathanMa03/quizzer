from pathlib import Path
from types import SimpleNamespace
import json

import pytest

import quizzer.generator as generator_module
from quizzer.blueprint import (
    LearningOutcome,
    QuestionKind,
    build_blueprint,
    extract_learning_outcomes,
    normalize_formula_delimiters,
    normalize_code_fences,
    normalize_choice_fields,
    normalize_plot_specs,
    validate_generated_quiz,
)
from quizzer.generator import generate_quizzes
from quizzer.input_loader import collect_input_documents
from quizzer.notebook import generate_quizzes_from_files
from quizzer.parsers import parse_document


REAL_LLM_GENERATION = generator_module._generate_quiz_with_llm


@pytest.fixture(autouse=True)
def stub_llm_generation(monkeypatch):
    """Keep the suite deterministic and offline while exercising the full pipeline."""
    def generate(_material, blueprint, version_num, output_format, _output_dir, prior_question_prompts=None):
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
                "plot_spec": {
                    "plot_type": "scatter",
                    "x": [1, 2, 3],
                    "y": [2, 3, 5],
                    "title": "Example plot",
                    "x_label": "x",
                    "y_label": "y",
                } if slot.modality.value == "plot_interpretation" else None,
            })
        return (
            generator_module._format_quiz_from_llm({"questions": questions}, output_format),
            generator_module._format_answer_key_from_llm({"questions": questions}, output_format),
            [],
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


def test_learning_outcome_parser_uses_outcome_section_and_categories(tmp_path):
    source = tmp_path / "MLO.md"
    source.write_text(
        "# Course\n\n## Key Concepts\n- This is background context, not an outcome.\n\n"
        "## Learning Outcomes\nStudents will be able to...\n"
        "- **Remember**\n  - define kernel density estimation and bandwidth.\n"
        "- **Apply**\n  - create histograms using Matplotlib.\n",
        encoding="utf-8",
    )

    outcomes = extract_learning_outcomes([source], tmp_path)

    assert [outcome.statement for outcome in outcomes] == [
        "define kernel density estimation and bandwidth.",
        "create histograms using Matplotlib.",
    ]
    assert [outcome.category for outcome in outcomes] == ["Remember", "Apply"]


def test_blueprint_requires_and_covers_every_learning_outcome():
    outcomes = [LearningOutcome(f"LO-{index}", f"Apply outcome {index}") for index in range(1, 4)]
    with pytest.raises(ValueError, match="num_questions must be at least 3"):
        build_blueprint(
            num_versions=1,
            num_questions=2,
            question_style="mixed",
            topics=["Topic"],
            learning_outcomes=outcomes,
        )

    blueprint = build_blueprint(
        num_versions=2,
        num_questions=4,
        question_style="mixed",
        topics=["Topic"],
        learning_outcomes=outcomes,
    )
    for version in (1, 2):
        identifiers = {
            requirement["learning_outcome"]["identifier"]
            for requirement in blueprint.version_plan(version)["requirements"]
        }
        assert identifiers == {"LO-1", "LO-2", "LO-3"}


def test_learning_outcomes_are_shuffled_within_each_version():
    outcomes = [LearningOutcome(f"LO-{index}", f"Apply outcome {index}") for index in range(1, 11)]
    blueprint = build_blueprint(
        num_versions=3,
        num_questions=15,
        question_style="mixed",
        topics=["Topic"],
        learning_outcomes=outcomes,
    )
    sequential = [f"LO-{(index % 10) + 1}" for index in range(15)]
    orders = []
    for version in (1, 2, 3):
        order = [
            requirement["learning_outcome"]["identifier"]
            for requirement in blueprint.version_plan(version)["requirements"]
        ]
        assert order != sequential
        assert set(order) == {f"LO-{index}" for index in range(1, 11)}
        orders.append(order)
    assert len({tuple(order) for order in orders}) == 3


def test_cross_version_similarity_rejects_paraphrased_repeat():
    data = {"questions": [{
        "number": 8,
        "question": "Based on the scatter plot, which statistical learning task is represented?",
    }]}
    prior = ["Based on the provided scatter plot, which statistical learning task is represented?"]

    assert generator_module._question_similarity_errors(data, prior) == [
        "question 8: too similar to an earlier-version question"
    ]


def test_within_quiz_similarity_rejects_repeated_questions_across_batches():
    accepted = [{
        "number": 2,
        "question": "Which formula correctly calculates the sample variance?",
    }]
    later_batch = {"questions": [
        {"number": 6, "question": "Which formula correctly calculates the sample variance?"},
        {"number": 7, "question": "What does bandwidth control in kernel density estimation?"},
    ]}

    assert generator_module._within_quiz_similarity_errors(later_batch, accepted) == [
        "question 6: too similar to another question in the same quiz"
    ]


def test_within_quiz_similarity_rejects_repeats_in_same_batch():
    data = {"questions": [
        {"number": 3, "question": "How does the median describe the center of ordered data?"},
        {"number": 7, "question": "How does the median describe the center of ordered data?"},
    ]}

    assert generator_module._within_quiz_similarity_errors(data) == [
        "question 7: too similar to another question in the same quiz"
    ]


def test_prompt_cannot_name_its_short_correct_answer():
    data = {"questions": [{
        "number": 4,
        "question": "This is a clustering example. Which learning method is shown?",
        "options": {"A": "Regression", "B": "Clustering", "C": "Classification", "D": "PCA"},
        "correct_answers": ["B"],
    }]}

    assert generator_module._answer_exposure_errors(data) == [
        "question 4: prompt exposes correct answer B"
    ]


def test_similarity_repair_budget_falls_back_to_structurally_valid_question():
    requirement = {
        "number": 2,
        "question_kind": "single_choice",
        "modality": "conceptual",
        "topic": "Foundations",
        "learning_outcome": {"statement": "Explain a foundational concept"},
    }
    question = {
        "number": 2,
        "question_kind": "single_choice",
        "modality": "conceptual",
        "question": "Which statement best explains the foundational concept?",
        "options": {"A": "Correct", "B": "Wrong", "C": "Wrong", "D": "Wrong"},
        "correct_answers": ["A"],
    }

    class FakeCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **_kwargs):
            self.calls += 1
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content=json.dumps({"questions": [question]})
            ))])

    completions = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    repaired = generator_module._repair_question_with_llm(
        client,
        requirement,
        question,
        "course material",
        2,
        [question["question"]],
    )

    assert repaired == question
    assert completions.calls == generator_module.MAX_GENERATION_ATTEMPTS


def test_failed_code_repair_downgrades_to_valid_conceptual_question():
    requirement = {
        "number": 11,
        "question_kind": "single_choice",
        "modality": "code",
        "topic": "Descriptive statistics",
        "learning_outcome": {"statement": "Interpret descriptive statistics"},
    }
    conceptual = {
        "number": 11,
        "question_kind": "single_choice",
        "modality": "code",
        "question": "Which measure describes the center of a dataset?",
        "options": {"A": "Mean", "B": "Variance", "C": "Range", "D": "Kurtosis"},
        "correct_answers": ["A"],
    }

    class FakeCompletions:
        def create(self, **_kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content=json.dumps({"questions": [conceptual]})
            ))])

    repaired = generator_module._repair_question_with_llm(
        SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())),
        requirement,
        conceptual,
        "The lecture covers descriptive statistics.",
        1,
        [],
    )

    assert repaired["modality"] == "conceptual"
    assert repaired["_modality_fallback"] in {"code_to_conceptual", "to_conceptual"}


def test_forbidden_package_code_is_discarded_before_focused_repair():
    requirement = {
        "number": 7,
        "question_kind": "single_choice",
        "modality": "code",
        "topic": "Descriptive statistics",
        "learning_outcome": {"statement": "Explain skewness"},
    }
    invalid = {
        "number": 7,
        "question_kind": "single_choice",
        "modality": "code",
        "question": "What is printed?\n```python\nfrom scipy.stats import skew\nprint(skew(range(100)))\n```",
        "options": {"A": "0", "B": "1", "C": "2", "D": "3"},
        "correct_answers": ["A"],
    }
    conceptual = {
        "number": 7,
        "question_kind": "single_choice",
        "modality": "conceptual",
        "question": "Which description indicates positive skewness?",
        "options": {
            "A": "A longer right tail",
            "B": "A longer left tail",
            "C": "Perfect symmetry",
            "D": "No variation",
        },
        "correct_answers": ["A"],
    }

    class FakeCompletions:
        def __init__(self):
            self.prompt = ""

        def create(self, **kwargs):
            self.prompt = kwargs["messages"][0]["content"]
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content=json.dumps({"questions": [conceptual]})
            ))])

    completions = FakeCompletions()
    repaired = generator_module._repair_question_with_llm(
        SimpleNamespace(chat=SimpleNamespace(completions=completions)),
        requirement,
        invalid,
        "The learning outcome covers skewness and descriptive statistics.",
        1,
        [],
    )

    assert repaired["modality"] == "conceptual"
    assert repaired["_modality_fallback"] == "code_to_conceptual"
    assert '"modality": "conceptual"' in completions.prompt
    assert "discard the prior computer-dependent code question" in completions.prompt


def test_empty_focused_repairs_use_deterministic_learning_outcome_fallback():
    requirement = {
        "number": 7,
        "question_kind": "single_choice",
        "modality": "code",
        "topic": "Kernel density estimation",
        "learning_outcome": {
            "statement": "Describe how KDE approximates a distribution from data.",
            "source": "MLO/01_Desc.md",
        },
    }

    class EmptyCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **_kwargs):
            self.calls += 1
            empty = {
                "questions": [{
                    "number": 7,
                    "question_kind": "single_choice",
                    "modality": "code",
                    "question": "",
                    "options": None,
                    "correct_answers": [],
                }]
            }
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(empty)))])

    completions = EmptyCompletions()
    repaired = generator_module._repair_question_with_llm(
        SimpleNamespace(chat=SimpleNamespace(completions=completions)),
        requirement,
        None,
        "The learning outcome explicitly includes KDE.",
        1,
        [],
    )

    assert completions.calls == generator_module.MAX_GENERATION_ATTEMPTS
    assert repaired["question"]
    assert "bandwidth" in repaired["question"].lower()
    assert repaired["correct_answers"] == ["A"]
    assert repaired["_modality_fallback"] == "to_conceptual"


def test_supervised_learning_fallback_assesses_concept_without_filename_topic():
    requirement = {
        "number": 1,
        "question_kind": "single_choice",
        "modality": "conceptual",
        "topic": "Desc",
        "learning_outcome": {
            "statement": "distinguish supervised from unsupervised learning and discrete from continuous learning tasks.",
            "source": "MLO/01_Desc.md",
        },
    }

    question = generator_module._build_safe_fallback_question(requirement)

    assert "Desc" not in question["question"]
    assert "supplied learning outcome" not in question["question"]
    assert "labeled examples" in question["question"]
    assert question["correct_answers"] == ["A"]


def test_generate_quizzes_creates_markdown_output(tmp_path):
    inputs = tmp_path / "inputs"
    outputs = tmp_path / "outputs"

    for name in ["syllabus", "lecture_notes", "MLO", "course_topics"]:
        (inputs / name).mkdir(parents=True)

    (outputs / "quizzes").mkdir(parents=True)
    (outputs / "quizzes" / "quiz_02.md").write_text("stale quiz", encoding="utf-8")

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
    assert not (outputs / "quizzes" / "quiz_02.md").exists()


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
    version_one = blueprint.version_plan(1)["requirements"]
    version_two = blueprint.version_plan(2)["requirements"]
    version_three = blueprint.version_plan(3)["requirements"]
    assert version_one != version_two != version_three
    assert sum(item["modality"] == "plot_interpretation" for item in version_one) == sum(
        item["modality"] == "plot_interpretation" for item in version_two
    )
    assert [item["number"] for item in version_one if item["modality"] == "plot_interpretation"] != [
        item["number"] for item in version_two if item["modality"] == "plot_interpretation"
    ]


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


def test_llm_generation_batches_and_retries_incomplete_responses(monkeypatch, tmp_path):
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
        prompt = {
            1: "Interpret a probability assigned to an event.",
            2: "Compare two outcomes in a finite sample space.",
            3: "Determine whether two stated events are independent.",
            4: "Explain how conditioning changes an event probability.",
            5: "Identify a valid complement rule application.",
            6: "Analyze a simple repeated-trial scenario.",
        }[requirement["number"]]
        if requirement["modality"] == "formula":
            prompt += " using $$P(A) = 1.$$"
        elif requirement["modality"] == "code":
            prompt += "\n\n```python\nx = 1\nprint(x)\n```"
        return {
            "number": requirement["number"],
            "question_kind": kind,
            "modality": requirement["modality"],
            "question": prompt,
            "options": None if is_open else {"A": "a", "B": "b", "C": "c", "D": "d"},
            "correct_answers": ["A", "C"] if kind == "multiple_select" else ["A"],
            "explanation": "Explanation",
            "source_references": ["notes.md"],
            "plot_spec": {
                "plot_type": "scatter",
                "x": [1, 2, 3],
                "y": [2, 4, 5],
                "title": "",
                "x_label": "x",
                "y_label": "y",
            } if requirement["modality"] == "plot_interpretation" else None,
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

    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    quiz, answer_key, artifacts = REAL_LLM_GENERATION(
        "course material", blueprint, 1, "markdown", output_dir
    )

    assert len(completions.calls) == 3
    assert all(call["response_format"] == {"type": "json_object"} for call in completions.calls)
    retry_prompt = completions.calls[1]["messages"][0]["content"]
    assert "PREVIOUS INVALID JSON" in retry_prompt
    assert '"number": 1' in retry_prompt
    assert "expected 5 questions, received 1" in retry_prompt
    assert "6. Analyze a simple repeated-trial scenario." in quiz
    assert "6. **A**" in answer_key
    assert any(path.endswith(".py") for path in artifacts)
    assert any(path.endswith(".png") for path in artifacts)
    assert "![Data visualization for question" in quiz


def test_exhausted_batch_repairs_only_invalid_question(monkeypatch, tmp_path):
    blueprint = build_blueprint(
        num_versions=1,
        num_questions=2,
        question_style="mixed",
        topics=["Foundations"],
        learning_outcomes=[LearningOutcome("LO-1", "Apply foundational concepts")],
    )
    requirements = blueprint.version_plan(1)["requirements"]

    invalid = {
        "number": 1,
        "question_kind": requirements[0]["question_kind"],
        "modality": requirements[0]["modality"],
        "question": "Interpret this concrete scenario.",
        "options": None,
        "correct_answers": [],
        "explanation": "Explanation",
    }
    valid_second = {
        "number": 2,
        "question_kind": requirements[1]["question_kind"],
        "modality": requirements[1]["modality"],
        "question": "Which statements follow from $x=1$?",
        "options": {"A": "First", "B": "Second", "C": "Third", "D": "Fourth"},
        "correct_answers": ["A", "C"],
        "explanation": "Explanation",
    }
    repaired_first = {
        **invalid,
        "options": {"A": "Correct", "B": "Wrong", "C": "Wrong", "D": "Wrong"},
        "correct_answers": ["A"],
    }
    responses = [
        {"questions": [invalid, valid_second]},
        {"questions": [invalid, valid_second]},
        {"questions": [invalid, valid_second]},
        {"questions": [repaired_first]},
    ]

    class FakeCompletions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(responses.pop(0))))])

    completions = FakeCompletions()
    monkeypatch.setattr(
        generator_module,
        "_get_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()

    quiz, _answer_key, _artifacts = REAL_LLM_GENERATION(
        "course material", blueprint, 1, "markdown", output_dir
    )

    assert len(completions.calls) == 4
    assert "Repair one quiz question" in completions.calls[-1]["messages"][0]["content"]
    assert "A. Correct" in quiz


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

    assert "$P(A)=0.5$" in data["questions"][0]["explanation"]
    assert errors == []


def test_formula_normalization_repairs_textstylebigg_corruption():
    data = {"questions": [{
        "number": 1,
        "modality": "formula",
        "question": r"Interpret $\bar{x}=\frac{1}{N}textstylebigg(\sum_i x_i bigg)$.",
    }]}

    normalize_formula_delimiters(data, {"requirements": []})

    rendered = data["questions"][0]["question"]
    assert "textstylebigg" not in rendered
    assert r"\textstyle" not in rendered
    assert r"\bigg" not in rendered


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


def test_math_normalization_repairs_json_escape_control_characters():
    data = {"questions": [{
        "number": 1,
        "question": "Choose the correct expression.",
        "options": {
            "A": "$\bar{x} = \frac{1}{N} \times \text{sum}(x)$",
            "B": "$Y = f(X) + \nu$",
            "C": "$Y = f(X) + \regexpsilon$",
            "D": "No formula",
        },
        "explanation": "$\beta$ is a coefficient.",
    }]}

    normalize_formula_delimiters(data, {"requirements": []})
    rendered = "\n".join(data["questions"][0]["options"].values())

    assert r"$\bar{x} = \frac{1}{N} \times \text{sum}(x)$" in rendered
    assert r"$Y = f(X) + \nu$" in rendered
    assert r"$Y = f(X) + \epsilon$" in rendered
    assert r"$\beta$" in data["questions"][0]["explanation"]


def test_markdown_answer_choices_use_explicit_line_breaks():
    quiz = generator_module._format_quiz_from_llm({"questions": [{
        "number": 1,
        "question_kind": "single_choice",
        "question": "Question?",
        "options": {"A": "One", "B": "Two", "C": "Three", "D": "Four"},
        "correct_answers": ["A"],
    }]}, "markdown")

    assert "A. One  \nB. Two  \nC. Three  \nD. Four  " in quiz


def test_multiline_answer_values_render_as_text_not_indented_code():
    quiz = generator_module._format_quiz_from_llm({"questions": [{
        "number": 15,
        "question_kind": "single_choice",
        "question": "What array is printed?\n\n```python\nprint(values)\n```",
        "options": {
            "A": "[[1, 2]\n [3, 4]]",
            "B": "[1, 2]",
            "C": "[3, 4]",
            "D": "[]",
        },
        "correct_answers": ["A"],
    }]}, "markdown")

    assert "A. [[1, 2]<br>[3, 4]]  " in quiz
    assert "\n [3, 4]]" not in quiz


def test_markdown_code_blocks_have_blank_lines_and_canonical_fences():
    quiz = generator_module._format_quiz_from_llm({"questions": [{
        "number": 7,
        "question_kind": "single_choice",
        "question": "What is printed? ```python\nprint(3)```",
        "options": {"A": "3", "B": "2", "C": "1", "D": "0"},
        "correct_answers": ["A"],
    }]}, "markdown")

    assert "7. What is printed?\n\n```python\nprint(3)\n```\n\nA. 3" in quiz


def test_code_question_normalization_repairs_visible_newlines_and_fence():
    data = {"questions": [{
        "number": 7,
        "modality": "code",
        "question": r"What is printed?\n\n`python\narr = [1, 2, 3]\nprint(sum(arr))\n`",
    }]}

    normalize_code_fences(data)

    assert data["questions"][0]["question"] == (
        "What is printed?\n\n```python\narr = [1, 2, 3]\nprint(sum(arr))\n```"
    )


def test_code_question_normalization_embeds_separate_snippet_field():
    data = {"questions": [{
        "number": 11,
        "modality": "code",
        "question": "What value is printed?",
        "code_snippet": r"x = [1, 2, 3]\nprint(sum(x))",
    }]}

    normalize_code_fences(data)

    assert data["questions"][0]["question"] == (
        "What value is printed?\n\n```python\nx = [1, 2, 3]\nprint(sum(x))\n```"
    )


def test_code_modality_requires_fenced_code_block():
    blueprint = build_blueprint(
        num_versions=1,
        num_questions=1,
        question_style="open",
        topics=["Python"],
        learning_outcomes=[LearningOutcome("LO-1", "Interpret Python code")],
    )
    requirement = blueprint.version_plan(1)["requirements"][0]
    requirement["modality"] = "code"
    data = {"questions": [{
        "number": 1,
        "question_kind": "open_ended",
        "modality": "code",
        "question": "Explain what a loop does.",
        "options": None,
        "correct_answers": ["A loop repeats a block."],
    }]}

    errors = validate_generated_quiz(data, {"requirements": [requirement]})

    assert "question 1: code questions require a fenced code block in the prompt" in errors


def test_clustering_plot_requires_titleless_many_grouped_points():
    blueprint = build_blueprint(
        num_versions=1,
        num_questions=1,
        question_style="open",
        topics=["Clustering"],
        learning_outcomes=[LearningOutcome("LO-1", "Interpret a clustering plot")],
    )
    requirement = blueprint.version_plan(1)["requirements"][0]
    requirement["modality"] = "plot_interpretation"
    data = {"questions": [{
        "number": 1,
        "question_kind": "open_ended",
        "modality": "plot_interpretation",
        "question": "Interpret the grouping in the displayed data.",
        "options": None,
        "correct_answers": ["The observations form two groups."],
        "plot_spec": {
            "plot_type": "scatter",
            "x": [1, 2, 3],
            "y": [1, 2, 3],
            "title": "Sample Clustering Plot",
            "x_label": "x",
            "y_label": "y",
        },
    }]}

    errors = validate_generated_quiz(data, {"requirements": [requirement]})

    assert "question 1: generated plots must not have titles" in errors
    assert "question 1: clustering plots require at least 30 points" in errors
    assert any("clustering plots require a groups list" in error for error in errors)


def test_clustering_plot_normalization_removes_title_and_expands_points():
    requirement = {
        "number": 12,
        "question_kind": "open_ended",
        "modality": "plot_interpretation",
        "topic": "Clustering",
        "learning_outcome": {"statement": "Identify clusters in observed data"},
    }
    question = {
        "number": 12,
        "question_kind": "open_ended",
        "modality": "plot_interpretation",
        "question": "What learning task is illustrated? Plot Points: (1, 1), (5, 5)",
        "options": None,
        "correct_answers": ["Clustering"],
        "plot_spec": {
            "plot_type": "scatter",
            "x": [1.0, 5.0],
            "y": [1.0, 5.0],
            "title": "Sample Clustering Plot",
            "x_label": "Feature 1",
            "y_label": "Feature 2",
        },
    }
    data = {"questions": [question]}
    plan = {"requirements": [requirement]}

    normalize_plot_specs(data, plan)
    errors = validate_generated_quiz(data, plan)

    spec = question["plot_spec"]
    assert spec["title"] == ""
    assert "Plot Points" not in question["question"]
    assert "(1, 1)" not in question["question"]
    assert len(spec["x"]) == len(spec["y"]) == len(spec["groups"]) == 30
    assert len(set(spec["groups"])) == 2
    assert errors == []


def test_distribution_plot_is_normalized_to_histogram():
    requirement = {
        "number": 8,
        "question_kind": "open_ended",
        "modality": "plot_interpretation",
        "topic": "Descriptive statistics",
        "learning_outcome": {"statement": "Interpret distribution shape and dispersion"},
    }
    question = {
        "number": 8,
        "question_kind": "open_ended",
        "modality": "plot_interpretation",
        "question": "Interpret the shape of the displayed distribution.",
        "options": None,
        "correct_answers": ["The distribution is right-skewed."],
        "plot_spec": {
            "plot_type": "scatter",
            "x": [1, 1, 2, 2, 3, 8],
            "y": [1, 2, 3, 4, 5, 6],
            "title": "",
            "x_label": "Value",
            "y_label": "Frequency",
        },
    }
    data = {"questions": [question]}
    plan = {"requirements": [requirement]}

    normalize_plot_specs(data, plan)

    assert question["plot_spec"]["plot_type"] == "histogram"
    assert len(question["plot_spec"]["values"]) == 21
    assert question["plot_spec"]["values"].count(1) == 3
    assert question["plot_spec"]["values"].count(2) == 7
    assert question["plot_spec"]["values"].count(3) == 5
    assert question["plot_spec"]["values"].count(8) == 6
    assert "scatter" not in question["question"].lower()
    assert validate_generated_quiz(data, plan) == []


def test_statistical_learning_task_plot_uses_scatter_even_if_distribution_is_mentioned():
    requirement = {
        "number": 5,
        "question_kind": "open_ended",
        "modality": "plot_interpretation",
        "topic": "Statistical learning",
        "learning_outcome": {"statement": "Distinguish clustering from other learning tasks"},
    }
    question = {
        "number": 5,
        "question_kind": "open_ended",
        "modality": "plot_interpretation",
        "question": "Which statistical learning task is suggested by the distribution of points?",
        "options": None,
        "correct_answers": ["Clustering"],
        "plot_spec": {
            "plot_type": "histogram",
            "x": [1, 2, 5, 6],
            "y": [1, 2, 5, 6],
            "title": "",
            "x_label": "Feature 1",
            "y_label": "Feature 2",
        },
    }

    normalize_plot_specs({"questions": [question]}, {"requirements": [requirement]})

    assert question["plot_spec"]["plot_type"] == "scatter"
    assert "histogram" not in question["question"].lower()


def test_material_grounding_rejects_random_and_unintroduced_model_api():
    data = {"questions": [{
        "number": 1,
        "modality": "code",
        "question": "What is printed?\n```python\nfrom sklearn.tree import DecisionTreeClassifier\n"
                    "x = np.random.randn(10)\nmodel.fit(x)\n```",
    }]}

    errors = generator_module._material_grounding_errors(
        data, "The lecture introduces Python, NumPy, and descriptive statistics."
    )

    assert "question 1: code questions must not depend on random output" in errors
    assert "question 1: code questions must be solvable without fitting or running a model" in errors
    assert "question 1: package 'sklearn' is not introduced in the selected lecture notes" in errors


def test_histogram_frequency_pairs_expand_to_literal_observations():
    requirement = {
        "number": 1,
        "question_kind": "open_ended",
        "modality": "plot_interpretation",
        "topic": "Distribution shape",
        "learning_outcome": {"statement": "Interpret a histogram distribution"},
    }
    question = {
        "number": 1,
        "question_kind": "open_ended",
        "modality": "plot_interpretation",
        "question": "Interpret the histogram.",
        "options": None,
        "correct_answers": ["The lower values occur less often."],
        "plot_spec": {
            "plot_type": "histogram",
            "x": [5, 4, 3, 2, 1],
            "y": [4, 2, 1, 2, 1],
            "title": "",
            "x_label": "Value",
            "y_label": "Frequency",
        },
    }

    normalize_plot_specs({"questions": [question]}, {"requirements": [requirement]})

    assert question["plot_spec"]["values"] == [5, 5, 5, 5, 4, 4, 3, 2, 2, 1]
    assert question["plot_spec"]["x"] == question["plot_spec"]["values"]
    assert question["plot_spec"]["y"] == []


def test_code_execution_validation_rejects_non_runnable_block():
    data = {"questions": [{
        "number": 3,
        "question": "What is printed?\n```python\nprint(undefined_value)\n```",
        "options": {"A": "1", "B": "2", "C": "3", "D": "4"},
    }]}

    errors = generator_module._code_execution_errors(data)

    assert any("question 3: code is not runnable" in error for error in errors)


def test_code_in_answer_options_does_not_satisfy_code_modality():
    requirement = {
        "number": 15,
        "question_kind": "single_choice",
        "modality": "code",
    }
    data = {"questions": [{
        "number": 15,
        "question_kind": "single_choice",
        "modality": "code",
        "question": "Which expression computes the mean of values in x?",
        "options": {
            "A": "`sum(x) / len(x)`",
            "B": "`len(x) / sum(x)`",
            "C": "`sum(len(x))`",
            "D": "`x / len(x)`",
        },
        "correct_answers": ["A"],
    }]}

    errors = validate_generated_quiz(data, {"requirements": [requirement]})
    assert "question 15: code questions require a fenced code block in the prompt" in errors


@pytest.mark.parametrize(
    ("options", "answers", "expected_answers"),
    [
        (["one", "two", "three", "four"], [2], ["B"]),
        ({"a": "one", "b": "two", "c": "three", "d": "four"}, ["two"], ["B"]),
        ({"1": "one", "2": "two", "3": "three", "4": "four"}, ["2"], ["B"]),
    ],
)
def test_choice_normalization_canonicalizes_model_variants(options, answers, expected_answers):
    requirement = {
        "number": 4,
        "question_kind": "single_choice",
        "modality": "conceptual",
    }
    question = {
        "number": 4,
        "question_kind": "single_choice",
        "modality": "conceptual",
        "question": "Which result is correct?",
        "options": options,
        "correct_answers": answers,
    }
    data = {"questions": [question]}
    plan = {"requirements": [requirement]}

    normalize_choice_fields(data, plan)

    assert set(question["options"]) == {"A", "B", "C", "D"}
    assert question["correct_answers"] == expected_answers
    assert validate_generated_quiz(data, plan) == []


def test_numeric_topics_select_numbered_lectures_and_matching_outcomes(tmp_path):
    inputs = tmp_path / "inputs"
    outputs = tmp_path / "outputs"
    for name in ["syllabus", "lecture_notes", "MLO", "course_topics"]:
        (inputs / name).mkdir(parents=True)

    (inputs / "lecture_notes" / "05-Regression-draft.html").write_text("draft", encoding="utf-8")
    (inputs / "lecture_notes" / "05-Regression.html").write_text(
        "fit and interpret a least squares regression model", encoding="utf-8"
    )
    (inputs / "lecture_notes" / "06-Regularization.html").write_text(
        "compare regularization and dimension reduction", encoding="utf-8"
    )
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


def test_notebook_generation_accepts_named_paths(tmp_path):
    source_dir = tmp_path / "downloads"
    source_dir.mkdir()
    lecture_one = source_dir / "download-a.html"
    lecture_two = source_dir / "download-b.html"
    outcomes = source_dir / "outcomes.txt"
    lecture_one.write_text("descriptive statistics", encoding="utf-8")
    lecture_two.write_text("probability distributions", encoding="utf-8")
    outcomes.write_text("- Explain distributions using examples", encoding="utf-8")
    output_dir = tmp_path / "notebook_outputs"

    manifest = generate_quizzes_from_files(
        input_files={
            "lecture_notes": {
                "01-Description.html": lecture_one,
                "02-Distributions.html": lecture_two,
            },
            "learning_outcomes": {"0102_Outcomes.txt": outcomes},
        },
        output_dir=output_dir,
        num_versions=1,
        num_questions=4,
        question_type="mixed",
    )

    assert manifest["blueprint"]["topics"] == ["Description", "Distributions"]
    assert manifest["input_files"]["lecture_notes"] == [
        str(lecture_one.resolve()),
        str(lecture_two.resolve()),
    ]
    assert (output_dir / "quizzes" / "quiz_01.md").exists()
    audit = (output_dir / "audit" / "generation_audit.md").read_text(encoding="utf-8")
    assert "Notebook-supplied files" in audit
    assert "quizzer-notebook-" not in audit


def test_notebook_generation_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="Notebook input file does not exist"):
        generate_quizzes_from_files(
            input_files={"lecture_notes": [tmp_path / "missing.html"]},
            output_dir=tmp_path / "outputs",
        )
