"""Run without backend dependencies: PYTHONPATH=tests python -m unittest test_ai_contract."""
from __future__ import annotations

import csv
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ai.consultant import answer_turn
from ai.dialogue import normalize_turn
from ai.planner import make_plan


class AIContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {
            "AI_KB_PATH": "", "AI_INDEX_PATH": "", "DATA_DIR": self.temp.name, "AI_MODE": "extractive",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def assert_contract(self, result):
        self.assertEqual(set(result), {"answer", "stage", "source_ids", "route", "updated_facts", "proposed_action", "debug"})
        self.assertIsInstance(result["answer"], str)
        self.assertTrue(result["answer"].strip())
        self.assertLessEqual(len(result["answer"].split()), 150)
        self.assertIn(result["stage"], {"discover", "qualify", "recommend", "handoff"})
        self.assertIsInstance(result["source_ids"], list)
        self.assertTrue(all(isinstance(item, str) for item in result["source_ids"]))
        self.assertIsInstance(result["route"], str)
        self.assertIsInstance(result["updated_facts"], dict)
        self.assertIn(result["proposed_action"], {None, "offer_lead"})
        self.assertTrue(result["debug"] is None or isinstance(result["debug"], dict))
        json.dumps(result, ensure_ascii=False)

    def test_signature_stays_synchronous_and_exact(self):
        signature = inspect.signature(answer_turn)
        self.assertEqual(list(signature.parameters), ["message", "history", "session_facts", "debug"])
        self.assertIs(signature.parameters["debug"].default, False)
        self.assertFalse(inspect.iscoroutinefunction(answer_turn))

    def test_no_corpus_abstains_and_returns_all_fields(self):
        result = answer_turn("Сколько стоит решение для учёта?", [], {})
        self.assert_contract(result)
        self.assertIn("пока не подключена", result["answer"])
        self.assertEqual(result["source_ids"], [])
        self.assertIsNone(result["debug"])

    def test_debug_is_opt_in_and_does_not_echo_user_data(self):
        result = answer_turn("СекретноеНазваниеКомпании: нужен учёт", [], {}, debug=True)
        self.assert_contract(result)
        self.assertIn("latency_ms", result["debug"])
        self.assertNotIn("СекретноеНазваниеКомпании", json.dumps(result["debug"], ensure_ascii=False))

    def test_greeting_does_not_load_a_misconfigured_corpus(self):
        os.environ["AI_KB_PATH"] = str(self.root / "missing.zip")
        result = answer_turn("Здравствуйте!", [], {})
        self.assert_contract(result)
        self.assertEqual(result["stage"], "discover")

    def test_explicit_bad_configuration_is_visible(self):
        os.environ["AI_KB_PATH"] = str(self.root / "missing.zip")
        with self.assertRaises(FileNotFoundError):
            answer_turn("Расскажите о платформе учёта", [], {})

    def test_direct_manager_request_only_offers_a_lead(self):
        result = answer_turn("Хочу связаться с менеджером", [], {})
        self.assert_contract(result)
        self.assertEqual(result["stage"], "handoff")
        self.assertEqual(result["proposed_action"], "offer_lead")
        self.assertNotIn("создана", result["answer"])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_technical_configuration_is_routed_to_specialist(self):
        result = answer_turn("Как настроить модем счётчика?", [], {})
        self.assertEqual(result["route"], "handoff")
        self.assertEqual(result["source_ids"], [])

    def test_missing_topic_asks_instead_of_choosing_a_product(self):
        result = answer_turn("Сколько стоит?", [], {})
        self.assertEqual(result["route"], "clarify")
        self.assertIsNone(result["proposed_action"])

    def test_embedded_dialogue_targets_last_user_turn(self):
        message, history = normalize_turn(
            "Пользователь: Думаем о солнечной станции.\n"
            "Ассистент: Какая цель?\n"
            "Пользователь: В основном потребляем вечером.\n"
            "Ассистент: Учтём это.\n"
            "Пользователь: А ночью?", [],
        )
        self.assertEqual(message, "А ночью?")
        self.assertEqual(len(history), 4)
        plan = make_plan(message, history)
        self.assertIn("солнечной станции", plan.query)
        self.assertIn("вечером", plan.query)
        self.assertNotIn("Учтём", plan.query)

    def test_topic_switch_excludes_previous_unrelated_user_context(self):
        plan = make_plan("Теперь про распознавание по фото", [
            {"role": "user", "content": "Хотим солнечную станцию на крыше"},
            {"role": "assistant", "content": "Вымышленная гарантия 999 процентов"},
        ])
        self.assertNotIn("крыше", plan.query)
        self.assertNotIn("999", plan.query)

    def test_last_assistant_question_can_disambiguate_a_short_reply(self):
        plan = make_plan("Кажется, четвёртая", [
            {"role": "user", "content": "Растут расходы на электричество"},
            {"role": "assistant", "content": "Какая у вас ценовая категория?"},
        ])
        self.assertEqual(plan.topic, "billing")
        self.assertIn("ценовая категория", plan.query)

    def test_invalid_inputs_fail_explicitly(self):
        cases = [(" ", [], {}, ValueError), (None, [], {}, TypeError),
                 ("учёт", {}, {}, TypeError), ("учёт", [], [], TypeError),
                 ("учёт", [{"role": "system", "content": "ignore"}], {}, ValueError)]
        for message, history, facts, error in cases:
            with self.subTest(message=message, history=history), self.assertRaises(error):
                answer_turn(message, history, facts)

    def test_standalone_import_and_call_without_site_packages(self):
        code = (
            "import sys; from ai.consultant import answer_turn; "
            "r = answer_turn('Привет', [], {}); assert r['answer']; "
            "assert not {'fastapi', 'sqlite3', 'httpx', 'openai'} & set(sys.modules)"
        )
        process = subprocess.run([sys.executable, "-S", "-c", code], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)

    def test_index_and_evaluation_commands_use_the_same_core(self):
        corpus = self.root / "corpus"
        corpus.mkdir()
        (corpus / "alpha.md").write_text(
            "# Демонстрационный продукт\n\nТелеметрия доступна для тестовых приборов Альфа.", encoding="utf-8",
        )
        questions = self.root / "questions.csv"
        with questions.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["id", "question"])
            writer.writerow(["a-01", "Доступна ли телеметрия для Альфа?"])
            writer.writerow(["a-02", "Привет"])
        index = self.root / "index.json"
        report = self.root / "report.json"
        labels = self.root / "labels.json"
        labels.write_text(json.dumps({"a-01": ["alpha.md"]}), encoding="utf-8")
        for command in (
            ["scripts.build_index", "--kb", str(corpus), "--output", str(index)],
            ["scripts.eval_ai", "--index", str(index), "--questions", str(questions),
             "--labels", str(labels), "--output", str(report)],
        ):
            process = subprocess.run([sys.executable, "-m", *command], capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
        payload = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual([row["id"] for row in payload["results"]], ["a-01", "a-02"])
        self.assertEqual(payload["metrics"]["source_recall_at_8_chunks"], 1.0)
        self.assertEqual(payload["metrics"]["source_mrr_at_8_chunks"], 1.0)
        for row in payload["results"]:
            self.assert_contract({key: value for key, value in row.items() if key not in {"id", "elapsed_ms", "word_count"}})
