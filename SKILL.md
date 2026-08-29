---
name: quiz-generation
description: Generate grounded, comparable course quizzes and answer keys from supplied instructional materials using a shared assessment blueprint and an auditable validation workflow.
---

# Quiz Generation Instructions

## Executable Blueprint Contract

Before generating question prose, create one assessment blueprint shared by all quiz versions. Each numbered slot must specify its topic, source learning outcome, question type, and difficulty. Versions may vary wording, scenarios, values, and answer ordering, but must preserve those slot-level targets.

The user-facing question mode must be either `mixed` or `open`. A `mixed` quiz contains both single-answer multiple-choice and multiple-select questions; determine their distribution internally rather than asking for a multiple-select count. An `open` quiz contains only open-ended questions.

Blueprint slots may assess concepts through prose, formula work, code reasoning, or plot interpretation when supported by the course materials. Put display formulas inside `$$...$$` blocks.

Treat the emitted `outputs/audit/blueprint.json` as the authoritative run plan. If a prose rule conflicts with the user's explicit CLI arguments or the executable blueprint, follow the user arguments and report the conflict in the audit.

## 1. Purpose

Generate multiple-choice quizzes based on the lecture content and any provided learning outcomes.

Quizzes must assess one or more of the following, as appropriate to the lecture:

- conceptual understanding
- mathematical reasoning
- code interpretation
- debugging or code-completion reasoning
- sampling intuition
- plot interpretation
- data-analysis reasoning

Unless explicitly requested otherwise, do not ask about:

- course logistics
- administrative details
- facts not tied to the lecture content
- facts not tied to the provided learning outcomes

---

## 2. Default Output Format

Unless the user requests another format, quizzes must be written in Markdown.

Each quiz version must be a complete standalone Markdown file.

Each quiz version must be placed in exactly one standalone Markdown code block.

Each quiz version must be directly copyable from its code block into a standalone `.md` file without editing.

Example filenames, when filenames are needed:

- `quiz_lecture_01_version_A.md`
- `quiz_lecture_01_version_B.md`

Do not put filenames inside a quiz code block unless the filename is intended to be part of the exported quiz file.

---

## 3. Standard Quiz Structure

Use the following structure for each Markdown quiz:

```text
# Multiple Choice Quiz: Lecture Title -- Version A

## Questions

### 1. Question text here.

A. Answer choice A  
B. Answer choice B  
C. Answer choice C  
D. Answer choice D  

**ANSWER:** B.

* **LO measured:** Category -- Learning outcome statement.

---

### 2. **Select all that apply.** Question text here.

A. Answer choice A  
B. Answer choice B  
C. Answer choice C  
D. Answer choice D  

**ANSWER:** A, C.

* **LO measured:** Category -- Learning outcome statement.

---
```

Every question must include:

- a numbered question heading
- answer choices labeled A, B, C, and D unless the user requests a different number of choices
- exactly one answer line beginning with `**ANSWER:**`
- exactly one learning-outcome line beginning with `* **LO measured:**`
- a horizontal rule `---` after the learning-outcome line

Do not omit the answer line.

Do not omit the learning-outcome line.

Do not invent a learning-outcome numbering system unless the source outcomes are numbered.

Use the original learning-outcome category and statement when provided.

---

## 4. Question Counts

User-specified counts are hard constraints.

If the user requests a specific number of any of the following, the final output must satisfy that count exactly:

- quiz versions
- total questions
- answer choices
- select-all-that-apply questions
- plot-based questions
- code questions
- questions by topic
- questions by learning outcome

Do not approximate requested counts.

Do not silently change requested counts.

If the request is ambiguous or impossible, ask for clarification before generating the quiz.

---

## 5. Answer Choice Requirements

Unless the user requests otherwise:

- every question must have exactly four answer choices
- answer choices must be labeled A, B, C, and D
- answer choices must be plausible
- distractors must represent common misconceptions when possible
- answer choices must not be obviously absurd unless the learning goal specifically requires identifying an absurd option
- answer choices must be grammatically parallel when possible
- answer choices must avoid unnecessary trick wording

For single-answer questions:

