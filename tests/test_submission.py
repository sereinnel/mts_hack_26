"""Competition callable and flat-root imports, with simulated model transport."""
from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from ai.llm import ChatClient, LLMConfig, LLMConfigurationError, LLMError
from ai.retriever import Retriever, load_chunks
from ai.submission import answer_question
from scripts.export_ai_modules import export_modules


class SyntheticClient:
    """Generate from supplied test evidence, then return a preset test verdict."""
    def __init__(self):
        self.requests = []

    def complete(self, messages, max_tokens=None):
        payload = json.loads(messages[1]["content"])
        self.requests.append(payload)
        if "evidence" in payload:
            passage = payload["evidence"][0]
            return json.dumps({"answer": passage["text"], "source_ids": [passage["source_id"]]}, ensure_ascii=False)
        return json.dumps({"grounded": True, "relevant": True, "context_consistent": True,
                           "safe_handoff": True, "unsupported_claims": [], "reason": "Synthetic verdict"})


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.kb = self.root / "knowledge-base.zip"
        self.text = "Телеметрия Альфа доступна только на тестовом стенде."
        with ZipFile(self.kb, "w") as stream:
            stream.writestr("synthetic/alpha.md", "# Телеметрия Альфа\n\n" + self.text)
        environment = patch.dict(os.environ, {
            "AI_MODE": "extractive", "AI_INDEX_PATH": str(self.root / "missing-web-index.json"),
            "AI_KB_PATH": str(self.root / "missing-web-corpus.zip"), "DATA_DIR": str(self.root / "missing-data"),
            "LLM_BASE_URL": "https://example.invalid/v1", "LLM_API_KEY": "test-only-key", "LLM_MODEL": "test-model",
            "TOP_K": "8", "MAX_TOKENS": "1600", "TEMPERATURE": "0",
        })
        environment.start()
        self.addCleanup(environment.stop)

    def test_returns_only_ready_text_and_enables_model_without_mutating_environment(self):
        client = SyntheticClient()
        before = dict(os.environ)
        with patch("ai.consultant.ChatClient", return_value=client):
            answer = answer_question("Доступна телеметрия Альфа?", self.kb)
        self.assertEqual(answer, self.text)
        self.assertIsInstance(answer, str)
        self.assertEqual(len(client.requests), 2)
        self.assertEqual(dict(os.environ), before)

    def test_dialogue_is_understood_but_the_next_case_has_no_history_or_facts(self):
        clients = []

        def create_client(config):
            client = SyntheticClient()
            clients.append(client)
            return client

        with patch("ai.consultant.ChatClient", side_effect=create_client):
            answer_question("Пользователь: У нас завод.\nАссистент: Какой вопрос?\n"
                            "Пользователь: Доступна телеметрия Альфа?", self.kb)
            answer_question("Доступна телеметрия Альфа?", self.kb)
        self.assertEqual(clients[0].requests[0]["message"], "Доступна телеметрия Альфа?")
        self.assertEqual(clients[0].requests[0]["session_facts"], {"industry": "manufacturing"})
        self.assertEqual(clients[1].requests[0]["history"], [])
        self.assertEqual(clients[1].requests[0]["session_facts"], {})

    def test_parallel_cases_use_their_own_explicit_corpus(self):
        second = self.root / "second.zip"
        second_text = "Телеметрия Бета доступна в другом тестовом контуре."
        with ZipFile(second, "w") as stream:
            stream.writestr("synthetic/beta.md", "# Телеметрия Бета\n\n" + second_text)
        cases = [("Доступна телеметрия Альфа?", self.kb), ("Доступна телеметрия Бета?", second)] * 3
        before = dict(os.environ)
        with patch("ai.consultant.ChatClient", side_effect=lambda config: SyntheticClient()):
            with ThreadPoolExecutor(max_workers=3) as executor:
                answers = list(executor.map(lambda case: answer_question(*case), cases))
        self.assertEqual(answers, [self.text, second_text] * 3)
        self.assertEqual(dict(os.environ), before)

    def test_prebuilt_json_index_is_supported_without_global_index_setting(self):
        index = self.root / "private-index.json"
        Retriever(load_chunks(self.kb)).save(index)
        with patch("ai.consultant.ChatClient", return_value=SyntheticClient()):
            self.assertEqual(answer_question("Доступна телеметрия Альфа?", index), self.text)

    def test_unconfigured_model_is_not_silently_treated_as_a_model_answer(self):
        variables = ("LLM_BASE_URL", "BASE_URL", "OPENAI_BASE_URL", "LLM_API_KEY", "OPENAI_API_KEY",
                     "LLM_MODEL", "GEN_MODEL", "OPENAI_MODEL")
        with patch.dict(os.environ, {name: "" for name in variables}):
            with self.assertRaises(LLMConfigurationError):
                answer_question("Доступна телеметрия Альфа?", self.kb)

    def test_model_transport_failure_returns_existing_grounded_fallback(self):
        client = SyntheticClient()
        with patch("ai.consultant.ChatClient", return_value=client), patch.object(
            client, "complete", side_effect=LLMError("api_http_503"),
        ):
            answer = answer_question("Доступна телеметрия Альфа?", self.kb)
        self.assertIn(self.text, answer)
        self.assertNotIn("api_http_503", answer)
        self.assertNotIn("\n", answer)

    def test_top_k_bounds_the_evidence_sent_to_model(self):
        with patch.dict(os.environ, {"TOP_K": "1"}), patch(
            "ai.consultant.ChatClient", return_value=(client := SyntheticClient()),
        ):
            answer_question("Доступна телеметрия Альфа?", self.kb)
        self.assertEqual(len(client.requests[0]["evidence"]), 1)

    def test_invalid_question_corpus_and_top_k_fail_explicitly(self):
        with self.assertRaises(ValueError):
            answer_question(" ", self.kb)
        with self.assertRaises(TypeError):
            answer_question(None, self.kb)
        with self.assertRaises(FileNotFoundError):
            answer_question("Вопрос", self.root / "absent.zip")
        with self.assertRaises(TypeError):
            answer_question("Вопрос", {})
        for value in ("0", "31", "not-an-int"):
            with self.subTest(value=value), patch.dict(os.environ, {"TOP_K": value}), self.assertRaises(ValueError):
                answer_question("Вопрос", self.kb)


