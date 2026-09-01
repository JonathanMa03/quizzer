# Quizzer

Quizzer is an LLM-assisted quiz generator for course materials. It creates one or more alternate quiz versions, separate answer keys, a structured assessment blueprint, an audit report, and reproducible plot artifacts when plot interpretation is assessed.

Quiz questions can assess:

- Conceptual understanding
- Mathematical and statistical reasoning
- Code interpretation, completion, and debugging
- Plot interpretation
- Single-answer multiple choice
- Multiple-select questions
- Open-ended responses

Quizzer supports two question modes:

- `mixed`: an internally planned mix of multiple-choice and multiple-select questions
- `open`: open-ended questions only

## How generation works

```text
Course files
    ↓
Parse lecture notes, syllabus, and learning outcomes
    ↓
Build one structured assessment blueprint
    ↓
Generate distinct alternate quiz versions in validated batches
    ↓
Normalize Markdown and mathematical notation
    ↓
Generate and execute plot scripts when required
    ↓
Write quizzes, answer keys, blueprint, artifacts, and audit
```

Quiz versions retain comparable overall coverage and question-type counts, but topics, learning outcomes, modalities, and difficulty positions are permuted. Earlier question stems are supplied as an exclusion list so later versions use different scenarios, code, values, plots, and central tasks.

Selected lecture notes and explicit learning outcomes jointly define assessable content. Syllabus material is contextual only. When a learning-outcome file contains a `Learning Outcomes` or `Learning Objectives` section, Quizzer extracts outcomes from that section rather than treating earlier key-concept bullets as additional outcomes. Each outcome is assigned at least once per quiz; generation reports an error when the requested question count is smaller than the number of supplied outcomes.

## Project structure

```text
quizzer/
├── quizzer_notebook.ipynb
├── README.md
├── SKILL.md
├── pyproject.toml
├── requirements.txt
├── inputs/
│   ├── syllabus/
│   ├── lecture_notes/
│   ├── MLO/
│   └── course_topics/
├── outputs/
│   ├── quizzes/
│   ├── answer_keys/
│   ├── audit/
│   └── supplementary/
│       ├── code/
│       └── plots/
├── src/quizzer/
└── tests/
```

## Requirements

- Python 3.10 or newer
- An OpenAI API key
- Internet access during LLM generation
- A TeX distribution only when compiling generated `.tex` files externally

## Environment setup

### 1. Open the project

```bash
cd /path/to/quizzer
```

### 2. Create and activate a virtual environment

macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Install Quizzer

For command-line use and tests:

```bash
python -m pip install -e '.[test]'
```

For command-line, tests, and notebook use:

```bash
python -m pip install -e '.[test,notebook]'
```

The notebook installation includes `ipykernel`. Matplotlib is a normal project dependency because Quizzer executes reproducible scripts to create plot-question images.

### 4. Configure the API key

Create `.env` in the project root:

```text
OPENAI_API_KEY=your_api_key_here
```

If `.env.example` is available, it can be copied first:

```bash
cp .env.example .env
```

Do not commit `.env`.

### 5. Register the notebook kernel

With `.venv` activated:

```bash
python -m ipykernel install --user --name quizzer --display-name "Python (Quizzer)"
```

This registration is normally needed only once per environment. The included notebook already selects the `quizzer` kernel in its metadata.

## Running the notebook

The ready-to-run notebook is [quizzer_notebook.ipynb](quizzer_notebook.ipynb).

### 1. Start Jupyter from the project root

If JupyterLab or Notebook is already installed on your system:

```bash
jupyter lab quizzer_notebook.ipynb
```

or:

```bash
jupyter notebook quizzer_notebook.ipynb
```

The `notebook` dependency extra installs the project kernel, not the JupyterLab user interface. If neither command exists, install the interface you prefer:

```bash
python -m pip install jupyterlab
```

Then run:

```bash
python -m jupyter lab quizzer_notebook.ipynb
```

### 2. Select the project kernel

Choose **Python (Quizzer)** if the notebook does not select it automatically.

### 3. Configure the run

Edit the configuration cell:

```python
NUM_VERSIONS = 1
NUM_QUESTIONS = 15
QUESTION_TYPE = "mixed"       # "mixed" or "open"
OUTPUT_FORMAT = "markdown"    # "markdown" or "tex"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "notebook_run"
```

### 4. Supply the input files

The notebook uses every file listed in `INPUT_FILES`. A separate topic filter is not needed.

```python
INPUT_FILES = {
    "syllabus": PROJECT_ROOT / "inputs" / "syllabus" / "syllabus.md",
    "lecture_notes": [
        PROJECT_ROOT / "inputs" / "lecture_notes" / "01-Desc.html",
        PROJECT_ROOT / "inputs" / "lecture_notes" / "01-Intro.pdf",
    ],
    "learning_outcomes": [
        PROJECT_ROOT / "inputs" / "MLO" / "01_Desc.md",
    ],
}
```

Supported group names are:

- `syllabus`
- `lecture_notes`, `lectures`, or `notes`
- `learning_outcomes`, `outcomes`, or `MLO`
- `course_topics` or `topics`

Paths can point outside the repository. To give a file an explicit course filename independently of its disk filename, use a nested mapping:

```python
INPUT_FILES = {
    "lecture_notes": {
        "01-Description.html": "/path/to/downloaded_notes.html",
        "02-Distributions.html": "/path/to/another_download.html",
    },
    "learning_outcomes": {
        "0102_Outcomes.md": "/path/to/outcomes.md",
    },
}
```

Explicit names are useful because Quizzer derives blueprint topic names from numbered lecture filenames.

### 5. Run the notebook

Run the cells from top to bottom. The generation cell makes API calls. Later cells display the blueprint, preview the first quiz, list answer keys, and show the audit.

Notebook output is written under `outputs/notebook_run/` by default.

### Notebook API

The notebook calls the public Python function directly:

```python
from quizzer import generate_quizzes_from_files

manifest = generate_quizzes_from_files(
    input_files=INPUT_FILES,
    output_dir="outputs/notebook_run",
    num_versions=1,
    num_questions=15,
    question_type="mixed",
    output_format="markdown",
)
```

`generate_quizzes_from_files` intentionally has no `topics` argument. The supplied files define the complete allowed source set.

## Running from the command line

Directory-based generation remains available through `gen_quizzes`:

```bash
gen_quizzes \
  --input ./inputs \
  --output ./outputs \
  --N 1 \
  --M 15 \
  --T mixed \
  --format markdown
```

Arguments:

- `--input`, `-i`: structured course-material directory
- `--output`, `-o`: destination directory
- `--N`, `--versions`: number of quiz versions
- `--M`, `--questions`: questions per version
- `--T`, `--question-type`, `--question-style`: `mixed` or `open`
- `--format`: `markdown` or `tex`
- `--topic`: optional numeric lecture selectors or content phrases

### Selecting numbered lectures

Lecture notes commonly use names such as `05-LeastSquares.html`. To select lectures by their leading numbers:

```bash
gen_quizzes --N 1 --M 15 --T mixed --topic 05 06
```

This selects matching numbered lecture files and matching numbered MLO files. Grouped MLO names are supported; for example, `060708_PCA.md` can match lecture `06`, `07`, or `08`. When both final and `-draft` lecture files exist, Quizzer prefers the final file.

Phrase filtering is also supported for CLI runs:

```bash
gen_quizzes --N 1 --M 10 --T open --topic "Bayesian statistics"
```

## Input formats

The directory loader currently supports:

- `.pdf`
- `.txt`
- `.md`
- `.html` and `.htm`
- `.tex`
- `.py`
- `.r`

Unsupported files are not parsed. PowerPoint, notebook, image, CSV, and NumPy files are not currently treated as course-text inputs.

## Generated outputs

A run produces:

```text
outputs/
├── quizzes/
│   ├── quiz_01.md
│   └── quiz_02.md
├── answer_keys/
│   ├── quiz_01_key.md
│   └── quiz_02_key.md
├── audit/
│   ├── blueprint.json
│   └── generation_audit.md
└── supplementary/
    ├── code/
    │   └── quiz_01_q04_plot.py
    └── plots/
        └── quiz_01_q04_plot.png
```

For TeX output, quiz and answer-key extensions are `.tex`.

### Plot questions

Plot-interpretation questions never rely on an imagined “given plot.” For each plot question, Quizzer:

1. Validates a numeric plot specification returned by the model.
2. Writes a reproducible Matplotlib script under `supplementary/code/`.
3. Executes the script using the active Quizzer environment.
4. Saves a PNG under `supplementary/plots/`.
5. Adds the relative image path to the quiz.

### Markdown and formulas

- Answer choices use explicit Markdown line breaks so A–D display on separate lines in notebooks.
- Generated LaTeX is repaired when JSON escaping damages common commands.
- Inline `$...$` math is preferred when display math is unnecessary.
- `\(...\)` and `\[...\]` delimiters are normalized for notebook compatibility.

## Blueprint and validation

`outputs/audit/blueprint.json` records the shared assessment plan. Each slot includes:

- Question number
- Topic
- Learning outcome and source
- Question kind
- Assessment modality
- Difficulty

Generated batches are checked for exact question counts, numbering, question kinds, modalities, answer structure, valid answer letters, and plot specifications. Invalid batches are retried up to the configured stopping limit.

`generation_audit.md` records run parameters, included source files, output files, the blueprint table, and structural generation results.

## Running tests

```bash
python -m pytest -q
```

The test suite stubs LLM requests, so tests do not consume API credits. Plot tests execute generated scripts locally.

## Troubleshooting

### The notebook cannot import `quizzer`

Confirm that **Python (Quizzer)** is selected and reinstall the editable package:

```bash
source .venv/bin/activate
python -m pip install -e '.[test,notebook]'
```

### The kernel is missing

```bash
source .venv/bin/activate
python -m ipykernel install --user --name quizzer --display-name "Python (Quizzer)"
```

Then restart Jupyter and select **Python (Quizzer)**.

### `OPENAI_API_KEY` is missing

Add it to `.env` in the project root, restart the kernel, and rerun the notebook initialization cell.

### A generated batch fails validation

Quizzer retries invalid batches automatically. If all attempts fail, the error identifies the question batch and the failed validation rule. Rerunning generation may produce a compliant batch; persistent failures indicate that the source material or generation contract needs adjustment.

## Development status

Quizzer is under active development. Interfaces and validation rules may continue to evolve.