- exactly one choice must be correct
- the answer line must contain exactly one correct letter
- correct letters must be reasonably balanced across A, B, C, and D
- correct answers must not follow an obvious pattern
- correct answers must not be concentrated in one or two letters
- answer-choice order must be adjusted when needed to improve balance

For select-all-that-apply questions, follow the rules in Section 7.

---

## 6. Learning Outcome Requirements

Each question must measure a lecture-relevant learning outcome.

The learning-outcome line must use the format:

```text
* **LO measured:** Category -- Learning outcome statement.
```

When provided learning outcomes include categories from Bloom's Taxonomy such as Remember, Understand, Apply, and Analyze, use those categories.

Questions should be distributed across the available learning-outcome categories when appropriate.

Do not focus only on low-level recall unless the user explicitly requests a recall-only quiz.

Prefer questions that require students to reason from:

- definitions
- formulas
- code snippets
- plots
- short scenarios
- conceptual comparisons
- data-analysis situations

Avoid questions that only test memorization of isolated wording from slides.

---

### 6.1 Sequential Lecture Context

When quizzes are created sequentially in the same chat and lecture materials are numbered by lecture, use previously uploaded lecture materials and learning objectives as background context for later-numbered lectures.

For a quiz on Lecture `N`, materials and learning objectives from Lectures `1` through `N - 1` may be treated as prior knowledge that students can be assumed to have encountered.

Use this prior lecture context to determine:

- terminology students can be expected to know
- notation and formulas that can be used without full re-explanation
- coding conventions, packages, functions, and workflows students have already seen
- statistical, mathematical, computational, or conceptual foundations that can be assumed
- appropriate prerequisite reasoning needed for the current lecture
- plausible distractors based on misconceptions from earlier lectures

The quiz should still primarily assess the current lecture content and current lecture learning objectives unless the user explicitly requests cumulative review.

Do not make earlier lecture content the main target of assessment unless explicitly requested.

Do not require obscure details from previous lectures unless those details are necessary for understanding the current lecture or are restated in the question.

When prior lecture context is used, ensure that each question still measures a current lecture-relevant learning outcome.

If there is uncertainty about whether a prior lecture concept should be assumed, prefer to include enough context in the question for it to be answerable.

---

## 7. Select-All-That-Apply Question Requirements

### 7.1 Scope and Priority

These rules apply to every quiz version that includes select-all-that-apply questions.

The select-all-that-apply distribution is a hard requirement. It must be planned before drafting and audited before output.

Do not approximate, ignore, or silently modify this distribution.

If any rule in this section conflicts with a previous SATA-distribution rule, this section supersedes the previous rule.

---

### 7.2 Required SATA Wording

Every select-all-that-apply question must include the exact phrase:

**Select all that apply.**

This phrase must appear in the question text.

---

### 7.3 Internal SATA Planning and Correctness

For `mixed` mode, the blueprint determines the number and positions of select-all-that-apply questions. Do not expose a separate user-facing count. Ensure that every mixed quiz contains at least one single-answer multiple-choice question and at least one multiple-select question.

Every multiple-select question must have at least two correct answers. Vary the number and positions of correct choices when doing so remains natural and accurate.

The internal distribution must never be satisfied by making a question inaccurate, misleading, ambiguous, or pedagogically weak.

If a question does not naturally fit its assigned number of correct answers, revise one or more of the following before output:

- the question wording
- the answer choices
- the placement of the question within the SATA plan
- the concept being assessed

The final result must satisfy both of the following:

1. The question is scientifically, mathematically, and pedagogically correct.
2. Its correct-answer set is unambiguous.

Do not sacrifice correctness to satisfy answer-count distribution.

---

### 7.4 SATA Answer-Pattern Rules

Correct answer positions for SATA questions must be varied and pattern-free.

Do not overuse any of the following answer patterns:

- **A, B, C**
- **A, B, D**
- mostly consecutive answer choices
- mostly early answer choices
- mostly late answer choices
- the same two-correct pattern repeatedly
- the same three-correct pattern repeatedly
- always A and B
- always all except D
- all correct answers always beginning with A

Across the SATA questions in a quiz version:

- correct choices must not be concentrated in A and B
- correct choices must not usually appear consecutively
- two-correct SATA questions must use varied answer-position patterns
- three-correct SATA questions must use varied answer-position patterns
- the overall SATA answer pattern must appear non-obvious and pattern-free to students

