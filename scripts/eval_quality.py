"""Assess actual answers separately from contract/latency smoke tests.

Manual scores are bound to exact answer hashes. Model judging is opt-in and
requires an explicitly configured API; offline mode never invents judge scores.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path

from ai.dialogue import normalize_turn
from ai.generation import Draft, semantic_review
from ai.llm import ChatClient, LLMConfig, LLMError
from ai.planner import make_plan
from ai.retriever import configured_retriever


def answer_hash(answer: str) -> str:
    return hashlib.sha256(answer.encode("utf-8")).hexdigest()


def read_csv(path: Path, column: str) -> dict[str, str]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"id", column} <= set(reader.fieldnames or []):
            raise ValueError(f"CSV must contain id and {column}")
        result = {}
        for row in reader:
            identifier = row["id"]
            if not identifier or identifier in result or not row[column].strip():
                raise ValueError("CSV IDs must be non-empty and unique; text must be non-empty")
            result[identifier] = row[column]
    return result


def assess(
    answers: list[dict],
    questions: dict[str, str],
    references: dict[str, str],
    manual: dict | None = None,
    judge: ChatClient | None = None,
) -> dict:
    if manual is not None and judge is not None:
        raise ValueError("choose manual review or API judge")
    retriever = configured_retriever() if judge else None
    reviews = manual.get("reviews", {}) if manual is not None else {}
    if not isinstance(reviews, dict):
        raise ValueError("manual reviews must be an object keyed by question ID")
    results = []
    seen = set()
    for row in answers:
        identifier = row["id"]
        if identifier in seen or identifier not in questions:
            raise ValueError("answer IDs must be unique and match the questions CSV")
        seen.add(identifier)
        answer = row["answer"]
        item = {
            "id": identifier, "answer_sha256": answer_hash(answer),
            "within_150_words": len(answer.split()) <= 150,
            "has_reference": identifier in references,
            "status": "pending", "method": "none",
        }
        if identifier in reviews:
            review = reviews[identifier]
            if not isinstance(review, dict) or review.get("answer_sha256") != item["answer_sha256"]:
                raise ValueError("manual review is stale or belongs to a different answer")
            for field in ("relevance", "completeness", "context"):
                if type(review.get(field)) is not int or review[field] not in {0, 1, 2}:
                    raise ValueError("manual ratings must be integers 0, 1 or 2")
            if not isinstance(review.get("comment"), str) or not review["comment"].strip():
                raise ValueError("manual review needs an explanatory comment")
            item.update({"status": "reviewed", "method": manual.get("method", "manual_review"),
                         "review": review})
        elif judge is not None:
            message, history = normalize_turn(questions[identifier], [])
            plan = make_plan(message, history)
            hits = retriever.search(plan.query, top_k=8, topic=plan.topic) if retriever else []
            try:
                verdict = semantic_review(
                    judge, message, history, {}, Draft(answer, tuple(row["source_ids"])),
                    hits, plan.contact_declined, reference_answer=references.get(identifier),
                )
                item.update({"status": "approved" if verdict.approved else "rejected",
                             "method": "model_judge", "review": asdict(verdict)})
            except LLMError as exc:
                item.update({"status": "error", "method": "model_judge", "error": str(exc)})
        results.append(item)
    if set(reviews) - seen:
        raise ValueError("manual review contains IDs absent from answers")
    summary = {
        "answers": len(results),
        "over_150_words": sum(not item["within_150_words"] for item in results),
        "pending": sum(item["status"] == "pending" for item in results),
        "manual_reviewed": sum(item["status"] == "reviewed" for item in results),
        "model_judged": sum(item["method"] == "model_judge" and item["status"] != "error" for item in results),
        "model_approved": sum(item["status"] == "approved" for item in results),
        "model_errors": sum(item["status"] == "error" for item in results),
    }
    rated = [item for item in results if item["status"] == "reviewed"]
    if rated:
        summary.update({
            "directly_relevant": sum(item["review"]["relevance"] == 2 for item in rated),
            "partly_relevant": sum(item["review"]["relevance"] == 1 for item in rated),
            "irrelevant": sum(item["review"]["relevance"] == 0 for item in rated),
            "complete": sum(item["review"]["completeness"] == 2 for item in rated),
        })
    return {"summary": summary, "results": results}


def main() -> None:
    parser = argparse.ArgumentParser(description="Quality review; no semantic score without a review")
    parser.add_argument("--answers", type=Path, required=True, help="JSON report produced by scripts.eval_ai")
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--references", type=Path, help="CSV with id,answer; never sent to the generator")
    method = parser.add_mutually_exclusive_group()
    method.add_argument("--manual-review", type=Path)
    method.add_argument("--judge", action="store_true", help="Explicitly send answers and evidence to model API")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--kb", type=Path)
    source.add_argument("--index", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/ai_quality.json"))
    args = parser.parse_args()
    judge = ChatClient(LLMConfig.from_env()) if args.judge else None
    if args.kb:
        os.environ["AI_KB_PATH"] = str(args.kb)
        os.environ.pop("AI_INDEX_PATH", None)
    if args.index:
        os.environ["AI_INDEX_PATH"] = str(args.index)
    questions = read_csv(args.questions, "question")
    references = read_csv(args.references, "answer") if args.references else {}
    manual = json.loads(args.manual_review.read_text(encoding="utf-8")) if args.manual_review else None
    if manual is not None and not isinstance(manual, dict):
        raise ValueError("manual review must be a JSON object")
    report = json.loads(args.answers.read_text(encoding="utf-8"))
    result = assess(report["results"], questions, references, manual=manual, judge=judge)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"Private quality report -> {args.output}")


if __name__ == "__main__":
    main()
