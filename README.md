# Quizzer

`Quizzer` is an agentic LLM tool for generating multiple, comparable versions of course quizzes from instructional materials.

Given course materials and quiz specifications, Quizzer generates `n` versions of an `m`-question quiz. Quiz versions are designed to be similar in content coverage, difficulty, and question type while varying the specific questions and answer ordering.

Questions may assess:

* Conceptual understanding
* Mathematical/statistical reasoning
* Code interpretation
* Practical coding knowledge
* Plot or output interpretation
* Single-answer multiple choice
* Multiple-select questions
* Open-ended questions


Quizzer also produces separate answer keys, an audit report, and any supplementary files required by generated questions.

## Project Structure:

```
Quizzer/
├── README.md
├── SKILL.md
├── requirements.txt
├── pyproject.toml
├── .env.example
│
├── inputs/
│   ├── syllabus/
│   ├── lecture_notes/
│   ├── MLO/
│   └── course_topics/
│
├── outputs/
│   ├── quizzes/
│   ├── answer_keys/
│   ├── audit/
│   └── supplementary/
│       ├── code/
│       └── plots/
│
├── src/
│   └── quizzer/
│
└── tests/
```

## Inputs

Place course materials into the corresponding folders under `inputs/.`:

```
inputs/
├── syllabus/
│   └── syllabus.pdf
│
├── lecture_notes/
│   ├── lecture_01.pdf
│   ├── lecture_02.pdf
│   └── lecture_03.pdf
│
├── MLO/
│   └── mlo.txt
│
└── course_topics/
    └── topics.txt
```

Supported input formats may include `pdf`, `txt`, `md`, and `html`.

The input directory should contain all materials Quizzer is allowed to use when constructing the assessment.

## Outputs

A generation run produces:
```
outputs/
├── quizzes/
│   ├── quiz_01.tex
│   ├── quiz_02.tex
│   └── ...
│
├── answer_keys/
│   ├── answer_key_01.tex
│   ├── answer_key_02.tex
│   └── ...
│
├── audit/
│   └── audit_report.md
│
└── supplementary/
    ├── code/
    │   ├── quiz_01_q05_plot.py
    │   └── ...
    │
    └── plots/
        ├── quiz_01_q05_plot.png
        └── ...
```
Quiz files and answer keys are kept separate.

The supplementary directory stores code, plots, tables, or other files generated for use in quiz questions.

## Functionality

Quizzer performs the following workflow:
```
INPUT: Course Materials
      ↓
Read syllabus, lectures, MLOs, and topics
      ↓
Determine assessment coverage
      ↓
Generate N comparable quiz versions
      ↓
Verify questions and answer keys
      ↓
Randomize answer positions
      ↓
Generate plots/code when required
      ↓
Audit quiz quality and consistency
      ↓
OUTPUT: Write quizzes, answer keys, and audit report
```
Quizzer aims to ensure that all quiz versions have similar:

* Topic coverage
* MLO coverage
* Difficulty
* Question types
* Conceptual/practical balance
* Number of multiple-select questions

## Installation

### 1. Clone the repository:
```
git clone https://github.com/<USERNAME>/Quizzer.git
cd Quizzer
```
### 2. Create a virtual environment:
```
python -m venv .venv
```
### 3. Activate it:

macOS/Linux:
```
source .venv/bin/activate
```
Windows:
```
.venv\Scripts\Activate.ps1
```
### 4. Install Quizzer:
```
pip install -e .
```
Alternatively:
```
pip install -r requirements.txt
```
Environment Setup

Create a `.env` file from the example:
```
cp .env.example .env
```
Add any required LLM credentials:
```
OPENAI_API_KEY=your_api_key_here
```
Do not commit `.env` to version control.

## Running Quizzer

Once installed, Quizzer is runnable from the command line.

```bash
gen_quizzes --input ./inputs --output ./outputs --N 4 --M 10 --T mixed --format markdown
```

Where:

* `--input` is the path to the course input directory
* `--output` is the destination folder for generated files
* `--N` is the number of quiz versions to generate
* `--M` is the number of questions per quiz
* `--T` is `mixed` for a planned mix of multiple-choice and multiple-select questions, or `open` for open-ended questions
* `--format` chooses the output format for quiz and answer-key files: `markdown` or `tex`
* `--topic` optionally limits generation to a subject phrase, such as `--topic "introductions and distributions"`

Example with a topic filter:

```bash
gen_quizzes --input ./inputs --output ./outputs --N 3 --M 15 --T multiple --format markdown --topic "introductions and distributions"
```

This generates 3 quiz versions, each with 15 questions, and writes the results to `outputs/` using Markdown output. The topic filter is a keyword-based constraint that keeps generation focused on the supplied subject matter phrase.

When lecture-note filenames begin with lecture numbers, select them directly. For example, this selects lecture files beginning with `05-` and `06-`, plus matching numbered MLO files:

```bash
gen_quizzes --N 1 --M 15 --T mixed --topic 05 06
```

The default input directory may also be `./inputs`, allowing:

```bash
gen_quizzes --output ./outputs --N 4 --M 10 --format markdown
```

The generator writes:

* quiz files to `outputs/quizzes/`
* answer keys to `outputs/answer_keys/`
* audit summaries to `outputs/audit/`
* the shared structured plan to `outputs/audit/blueprint.json`
* supplementary code and plot artifacts to `outputs/supplementary/`

## SKILL.md

SKILL.md contains the generation and quality-control rules used by Quizzer.

Examples include:

* Do not generate trivial or obvious questions.
* Distractors must be plausible.
* Questions must be grounded in the supplied course material.
* Include both conceptual and practical questions when appropriate.
* Verify coding questions.
* Write Python code to generate plots used in questions.
* Save generated plotting code and figures.
* Follow the project TeX formatting specification.
* Support multiple-select questions.
* Randomize answer choices.
* Avoid systematic answer patterns.
* Avoid excessive use of any single correct answer position.
* Avoid duplicate or near-duplicate questions.
* Keep quiz versions similar in difficulty and coverage.
* Flag ambiguous or potentially invalid questions before final output.

More detailed generation rules should live in  `SKILL.md` rather than the README.

## Audit Report

Every run generates an audit report containing checks such as:

* Number of questions generated
* Topic coverage
* MLO coverage
* Difficulty balance
* Question-type balance
* Conceptual vs. practical question balance
* Answer-position distribution
* Multiple-select distribution
* Duplicate or near-duplicate questions
* Ambiguous questions
* Question validation failures
* Cross-version consistency
* Generated code/plot validation

Example:
```
Quiz Versions: 4
Questions per Quiz: 10
Questions Generated: 40
Questions Passed: 40
MLO Coverage: PASS
Topic Coverage: PASS
Difficulty Balance: PASS
Answer Distribution: PASS
Cross-Version Consistency: PASS
Warnings:
- Quiz 3, Question 7 revised due to an ambiguous distractor.
Overall Audit: PASS
```
## Requirements

Quizzer requires:

* Python 3.11+
* An available LLM provider
* Required API credentials
* Python packages listed in requirements.txt

Expected dependencies may include:
```
openai
pydantic
python-dotenv
pypdf
pyyaml
numpy
pandas
matplotlib
jinja2
typer
```
A TeX distribution is also required if quizzes are rendered to .tex or PDF.

## Status

Active Development

Quizzer is currently being developed as a course-assessment generation tool. Interfaces, supported file formats, and output formats may change as the tool is expanded.