---

## 8. Plot-Based Question Requirements

### 8.1 Default Plot Requirement

For every quiz version with **15 or more questions**, include exactly **2 plot-based questions per version** by default.

If the user explicitly requests a different number of plot-based questions, follow the user’s requested number exactly.

If the user explicitly requests no plots, do not include plot-based questions.

If plot-based questions are omitted despite the default requirement, provide a specific justification outside the quiz code block.

Introductory descriptive-statistics lectures are considered suitable for plot-based questions.

Do not omit plot-based questions merely because the content is introductory.

---

### 8.2 What Counts as a Plot-Based Question

A plot-based question must include an actual Markdown image link.

A text-only description of a plot does not count as a plot-based question unless the user explicitly says text-described plots are acceptable.

Each plot-based question must require interpretation of the plot.

Plot-based questions must not merely ask students to identify superficial visual features such as:

- the title
- the axis labels
- the color of a line
- the number of visible markers
- the filename

Plot-based questions should assess interpretation, such as:

- trends
- distributions
- density estimates
- regression fit quality
- residual behavior
- optimization paths
- feasible regions
- PCA directions
- scree plot implications
- variance explained
- relationships between plotted quantities

---

### 8.3 Markdown Image Formatting

Include images using standard Markdown image syntax:

```text
![Descriptive alt text](quiz_plot_1.png)
```

If image sizing is needed and the Markdown platform supports HTML, use:

```text
<img src="quiz_plot_1.png" alt="Descriptive alt text" width="500">
```

Prefer `.png` images for broad compatibility with Markdown previewers, learning-management systems, GitHub, Jupyter Book, and Quarto.

Use `.pdf` images only if the target Markdown-to-PDF workflow supports them.

Each image must have descriptive alt text.

The image link must appear inside the same Markdown code block as the quiz version.

The image link should appear immediately before the corresponding plot-based question text.

Each linked image filename must be unique unless intentional reuse is explicitly stated.

---

### 8.4 Plot Generation Script Requirements

If plot images are needed and not provided by the user, provide a separate Python script that generates all required plot image files.

The script must:

- use reproducible random seeds when randomness is involved
- save each plot to the exact filename referenced in the quiz Markdown
- save plot image files in the same folder as the quiz Markdown files
- use clear axis labels and titles when appropriate
- avoid relying on external data files unless the user provides them
- generate every image referenced by the quiz
- avoid generating unused images unless there is a clear reason

The plot-generation script must be provided in a separate Markdown code block after the quiz versions unless the user requests otherwise.

For quizzes with generated plot images, name the Python plot-generation script using the lecture numbers in the format `generate_quiz_plots_####.py`, for example `generate_quiz_plots_0910.py` for Lectures 09–10.

---

### 8.5 Plot Audit Requirements

Before output, verify that:

- each requested plot-based question has an actual Markdown image link
- each linked image filename is unique unless intentional reuse is explicitly stated
- the number of plot-based questions exactly matches the user request or default rule
- every linked image file is generated by the provided script or was provided by the user
- no text-only plot description is counted as a plot-based question
- plot-based questions assess interpretation rather than superficial visual matching

If any plot audit item fails, revise the quiz and audit again before output.

---

## 9. Code-Based Question Requirements

Coding questions must test reasoning, debugging, prediction, interpretation, or code completion.

Do not include code questions that merely ask students to recognize syntax unless that syntax is central to the learning outcome.

Additional acceptable code-based question formats include, but are not limited to:

- completing a missing line, expression, argument, condition, or function body in a code snippet
- selecting the correct code fragment to fill in one or more blanks
- selecting all code fragments that would correctly complete a task
- ordering provided lines or blocks of code to produce a specified behavior, result, plot, model fit, or output
- selecting the sequence of code blocks that correctly implements an algorithm or workflow
- choosing which code block should be inserted at a specified location
- choosing the minimal correction needed to make code run correctly or produce the intended result
- identifying which version of a code snippet correctly implements a stated concept

Fill-in-the-blank code questions must be formatted as multiple-choice or select-all-that-apply questions unless the user explicitly requests a free-response format. Do not require students to type arbitrary code in a quiz that is otherwise specified as multiple-choice.

