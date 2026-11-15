"""Retrieval tests use artificial corpora and require no private case data."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from ai.retriever import Retriever, chunk_document, configured_retriever, load_chunks
from ai.planner import make_plan


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_search_finds_content_beyond_document_prefix(self):
        source = "# Пример\n\n" + ("Вводный материал о демонстрации.\n\n" * 100)
        source += "## Удалённый раздел\n\nТелеметрия Альфа доступна для тестового прибора."
        chunks = chunk_document("nested/alpha.md", source)
        result = Retriever(chunks).search("Телеметрия Альфа")
        self.assertTrue(result)
        self.assertEqual(result[0].chunk.source_id, "nested/alpha.md")
        self.assertIn("Удалённый раздел", result[0].chunk.heading)
        self.assertIn("Телеметрия", result[0].chunk.text)
        self.assertTrue(all(len(chunk.text) <= 1400 for chunk in chunks))

    def test_both_retrieval_signals_are_computed(self):
        hits = Retriever(chunk_document("alpha.md", "# Телеметрия\n\nТелеметрия Альфа для тестовых приборов.")).search("Телеметрия")
        self.assertGreater(hits[0].lexical_score, 0)
        self.assertGreater(hits[0].character_score, 0)

    def test_character_signal_can_recover_a_typo(self):
        hits = Retriever(chunk_document("alpha.md", "# Телеметрия\n\nТелеметрия.")).search("телеметриа")
        self.assertTrue(hits)
        self.assertEqual(hits[0].lexical_score, 0)
        self.assertGreater(hits[0].character_score, 0)

    def test_unrelated_and_stopword_only_queries_return_no_results(self):
        retriever = Retriever(chunk_document("alpha.md", "# Телеметрия\n\nТестовый прибор Альфа."))
        self.assertEqual(retriever.search("рецепт борща"), [])
        self.assertEqual(retriever.search("и в на"), [])

    def test_ids_preserve_directories_for_same_named_documents(self):
        for folder in ("one", "two"):
            (self.root / folder).mkdir()
            (self.root / folder / "same.md").write_text("# Телеметрия\n\nТест " + folder, encoding="utf-8")
        chunks = load_chunks(self.root)
        self.assertEqual({chunk.source_id for chunk in chunks}, {"one/same.md", "two/same.md"})
        self.assertEqual(len({chunk.chunk_id for chunk in chunks}), len(chunks))

    def test_zip_and_directory_use_identical_ids_and_text(self):
        folder = self.root / "kb"
        (folder / "products").mkdir(parents=True)
        text = "# Телеметрия\n\nСинтетический пример для тестирования."
        (folder / "products" / "alpha.md").write_text(text, encoding="utf-8-sig")
        archive = self.root / "kb.zip"
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("products/alpha.md", text.encode("utf-8-sig"))
            stream.writestr("__MACOSX/._alpha.md", "metadata")
        self.assertEqual(load_chunks(folder), load_chunks(archive))

    def test_zip_invalid_relative_id_is_rejected_without_extraction(self):
        archive = self.root / "invalid.zip"
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("../outside.md", "# Example\n\nContent")
        with self.assertRaises(ValueError):
            load_chunks(archive)
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ["invalid.zip"])

    def test_index_roundtrip_preserves_ranking_and_sources(self):
        chunks = chunk_document("products/alpha.md", "# Телеметрия\n\nТестовый прибор Альфа.")
        retriever = Retriever(chunks)
        index = self.root / "indexes" / "example.json"
        retriever.save(index)
        self.assertEqual(retriever.search("Телеметрия"), Retriever.load(index).search("Телеметрия"))

    def test_unknown_index_version_fails(self):
        index = self.root / "index.json"
        index.write_text('{"version": 999, "chunks": []}', encoding="utf-8")
        with self.assertRaises(ValueError):
            Retriever.load(index)

    def test_cache_refreshes_after_document_change(self):
        document = self.root / "alpha.md"
        document.write_text("# Альфа\n\nТестовая телеметрия.", encoding="utf-8")
        with patch.dict(os.environ, {"AI_KB_PATH": str(self.root), "AI_INDEX_PATH": ""}):
            first = configured_retriever()
            self.assertIs(first, configured_retriever())
            document.write_text("# Бета\n\nДругая синтетическая конфигурация.", encoding="utf-8")
            second = configured_retriever()
            self.assertIsNot(first, second)
            self.assertIn("Бета", second.chunks[0].heading)

    def test_empty_corpus_and_bad_top_k_are_explicit_errors(self):
        with self.assertRaises(ValueError):
            load_chunks(self.root)
        retriever = Retriever(chunk_document("alpha.md", "# Тест\n\nПример."))
        with self.assertRaises(ValueError):
            retriever.search("Пример", top_k=0)

    def test_explicit_topic_does_not_select_another_product(self):
        chunks = chunk_document("solar.md", "# Солнечная генерация\n\nТестовая стоимость приборов Альфа.")
        chunks += chunk_document("meters.md", "# Платформа учёта\n\nТестовая стоимость приборов Бета.")
        hits = Retriever(chunks).search("Стоимость приборов", topic="metering")
        self.assertTrue(hits)
        self.assertEqual({hit.chunk.source_id for hit in hits}, {"meters.md"})

    def test_long_table_stays_whole_and_long_words_are_not_cut(self):
        table = "--------------------\n" + "Альфа    987    тестовая оговорка\n" * 100
        chunks = chunk_document("table.md", "# Таблица\n\n" + table)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, table.strip())
        sentence = " ".join(["демонстрационный"] * 100)
        chunks = chunk_document("prose.md", sentence, max_chars=200)
        self.assertEqual(" ".join(" ".join(chunk.text.split()) for chunk in chunks), sentence)

    def test_metering_acronyms_resolve_to_platform_without_literal_document_match(self):
        chunks = chunk_document("synthetic/platform.md", "# Облачная платформа учёта электроэнергии\n\n"
                                "## Что это\n\nПлатформа собирает показания тестовых приборов и отображает потребление.")
        chunks += chunk_document("synthetic/losses.md", "# Поиск коммерческих потерь\n\n"
                                 "Решение решает задачи на предприятии и выявляет коммерческие потери.")
        retriever = Retriever(chunks)
        for acronym in ("АСКУЭ", "аскуэ", "АИИС КУЭ", "ASKUE"):
            with self.subTest(acronym=acronym):
                question = f"Что такое {acronym} и какие задачи она решает на предприятии?"
                self.assertEqual(make_plan(question, []).topic, "metering")
                hits = retriever.search(question)
                self.assertTrue(hits)
                self.assertEqual({hit.chunk.source_id for hit in hits}, {"synthetic/platform.md"})

    def test_explicit_acronym_switches_away_from_previous_loss_context(self):
        plan = make_plan("Что такое АСКУЭ?", [
            {"role": "user", "content": "Хотим находить коммерческие потери"},
            {"role": "assistant", "content": "Какие данные есть для поиска потерь?"},
        ])
        self.assertEqual(plan.topic, "metering")
        self.assertNotIn("потер", plan.query)
