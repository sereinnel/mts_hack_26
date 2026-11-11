"""Check evaluation bookkeeping; simulated judge replies are not accuracy scores."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from ai.schemas import Chunk, SearchHit
from scripts.eval_quality import answer_hash, assess
from scripts.eval_ai import evaluate
from test_generation import StubClient, approved


class QualityEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.answers = [{"id": "test-1", "answer": "Тестовая телеметрия доступна.", "source_ids": ["alpha.md"]}]
        self.questions = {"test-1": "Доступна ли телеметрия?"}
        self.references = {"test-1": "Телеметрия доступна для теста."}

    def manual(self, **changes):
        review = {"answer_sha256": answer_hash(self.answers[0]["answer"]),
                  "relevance": 2, "completeness": 1, "context": 2, "comment": "Synthetic test assessment"}
        review.update(changes)
        return {"method": "test_manual_review", "reviews": {"test-1": review}}

    def test_no_judge_or_review_means_pending_not_passed(self):
        result = assess(self.answers, self.questions, self.references)
        self.assertEqual(result["summary"]["pending"], 1)
        self.assertEqual(result["summary"]["model_judged"], 0)
        self.assertNotIn("review", result["results"][0])

    def test_manual_review_is_bound_to_exact_answer(self):
        result = assess(self.answers, self.questions, self.references, manual=self.manual())
        self.assertEqual(result["summary"]["directly_relevant"], 1)
        self.assertEqual(result["summary"]["complete"], 0)
        with self.assertRaisesRegex(ValueError, "stale"):
            assess(self.answers, self.questions, self.references, manual=self.manual(answer_sha256="wrong"))

    def test_invalid_ratings_are_not_counted(self):
        for value in (True, "2", 3, -1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                assess(self.answers, self.questions, self.references, manual=self.manual(relevance=value))

    def test_duplicate_answer_ids_cannot_inflate_scores(self):
        with self.assertRaises(ValueError):
            assess(self.answers * 2, self.questions, self.references)

    def test_model_judge_receives_reference_and_cited_evidence(self):
        chunk = Chunk("alpha.md", "alpha.md#0000", "Тест", self.answers[0]["answer"])
        client = StubClient(approved())
        with patch("scripts.eval_quality.configured_retriever") as configured:
            configured.return_value.search.return_value = [SearchHit(chunk, 1, 1, 1)]
            result = assess(self.answers, self.questions, self.references, judge=client)
        self.assertEqual(result["summary"]["model_judged"], 1)
        self.assertEqual(result["summary"]["model_approved"], 1)
        payload = json.loads(client.requests[0][1]["content"])
        self.assertEqual(payload["reference_answer"], self.references["test-1"])
        self.assertEqual(payload["cited_evidence"][0]["text"], chunk.text)

    def test_failed_judge_call_is_an_error_not_an_approved_answer(self):
        chunk = Chunk("alpha.md", "alpha.md#0000", "Тест", self.answers[0]["answer"])
        client = StubClient("unstructured verdict")
        with patch("scripts.eval_quality.configured_retriever") as configured:
            configured.return_value.search.return_value = [SearchHit(chunk, 1, 1, 1)]
            result = assess(self.answers, self.questions, self.references, judge=client)
        self.assertEqual(result["summary"]["model_errors"], 1)
        self.assertEqual(result["summary"]["model_judged"], 0)
        self.assertEqual(result["summary"]["model_approved"], 0)

    def test_extractive_fallback_is_not_counted_as_generated(self):
        response = {"answer": "Синтетическая запасная цитата.", "stage": "qualify", "source_ids": ["alpha.md"],
                    "route": "rag", "updated_facts": {}, "proposed_action": None,
                    "debug": {"mode": "llm", "response_mode": "extractive_fallback",
                              "generation": {"status": "semantic_rejected"}}}
        with patch("scripts.eval_ai.configured_retriever", return_value=None), patch(
            "scripts.eval_ai.answer_turn", return_value=response,
        ):
            result = evaluate([{"id": "test-1", "question": "Синтетический вопрос"}])
        metrics = result["metrics"]
        self.assertEqual(metrics["generated_answers"], 0)
        self.assertEqual(metrics["model_attempts"], 1)
        self.assertEqual(metrics["extractive_fallbacks"], 1)
        self.assertEqual(metrics["semantic_rejections"], 1)