Code-ordering questions must provide answer choices as possible orderings or as selectable statements about the order. The correct ordering must be unambiguous and must produce the stated behavior or output.

Code-construction questions should assess reasoning about program logic, data flow, statistical computation, modeling workflow, visualization workflow, debugging, prediction, interpretation, or code completion. They should not merely test memorization of syntax unless that syntax is central to the learning outcome.

When using code fragments, ensure that:

- all variables, packages, functions, and data objects needed to answer the question are defined in the question or are standard within the lecture context
- the completed or ordered code is syntactically valid unless the question is explicitly about debugging invalid code
- distractor code fragments reflect plausible mistakes or misconceptions
- the intended output or behavior is stated clearly enough that only one answer is correct for single-answer questions
- select-all-that-apply code questions clearly indicate that more than one option may be correct

When code appears inside a quiz question:

- code must be syntactically consistent with the lecture materials
- code must be short enough to read within a quiz question
- code must not rely on unstated external files
- code must not use triple backticks inside the quiz Markdown code block if that would prematurely close the quiz code block

Use indentation or inline code formatting inside the quiz code block when necessary.

Examples of acceptable code-based question formats:

### Example 1. Fill-in-the-blank code completion

The code below should calculate the mean of the values in `x`. Which expression should replace the blank?

    x = [2, 4, 6, 8]
    result = ______

A. `sum(x) / len(x)`  
B. `len(x) / sum(x)`  
C. `sum(len(x))`  
D. `x / len(x)`  

**ANSWER:** A.
* **LO measured:** Use code to compute and interpret summary statistics.
---

### Example 2. Ordering code blocks

The following code blocks are intended to load a dataset, fit a model, and make predictions. Which ordering is correct?

1. `model.fit(X_train, y_train)`  
2. `pred = model.predict(X_test)`  
3. `model = LinearRegression()`  
4. `from sklearn.linear_model import LinearRegression`

A. 4, 3, 1, 2  
B. 3, 4, 1, 2  
C. 4, 1, 3, 2  
D. 1, 2, 3, 4  

**ANSWER:** A.
* **LO measured:** Arrange model-fitting code in the correct computational sequence.
---

### Example 3. Select-all-that-apply code completion

Select all expressions that would correctly replace the blank to compute the sample variance of the values in `x`.

    x = [2, 4, 6, 8]
    xbar = sum(x) / len(x)
    s2 = ______

A. `sum((xi - xbar)**2 for xi in x) / (len(x) - 1)`  
B. `sum((xi - xbar)**2 for xi in x) / len(x)`  
C. `np.var(x, ddof=1)`  
D. `np.mean(x) / (len(x) - 1)`  

**ANSWER:** A, C.
* **LO measured:** Use code to compute sample variance and distinguish sample from population variance.
---

### Example 4. Debugging by selecting the minimal correction

The code below is intended to compute the mean of the values in `x`, but it contains an error.

    x = [2, 4, 6, 8]
    result = sum(x) / x

Which change is the minimal correction?

A. Replace `x` in the denominator with `len(x)`  
B. Replace `sum(x)` with `len(x)`  
C. Replace `/` with `*`  
D. Replace `x` with `sum(len(x))`  

**ANSWER:** A.
* **LO measured:** Debug code that computes a numerical summary.
---

### Example 5. Choosing the correct code block to insert

The function below should return the proportion of values in `x` that are greater than `threshold`. Which code block should replace the blank?

    def proportion_greater(x, threshold):
        ______

A. `return sum(xi > threshold for xi in x) / len(x)`  
B. `return sum(x) > threshold / len(x)`  
C. `return len(x) / sum(xi > threshold for xi in x)`  
D. `return sum(xi < threshold for xi in x) / threshold`  

**ANSWER:** A.
* **LO measured:** Write code that computes a proportion from a condition.
---

---

## 10. Mathematical Notation Requirements

Mathematical notation must be consistent with the lecture materials.

Use standard notation for probability, statistics, optimization, least squares, and PCA.

Use dollar-sign math delimiters for all LaTeX math: use `$...$` for inline math and `$$...$$` for display math; do not use `\(...\)` or `\[...\]`, to improve compatibility with VS Code Markdown preview.

