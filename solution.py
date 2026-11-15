"""MTS Hack&Change 2026 submission entry point (Python 3.11+).

Put this file and the flat energytool_ai*.py exports in the root of the ZIP.
The platform provides DATA_DIR/questions.csv and DATA_DIR/knowledge-base.zip.
Run from the desired working directory; output is ./submission.csv.
"""
from __future__ import annotations

import csv
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


FALLBACK = "Недостаточно достоверной информации для ответа. Пожалуйста, уточните вопрос."
MAX_ANSWER_CHARS = 10_000


def data_directory() -> Path:
    return Path(os.environ.get("DATA_DIR") or "data")


def read_questions(path: Path) -> list[tuple[str, str]]:
    """Read all independent cases, preserving IDs and input order."""
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {"id", "question"}.issubset(reader.fieldnames):
            raise ValueError("questions.csv must have 'id' and 'question' columns")

        rows: list[tuple[str, str]] = []
        seen: set[str] = set()
        for line_number, row in enumerate(reader, start=2):
            identifier = row.get("id")
            if identifier is None or not identifier.strip():
                raise ValueError(f"Missing ID near CSV line {line_number}")
            if identifier in seen:
                raise ValueError(f"Duplicate question ID: {identifier!r}")
            seen.add(identifier)
            question = row.get("question") or ""
            rows.append((identifier, question))

    if not rows:
        raise ValueError("questions.csv has no questions")
    return rows


def worker_count() -> int:
    """Respect the platform limit without creating an unbounded thread pool."""
    value = (os.environ.get("MAX_WORKERS") or "3").strip()
    if value == "MAX_WORKERS":
        value = "3"
    try:
        count = int(value)
    except ValueError:
        count = 3
    return min(8, max(1, count))


def prepare_answer(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("AI answer must be a string")
    answer = value.strip()
    if not answer:
        raise ValueError("AI answer is empty")
    return answer[:MAX_ANSWER_CHARS].rstrip() or FALLBACK


def write_submission(path: Path, rows: list[tuple[str, str]]) -> None:
    """Replace the result only after every answer has been collected."""
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("id", "answer"))
        writer.writerows(rows)
    temporary.replace(path)


def main() -> None:
    root = data_directory()
    questions_path = root / "questions.csv"
    knowledge_base_path = root / "knowledge-base.zip"
    questions = read_questions(questions_path)

    if not knowledge_base_path.is_file():
        raise FileNotFoundError(f"Knowledge base not found: {knowledge_base_path}")

    # Validate input files without a network call or flat AI module export.
    if "--check-input" in sys.argv[1:]:
        print(f"Input OK: {len(questions)} unique questions; knowledge base found")
        return

    # The AI developer provides this module via scripts.export_ai_modules.
    # Import here so --check-input can run before the flat export is prepared.
    from energytool_ai import answer_question

    results: list[tuple[str, str] | None] = [None] * len(questions)
    errors = 0

    def answer_one(index: int, identifier: str, question: str) -> tuple[int, str, str, bool]:
        if not question.strip():
            return index, identifier, "Пожалуйста, уточните вопрос.", False
        try:
            answer = prepare_answer(answer_question(question, knowledge_base_path))
            return index, identifier, answer, True
        except Exception as exc:
            # Do not print exception messages: they may contain an API address or secret.
            print(f"Question {identifier!r} failed: {type(exc).__name__}", file=sys.stderr)
            return index, identifier, FALLBACK, False

    with ThreadPoolExecutor(max_workers=worker_count()) as executor:
        tasks = [
            executor.submit(answer_one, index, identifier, question)
            for index, (identifier, question) in enumerate(questions)
        ]
        for future in as_completed(tasks):
            index, identifier, answer, success = future.result()
            results[index] = (identifier, answer)
            if not success:
                errors += 1

    if errors == len(questions):
        raise RuntimeError("All questions failed. Check LLM proxy configuration and AI modules.")

    write_submission(Path.cwd() / "submission.csv", [row for row in results if row is not None])
    print(f"submission.csv created: {len(questions)} answers; {errors} fallback(s)")


if __name__ == "__main__":
    main()