class OrganizerSettingsTests(unittest.TestCase):
    def test_aliases_and_placeholders_match_the_organizer_environment(self):
        with patch.dict(os.environ, {
            "LLM_BASE_URL": "LLM_BASE_URL", "BASE_URL": "https://example.invalid/v1",
            "LLM_API_KEY": "LLM_API_KEY", "OPENAI_API_KEY": "test-only-key",
            "LLM_MODEL": "LLM_MODEL", "GEN_MODEL": "test-model",
            "MAX_TOKENS": "6000", "TEMPERATURE": "0.25",
        }, clear=True):
            config = LLMConfig.from_env()
        self.assertEqual(config.base_url, "https://example.invalid/v1")
        self.assertEqual(config.model, "test-model")
        self.assertEqual(config.max_tokens, 6000)
        self.assertEqual(config.temperature, 0.25)

    def test_api_request_honors_platform_budget_and_temperature(self):
        config = LLMConfig("https://example.invalid/v1", "fake", "test", max_tokens=6000, temperature=0.25)
        body = json.dumps({"choices": [{"message": {"content": "test"}}]}).encode()
        with patch("ai.llm.urlopen", side_effect=lambda *args, **kwargs: io.BytesIO(body)) as transport:
            ChatClient(config).complete([])
        request = json.loads(transport.call_args.args[0].data)
        self.assertEqual(request["max_tokens"], 6000)
        self.assertEqual(request["temperature"], 0.25)
        with patch("ai.llm.urlopen", side_effect=lambda *args, **kwargs: io.BytesIO(body)) as transport:
            ChatClient(LLMConfig("https://example.invalid/v1", "fake", "test", max_tokens=256)).complete([], max_tokens=1000)
        self.assertEqual(json.loads(transport.call_args.args[0].data)["max_tokens"], 256)

    def test_invalid_model_sampling_settings_fail_without_echoing_secrets(self):
        base = {"LLM_BASE_URL": "https://example.invalid/v1", "LLM_API_KEY": "test-only-secret", "LLM_MODEL": "test"}
        for changes in ({"MAX_TOKENS": "0"}, {"MAX_TOKENS": "bad"}, {"MAX_TOKENS": "99999"},
                        {"TEMPERATURE": "nan"}, {"TEMPERATURE": "3"}):
            with self.subTest(changes=changes), patch.dict(os.environ, base | changes, clear=True):
                with self.assertRaises(LLMConfigurationError) as caught:
                    LLMConfig.from_env()
                self.assertNotIn("test-only-secret", str(caught.exception))


class FlatExportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_generated_modules_have_no_package_relative_or_ai_imports(self):
        files = export_modules(self.root / "stage")
        self.assertIn("energytool_ai.py", [path.name for path in files])
        self.assertTrue(all(path.parent == self.root / "stage" for path in files))
        for path in files:
            tree = ast.parse(path.read_text(), filename=str(path), feature_version=(3, 11))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    self.assertEqual(node.level, 0)
                    self.assertNotEqual(node.module, "ai")
                    self.assertFalse((node.module or "").startswith("ai."))
                if isinstance(node, ast.Import):
                    self.assertFalse(any(alias.name == "ai" or alias.name.startswith("ai.") for alias in node.names))

    def test_export_is_reproducible_and_never_overwrites_other_files(self):
        stage = self.root / "stage"
        files = export_modules(stage)
        before = {path.name: path.read_text() for path in files}
        sentinel = stage / "backend-owned.txt"
        sentinel.write_text("preserve")
        export_modules(stage)
        self.assertEqual({path.name: path.read_text() for path in files}, before)
        files[0].write_text("local modification")
        with self.assertRaises(FileExistsError):
            export_modules(stage)
        self.assertEqual(files[0].read_text(), "local modification")
        export_modules(stage, overwrite=True)
        self.assertEqual({path.name: path.read_text() for path in files}, before)
        self.assertEqual(sentinel.read_text(), "preserve")

    def test_flat_archive_imports_and_calls_model_without_repo_or_site_packages(self):
        files = export_modules(self.root / "stage")
        archive = self.root / "modules.zip"
        with ZipFile(archive, "w") as stream:
            for path in files:
                stream.write(path, arcname=path.name)
        isolated = self.root / "isolated"
        with ZipFile(archive) as stream:
            self.assertTrue(all("/" not in name and name.endswith(".py") for name in stream.namelist()))
            stream.extractall(isolated)
        kb = self.root / "knowledge-base.zip"
        with ZipFile(kb, "w") as stream:
            stream.writestr("synthetic/alpha.md", "# Телеметрия\n\nТелеметрия доступна на тестовом стенде.")
        probe = isolated / "probe.py"
        probe.write_text('''import io, json, os, sys
from unittest.mock import patch
from energytool_ai import answer_question

def fake_open(request, timeout):
    body = json.loads(request.data)
    assert body["model"] == "test-model"
    payload = json.loads(body["messages"][1]["content"])
    if "evidence" in payload:
        passage = payload["evidence"][0]
        content = {"answer": passage["text"], "source_ids": [passage["source_id"]]}
    else:
        content = {"grounded": True, "relevant": True, "context_consistent": True,
                   "safe_handoff": True, "unsupported_claims": [], "reason": "Synthetic verdict"}
    return io.BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps(content)}}]}).encode())

with patch("energytool_ai_llm.urlopen", side_effect=fake_open) as transport:
    answer = answer_question("Доступна телеметрия?", sys.argv[1])
    assert transport.call_count == 2
assert os.environ["AI_MODE"] == "extractive"
assert not {"ai", "backend", "fastapi", "sqlite3", "httpx", "openai"} & set(sys.modules)
print(json.dumps({"answer": answer, "model_calls": transport.call_count}, ensure_ascii=False))
''', encoding="utf-8")
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment.update({"AI_MODE": "extractive", "AI_INDEX_PATH": "missing-web-index.json",
                            "LLM_BASE_URL": "https://example.invalid/v1", "LLM_API_KEY": "test-only-key",
                            "LLM_MODEL": "test-model", "TOP_K": "8", "MAX_TOKENS": "1600", "TEMPERATURE": "0",
                            "PYTHONDONTWRITEBYTECODE": "1"})
        process = subprocess.run([sys.executable, "-S", str(probe), str(kb)], cwd=self.root,
                                 env=environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result["answer"], "Телеметрия доступна на тестовом стенде.")
        self.assertEqual(result["model_calls"], 2)