All mathematical notation, variables, formulas, inequalities, intervals, probability statements, and distribution names used mathematically must be enclosed in dollar-sign LaTeX delimiters. Use `$...$` for inline math and `$$...$$` for display math. Do not leave mathematical expressions such as `p(x)`, `P(a <= X <= b)`, `E[X]`, `CDF(x)`, `Uniform(0,1)`, `[a,b]`, or `N` as plain text when they are being used as mathematical notation.

Use:

```text
\text{Var}
```

rather than:

```text
\mathbb{Var}
```

unless the user explicitly requests otherwise.

Ensure that formulas are mathematically correct.

Do not introduce notation that is inconsistent with the lecture unless it is clearly defined.

---

## 11. Multiple Quiz Versions

When multiple quiz versions are requested, each version must be parallel but not identical.

Versions must closely mirror each other in:

- number of questions
- number of answer choices
- number of select-all-that-apply questions
- planned question-type mix and SATA answer-set correctness
- number of plot-based questions
- difficulty
- topics covered
- learning outcomes assessed
- mathematical complexity
- type of code reasoning
- time required

Do not make one version substantially easier or harder than another.

Each quiz version must be a complete standalone Markdown file.

Each complete standalone Markdown quiz must be placed in its own separate Markdown code block.

Use labels outside the quiz code blocks, such as:

```text
Here is Version A:
```

followed by one complete Markdown code block containing only Version A.

Then use:

```text
Here is Version B:
```

followed by one complete Markdown code block containing only Version B.

Do not split a single quiz version across multiple code blocks.

---

## 12. Markdown Code Block Requirements for Final Output

When generating one or more quiz versions, each complete quiz version must be placed inside exactly one standalone Markdown code block.

Each code block must contain the entire contents of one complete quiz Markdown file, including:

- the quiz title
- all questions
- all answer choices
- the answer line for each question
- the learning-outcome line for each question
- any Markdown image links used by that quiz

Do not split a single quiz version across multiple code blocks.

Do not place explanatory text, filenames, notes, or partial quiz content inside the quiz code block unless that text is intended to be part of the exported `.md` quiz file.

Put labels such as `Here is Version A:` outside the quiz code block.

If plot images are needed, provide the image-generation Python script separately.

The plot-generation Python script must not be inside the quiz-version code block unless the user explicitly requests that structure.

---

## 13. Answer Randomization and Balance

### 13.1 General Answer Balance

Do not use purely random answer placement.

Use constrained randomization.

Correct-answer placement must be balanced and pattern-free.

For single-answer questions:

- correct letters must be reasonably balanced across A, B, C, and D
- no answer letter should be correct less than 2 times
- no answer letter should be correct more than 6 times
- correct answers must not follow an obvious sequence
- correct answers must not alternate predictably
- correct answers must not cluster excessively
- answer-choice order must be adjusted when needed to improve balance

For select-all-that-apply questions:

- follow the mixed-question planning rules in Section 7
- vary the correct-answer positions
- do not use A, B, C more than once
- do not use A, B, D more than once
- avoid mostly consecutive correct answers
- avoid mostly early correct answers
- avoid repeated pair or triple patterns

---

### 13.2 Pattern Avoidance

The final answer key must not look predictable to students.

Avoid patterns such as:

- many consecutive questions with the same correct letter
- repeating cycles such as A, B, C, D, A, B, C, D
- most single-answer questions using B or C
- most SATA questions using A, B, C
- most SATA questions using A, B, D
- most SATA questions using only consecutive choices
- most SATA questions using the first several answer choices

If the answer pattern is unbalanced, revise answer-choice order before output.

---

## 14. Style Guidelines

Use clear, direct wording.

Avoid unnecessarily tricky phrasing.

Use distractors that represent common misconceptions.

Prefer questions that require students to reason from definitions, formulas, code snippets, plots, or short scenarios.

Avoid questions that ask students only to recall isolated wording from slides.

When writing mathematical or coding questions, ensure the notation and code are consistent with the lecture materials.

When writing plot questions, assess what the plot means rather than asking students to identify superficial visual features.

