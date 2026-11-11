"""Local contract/latency evaluation, with optional manually labelled retrieval."""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
from statistics import median
from time import perf_counter

from ai.consultant import answer_turn
from ai.dialogue import normalize_turn
from ai.llm import LLMConfig
from ai.planner import make_plan
from ai.retriever import configured_retriever


def evaluate(questions: list[dict], labels: dict | None = None) -> dict:
    rows = []
    recall = []
    reciprocal_rank = []
    retriever = configured_retriever()
    for row in questions:
        started = perf_counter()
        result = answer_turn(row["question"], [], {}, debug=True)
        elapsed = (perf_counter() - started) * 1000
        rows.append({"id": row["id"], **result, "elapsed_ms": round(elapsed, 3),
                     "word_count": len(result["answer"].split())})
        if labels is not None and row["id"] in labels:
            expected = labels[row["id"]]
            if not isinstance(expected, list) or not expected or not all(isinstance(item, str) for item in expected):
                raise ValueError("retrieval labels must map question IDs to non-empty lists of source IDs")
            message, history = normalize_turn(row["question"], [])
            plan = make_plan(message, history)
            hits = retriever.search(plan.query, top_k=8, topic=plan.topic) if retriever else []
            sources = list(dict.fromkeys(hit.chunk.source_id for hit in hits))
            recall.append(len(set(sources) & set(expected)) / len(set(expected)))
            reciprocal_rank.append(next((1 / rank for rank, source in enumerate(sources, 1) if source in expected), 0))
    latencies = sorted(row["elapsed_ms"] for row in rows)
    metrics = {
        "questions": len(rows),
        "sourced_answers": sum(bool(row["source_ids"]) for row in rows),
        "handoffs": sum(row["stage"] == "handoff" for row in rows),
        "answers_over_150_words": sum(row["word_count"] > 150 for row in rows),
        "latency_p50_ms": round(median(latencies), 3) if latencies else 0,
        "latency_p95_ms": latencies[max(0, math.ceil(len(latencies) * 0.95) - 1)] if latencies else 0,
        "labelled_questions": len(recall),
        "model_attempts": sum(row["debug"].get("mode") == "llm" for row in rows),
        "generated_answers": sum(row["debug"].get("response_mode") == "generated" for row in rows),
        "extractive_fallbacks": sum(row["debug"].get("response_mode") == "extractive_fallback" for row in rows),
        "semantic_rejections": sum(row["debug"].get("generation", {}).get("status") == "semantic_rejected" for row in rows),
        "model_failures": sum(row["debug"].get("generation", {}).get("status") == "failed" for row in rows),
    }
    if recall:
        metrics["source_recall_at_8_chunks"] = round(sum(recall) / len(recall), 4)
        metrics["source_mrr_at_8_chunks"] = round(sum(reciprocal_rank) / len(reciprocal_rank), 4)
    return {"metrics": metrics, "results": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate standalone answers and latency; model mode is opt-in")
    parser.add_argument("--questions", type=Path, required=True, help="Local CSV with id,question columns")
    parser.add_argument("--mode", choices=("extractive", "llm"), default="extractive")
    parser.add_argument("--limit", type=int, help="Positive number of questions for a small initial run")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--kb", type=Path)
    source.add_argument("--index", type=Path)
    parser.add_argument("--labels", type=Path, help="Optional local JSON: question ID -> expected source IDs")
    parser.add_argument("--output", type=Path, default=Path("data/ai_eval.json"))
    args = parser.parse_args()
    os.environ["AI_MODE"] = args.mode
    if args.mode == "llm":
        LLMConfig.from_env()  # Fail before evaluation if the real model is not configured.
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if args.kb is not None:
        os.environ["AI_KB_PATH"] = str(args.kb)
        os.environ.pop("AI_INDEX_PATH", None)
    if args.index is not None:
        os.environ["AI_INDEX_PATH"] = str(args.index)
    with args.questions.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"id", "question"} <= set(reader.fieldnames or []):
            raise ValueError("questions CSV must contain id and question columns")
        questions = list(reader)
    if args.limit is not None:
        questions = questions[:args.limit]
    labels = json.loads(args.labels.read_text(encoding="utf-8")) if args.labels else None
    if labels is not None and not isinstance(labels, dict):
        raise ValueError("labels must be a JSON object")
    report = evaluate(questions, labels)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    print(f"Private evaluation report -> {args.output}")


if __name__ == "__main__":
    main()
