from __future__ import annotations

import argparse
from pathlib import Path

from .generator import generate_quizzes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate quiz versions from course material inputs.")
    parser.add_argument("--input", "-i", dest="input_dir", default="./inputs", help="Path to the course input directory.")
    parser.add_argument("--output", "-o", dest="output_dir", default="./outputs", help="Directory to write output files.")
    parser.add_argument("--N", "--versions", dest="num_versions", type=int, default=4, help="Number of quiz versions to generate.")
    parser.add_argument("--M", "--questions", dest="num_questions", type=int, default=10, help="Number of questions per quiz.")
    parser.add_argument(
        "--T", "--question-type", "--question-style",
        dest="question_type",
        choices=["mixed", "open"],
        default="mixed",
        help="mixed combines multiple-choice and multiple-select questions; open creates open-ended questions.",
    )
    parser.add_argument("--format", dest="output_format", choices=["markdown", "tex"], default="markdown", help="Output format for quiz and answer key files.")
    parser.add_argument(
        "--topic",
        dest="topics",
        nargs="*",
        default=[],
        help='Optional topic filters. Can use topic numbers (e.g., --topic 09 10) or phrases (e.g., --topic "Bayesian")',
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")

    manifest = generate_quizzes(
        input_dir=input_dir,
        output_dir=output_dir,
        num_versions=args.num_versions,
        num_questions=args.num_questions,
        question_type=args.question_type,
        output_format=args.output_format,
        topics=args.topics,
    )

    print(f"Generated {len(manifest['quizzes'])} quiz versions in {output_dir}")
    for quiz_file in manifest["quizzes"]:
        print(f"- {quiz_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