When generating multiple versions, make the versions parallel but not identical.

Do not make answer choices unnecessarily long unless required by the concept.

Do not use ambiguous wording such as “best” or “most correct” unless the criterion is explicit.

---

## 15. Mandatory Pre-Output Planning

This section is a hard requirement for every quiz-generation task.

Before drafting the final quiz, internally plan the quiz structure for each version.

The internal plan must include:

- total number of questions
- question numbers
- topic or concept for each question
- learning outcome for each question
- which questions are single-answer questions
- which questions are select-all-that-apply questions
- which questions are plot-based questions
- which questions include code, if any
- correct answer letter for each single-answer question
- correct answer letters for each SATA question
- mixed-question distribution and SATA answer-set correctness
- plot filenames for plot-based questions
- whether each plot filename will be generated by the script or was provided by the user

Do not output the quiz until the plan satisfies all requested and default requirements.

Do not show the internal plan unless the user explicitly requests it.

---

## 16. Mandatory Internal Final Audit

This section is a hard requirement for every quiz-generation task.

Before outputting the final quiz, perform an internal audit of every quiz version.

Before outputting any quiz, iteratively audit and revise the quiz until all requirements are satisfied. The audit must verify question count, version count, plot count, mixed-question composition, SATA answer-set correctness, answer-letter balance, non-patterned answer placement, learning-outcome coverage, plot filename consistency, Python script filename consistency, and math delimiter compatibility. Do not output the quiz until every requirement passes the audit.

The audit must verify all of the following:

### 16.1 Count Requirements

- the requested number of quiz versions is present
- each quiz version has the exact requested number of questions
- each question number appears exactly once
- no question number is skipped
- no extra questions are included
- the exact requested number of answer choices is used
- every mixed-mode question has choices labeled A, B, C, and D
- open-mode questions do not have answer choices

### 16.2 Question Format Requirements

- every mixed-mode question is multiple choice or select-all-that-apply
- every open-mode question is open-ended
- every question has exactly one answer line beginning with `**ANSWER:**`
- every question has exactly one learning-outcome line beginning with `* **LO measured:**`
- the answer line appears directly beneath the answer choices
- the learning-outcome line appears directly beneath the answer line
- each question ends with `---`
- no quiz version is split across multiple code blocks
- no extra commentary appears inside a quiz code block unless it is intended to be part of the exported quiz file

### 16.3 Learning Outcome Requirements

- the quiz content matches the lecture material
- the quiz content matches the provided learning outcomes
- the quiz avoids course logistics unless explicitly requested
- the LO measured lines use original learning-outcome categories and statements when provided
- no invented learning-outcome numbering system is used unless the source outcomes are numbered

### 16.4 Single-Answer Requirements

- every single-answer question has exactly one correct answer
- single-answer correct letters are reasonably balanced
- correct answers are not overly concentrated in A, B, C, or D
- the answer pattern is not predictable
- answer-choice order has been adjusted when needed to rebalance answer letters

### 16.5 SATA Requirements

- mixed mode contains both single-answer and multiple-select questions
- every SATA question includes the exact phrase **Select all that apply.**
- every SATA question has at least two correct answers
- the final answer key matches the internal SATA plan
- no SATA answer pattern is overused
- **A, B, C** is not overused
- **A, B, D** is not overused
- correct answers are not mostly consecutive
- correct answers are not mostly concentrated in early answer choices
- correct answers are not mostly concentrated in late answer choices
- no question has been made inaccurate, misleading, ambiguous, or weak to satisfy a question-type allocation

### 16.6 Plot Requirements

- the exact requested number of plot-based questions is present
- if the quiz has 15 or more questions, exactly 2 plot-based questions per version are included unless the user explicitly requested otherwise
- every plot-based question includes an actual Markdown image link
- every plot-based question assesses interpretation
- no text-only plot description is counted as a plot-based question unless the user explicitly allowed text-described plots
- every linked image filename is correct
- every linked image file is generated by the provided script or was provided by the user
- image filenames are unique unless intentional reuse is explicitly stated
- the Python script saves every referenced image to the exact referenced filename

### 16.7 Multiple-Version Requirements

