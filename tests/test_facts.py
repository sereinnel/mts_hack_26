"""Fact isolation and grounding regressions using only synthetic documents."""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai.consultant import answer_turn
from ai.critic import review_evidence, select_evidence
from ai.schemas import Chunk, Evidence, SearchHit


class FactTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {"AI_KB_PATH": "", "AI_INDEX_PATH": "", "DATA_DIR": temporary.name, "AI_MODE": "extractive"})
        environment.start()
        self.addCleanup(environment.stop)

    def test_facts_and_history_are_not_mutated_or_aliased(self):
        history = [{"role": "user", "content": "Нужен учёт", "metadata": {"test": True}}]
        facts = {"object": {"meters": ["test-a", "test-b"]}, "arbitrary_team_field": None}
        original = deepcopy((history, facts))
        result = answer_turn("Какие есть решения?", history, facts)
        self.assertEqual(result["updated_facts"], facts)
        result["updated_facts"]["object"]["meters"].append("test-c")
        self.assertEqual((history, facts), original)

    def test_assistant_claims_and_current_numbers_do_not_become_facts(self):
        result = answer_turn("У нас 37 тестовых приборов", [
            {"role": "assistant", "content": "Ваш регион — вымышленный, мощность 987 кВт"},
        ], {})
        self.assertEqual(result["updated_facts"], {})

    def test_new_session_does_not_inherit_previous_facts(self):
        answer_turn("Нужен учёт", [], {"company": "Тестовая Альфа"})
        result = answer_turn("Нужен учёт", [], {})
        self.assertEqual(result["updated_facts"], {})
        self.assertNotIn("Альфа", result["answer"])

    def test_contact_refusals_are_respected(self):
        for message in ("Я пока не готов оставлять телефон", "Не хочу оформлять заявку", "Менеджер мне не нужен"):
            with self.subTest(message=message):
                result = answer_turn(message, [], {})
                self.assertIsNone(result["proposed_action"])

    def test_contact_refusal_is_remembered_until_user_changes_it(self):
        history = [{"role": "user", "content": "Не хочу оставлять контакты"}]
        result = answer_turn("А техническая схема подключения счётчика?", history, {})
        self.assertIsNone(result["proposed_action"])
        result = answer_turn("Теперь хочу связаться с менеджером", history, {})
        self.assertEqual(result["proposed_action"], "offer_lead")

    def test_used_source_is_a_real_relative_document_id(self):
        (self.root / "products").mkdir()
        text = "Телеметрия Альфа работает только в демонстрационном контуре."
        (self.root / "products" / "alpha.md").write_text("# Тестовая телеметрия\n\n" + text, encoding="utf-8")
        os.environ["AI_KB_PATH"] = str(self.root)
        result = answer_turn("Где работает телеметрия Альфа?", [], {}, debug=True)
        self.assertEqual(result["source_ids"], ["products/alpha.md"])
        self.assertIn(text, result["answer"])
        self.assertEqual(result["debug"]["critic"], "extractive_grounding_passed")

    def test_unrelated_question_does_not_get_fake_sources(self):
        (self.root / "alpha.md").write_text("# Альфа\n\nТестовая телеметрия доступна в лаборатории.", encoding="utf-8")
        os.environ["AI_KB_PATH"] = str(self.root)
        result = answer_turn("Напиши рецепт борща", [], {})
        self.assertEqual(result["source_ids"], [])
        self.assertIn("не нашёл", result["answer"])

    def test_critic_rejects_unknown_ids_and_modified_claims(self):
        chunk = Chunk("alpha.md", "alpha.md#0000", "Тест", "Тестовая цена — 987 единиц, только для стенда.")
        hits = [SearchHit(chunk, 1, 1, 1)]
        for evidence in (
            Evidence("invented.md", chunk.chunk_id, chunk.text),
            Evidence(chunk.source_id, chunk.chunk_id, "Тестовая цена — 123 единицы."),
        ):
            with self.subTest(evidence=evidence):
                self.assertFalse(review_evidence([evidence], hits).approved)
        self.assertTrue(review_evidence([Evidence(chunk.source_id, chunk.chunk_id, chunk.text)], hits).approved)

    def test_prohibited_claim_section_is_never_presented_as_a_fact(self):
        chunk = Chunk("alpha.md", "alpha.md#0000", "Альфа / Чего утверждать нельзя", "Телеметрия гарантирует любой результат.")
        hits = [SearchHit(chunk, 1, 1, 1)]
        self.assertEqual(select_evidence("телеметрия", hits), [])
        self.assertFalse(review_evidence([Evidence(chunk.source_id, chunk.chunk_id, chunk.text)], hits).approved)

    def test_whole_paragraph_preserves_a_qualifier(self):
        text = "Тестовый эффект составляет 12 процентов. Это пример, а не гарантия результата."
        chunk = Chunk("alpha.md", "alpha.md#0000", "Тест", text)
        evidence = select_evidence("эффект", [SearchHit(chunk, 1, 1, 1)])
        self.assertEqual(evidence[0].text, text)

    def test_refusal_filters_contact_calls_inside_source_text(self):
        text = "Телеметрия: оставьте заявку для обсуждения.\n\nТелеметрия доступна на тестовом стенде."
        chunk = Chunk("alpha.md", "alpha.md#0000", "Тест", text)
        hits = [SearchHit(chunk, 1, 1, 1)]
        evidence = select_evidence("Телеметрия", hits, avoid_contact=True)
        self.assertEqual(evidence[0].text, "Телеметрия доступна на тестовом стенде.")

    def test_intro_keeps_the_whole_following_list(self):
        text = "Телеметрия требует следующие тестовые данные:\n\n- Канал Альфа.\n- Канал Бета.\n- Канал Гамма."
        chunk = Chunk("alpha.md", "alpha.md#0000", "Тест", text)
        hits = [SearchHit(chunk, 1, 1, 1)]
        evidence = select_evidence("Телеметрия", hits)
        self.assertIn("Канал Альфа", evidence[0].text)
        self.assertIn("Канал Гамма", evidence[0].text)
        self.assertTrue(review_evidence(evidence, hits).approved)

    def test_table_rows_are_not_returned_without_column_labels(self):
        text = "Телеметрия Альфа    987     только для стенда"
        chunk = Chunk("alpha.md", "alpha.md#0000", "Тест", text)
        self.assertEqual(select_evidence("Телеметрия", [SearchHit(chunk, 1, 1, 1)]), [])