- all versions are parallel in topic coverage
- all versions are parallel in difficulty
- all versions are parallel in mathematical complexity
- all versions are parallel in code-reasoning complexity
- all versions are parallel in plot-reasoning complexity
- all versions assess comparable learning outcomes
- no version is substantially easier or harder than another

### 16.8 Style and Quality Requirements

- answer choices are plausible
- distractors represent common misconceptions when possible
- wording is clear and direct
- questions are not unnecessarily tricky
- mathematical notation is consistent
- code is consistent with lecture materials
- plot questions assess meaning rather than superficial visual features

If any audit item fails, revise the quiz and repeat the audit before output.

Do not output the final quiz until all required audit checks pass.

Do not claim or imply that the quiz passed the audit unless the audit was actually performed and all checklist items passed.

Do not include hidden reasoning, internal planning, or answer-pattern audit details in the final user-facing response unless explicitly requested.

---

## 17. Optional Visible Audit When Requested

By default, do include the audit in the final user-facing response.

When a visible final audit summary is requested, use a Markdown table with the following columns:

| Version | # SATA questions | SATA # correct distribution | SATA answer-letter patterns used | Single-answer distribution | # plot-based questions | # coding-related questions | Final check status |

The table should report, for each quiz version:

- the total number of select-all-that-apply questions
- the number of SATA questions with exactly 2 correct answers
- the number of SATA questions with exactly 3 correct answers
- the number of SATA questions with exactly 4 correct answers
- the SATA answer-letter combinations used, without needing to list question numbers
- the correct-letter distribution for single-answer questions
- the total number of plot-based questions
- the total number of coding-related questions
- whether all checks passed, or which checks failed if any did not pass

If any failed check is found after output, acknowledge it directly and offer to revise the quiz.

Do not hide known failures.

As an example:

| Version | # SATA questions | SATA # correct distribution | SATA answer-letter patterns used | Single-answer distribution | # plot-based questions | # coding-related questions | Final check status |
|---|---:|---|---|---|---:|---:|---|
| Version A | 3 | 2-correct: 2; 3-correct: 1 | A,D; A,C,D; B,C | A: 2; B: 2; C: 2; D: 1 | 2 | 2 | Passed |
---

## 18. Final Output Requirements

When responding to a user request for quiz generation:

- follow the requested number of versions
- follow the requested number of questions
- use the lecture material and learning outcomes provided
- put each complete quiz version in exactly one standalone Markdown code block
- put only the quiz content inside the quiz code block
- put labels such as `Here is Version A:` outside the quiz code block
- if plot images are needed, provide the image-generation Python script separately
- if no plot images are needed or appropriate, do not invent unnecessary images
- if plot questions are omitted despite the default rule, explicitly justify the omission outside the quiz code block
- do not include hidden reasoning or answer-pattern audit details unless explicitly requested

For multiple quiz versions, use this output pattern:

````text
Here is Version A:

```markdown
# Multiple Choice Quiz: Lecture Title -- Version A

## Questions

...
```

Here is Version B:

```markdown
# Multiple Choice Quiz: Lecture Title -- Version B

## Questions

...
```
````

Each quiz version must be copyable directly from its code block into its own `.md` file.

Do not split a single quiz version across multiple code blocks.

Do not include partial quiz content outside the quiz code block.

---

## 19. Failure Handling

If a requested quiz cannot be generated while satisfying all hard requirements, do not produce a noncompliant quiz.

Instead, ask for clarification or state the conflict.

Examples of conflicts include:

- mixed mode is requested with fewer than two total questions
- the user requests plot-based questions but also forbids images
- the user requests a topic distribution that conflicts with the provided lecture material
- the user requests exact answer distributions that are impossible with the requested number of questions
- the user requests multiple versions that cannot be made parallel with the available material

Before outputting any quiz, iteratively audit and revise the quiz until all requirements are satisfied. The audit must verify question count, version count, plot count, mixed-question composition, SATA answer-set correctness, answer-letter balance, non-patterned answer placement, learning-outcome coverage, plot filename consistency, Python script filename consistency, and math delimiter compatibility. Do not output the quiz until every requirement passes the audit.

If a failure is discovered after output, acknowledge the issue directly and offer to revise the quiz.

Do not claim compliance when a requirement was not met.
