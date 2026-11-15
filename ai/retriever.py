"""Dependency-free lexical hybrid: BM25 + character TF-IDF, fused with RRF.

This is a reproducible offline baseline, not an embedding-based retriever.
ZIP documents are read in memory; their original relative paths are source IDs.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from functools import lru_cache
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import textwrap
import zipfile

from .schemas import Chunk, SearchHit
from .topics import identify_topic

_WORD = re.compile(r"[a-zа-яё0-9]+", re.I)
_STOP = set("а без бы был была были быть в вам вас ваш ваша ваши вашей вы где да для до его ее если есть еще и из или им их к как какая какие какой когда ли мне можно мы на надо нам нас наш не нет ни но о об он она они от по под при про с со так также то только у уже что чтобы это этот эта эти я хотим хочу вообще примерно сначала потом такой таких этого этом здесь пожалуйста будет будут стоит сможете сможет несколько одном нашей".split())
_SUFFIXES = ("иями", "ами", "ого", "ему", "ому", "ыми", "ими", "иях", "ах", "ях", "ых", "их", "ов", "ев", "ий", "ый", "ой", "ая", "яя", "ую", "юю", "ое", "ее", "ые", "ие", "ам", "ям", "ом", "ем", "ей", "ия", "ию", "а", "я", "ы", "и", "у", "ю", "е", "о")
# Query vocabulary only: these are language mappings, never product assertions.
_EXPANSIONS = (
    (r"\b(?:аскуэ|аиис\s*куэ|askue)\b", "платформа учёта электроэнергии сбор показаний потребление"),
    (r"фасад", "вертикальная поверхность здания"),
    (r"шифер", "шифер кровля"),
    (r"симк|sim|сим-карт", "сим-карты оператор"),
    (r"расшир|нараст|поэтап", "наращивается поэтапный ввод мощность очередями"),
    (r"магазин", "сетевой ретейл точки объекты"),
    (r"цех", "технический учёт оборудование"),
    (r"двухтариф|многотариф", "многотарифный раздельно тарифы тарифная зона"),
    (r"год выпуск", "год производства"),
    (r"невыгод|не окуп", "невыгодно нецелесообразен окупится"),
)


def expanded_query(query: str) -> str:
    lowered = query.lower()
    extra = [terms for pattern, terms in _EXPANSIONS if re.search(pattern, lowered)]
    if identify_topic(query) == "solar" and re.search(r"вечер|ночью", lowered):
        extra.append("ночью ночное потребление выработка накопители")
    if identify_topic(query) == "wholesale" and re.search(r"провер|уч[её]т", lowered):
        extra.append("аудит существующей системы учёта")
    if identify_topic(query) == "metering" and re.search(r"что понадоб|какие (?:данные|сведен)|с чего нач", lowered):
        extra.append("количество тип приборов существующая схема сбора показаний")
    return query + " " + " ".join(extra)


def _stem(word: str) -> str:
    if re.fullmatch(r"[а-я]+", word):
        for suffix in _SUFFIXES:
            if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                return word[:-len(suffix)]
    return word


def words(text: str) -> list[str]:
    return [_stem(word) for word in _WORD.findall(text.lower().replace("ё", "е"))
            if len(word) > 1 and word not in _STOP]


def _grams(text: str) -> Counter:
    result: Counter = Counter()
    for word in words(text):
        padded = "^" + word + "$"
        result.update(padded[index:index + 3] for index in range(len(padded) - 2))
    return result


def _paragraphs(text: str, limit: int) -> list[str]:
    result = []
    for paragraph in re.split(r"\n\s*\n", text.strip()):
        # Preserve table boundaries, even when a table exceeds the soft limit.
        # Otherwise an isolated row can silently lose its column qualifiers.
        if len(paragraph) <= limit or re.search(r"[-_]{5,}", paragraph):
            if paragraph.strip():
                result.append(paragraph.strip())
            continue
        items = re.split(r"\n(?=(?:-\s+|\d+\.\s+))", paragraph)
        if len(items) > 1:
            result.extend(_paragraphs("\n\n".join(items), limit))
            continue
        # Keep normal paragraphs intact; split unusually long ones by sentences.
        group = ""
        for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
            for piece in textwrap.wrap(sentence, width=limit, break_long_words=False, break_on_hyphens=False):
                if group and len(group) + len(piece) + 1 > limit:
                    result.append(group)
                    group = ""
                group = (group + " " + piece).strip()
        if group:
            result.append(group)
    return result


def chunk_document(source_id: str, text: str, max_chars: int = 1400) -> list[Chunk]:
    if max_chars < 200:
        raise ValueError("max_chars must be at least 200")
    chunks = []
    headings: list[tuple[int, str]] = []
    lines: list[str] = []

    def flush() -> None:
        heading = " / ".join(title for _, title in headings) or source_id
        group: list[str] = []
        for paragraph in _paragraphs("\n".join(lines), max_chars):
            if group and len("\n\n".join(group + [paragraph])) > max_chars:
                chunks.append(Chunk(source_id, f"{source_id}#{len(chunks):04d}", heading, "\n\n".join(group)))
                last = group[-1]
                group = [last] if len(last) < max_chars // 3 and len(last) + len(paragraph) + 2 <= max_chars else []
            group.append(paragraph)
        if group:
            chunks.append(Chunk(source_id, f"{source_id}#{len(chunks):04d}", heading, "\n\n".join(group)))
        lines.clear()

    for line in text.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if match:
            flush()
            level = len(match[1])
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, match[2]))
        else:
            lines.append(line)
    flush()
    return chunks


def load_chunks(path: str | Path) -> list[Chunk]:
    path = Path(path)
    documents: list[tuple[str, str]] = []
    if path.is_dir():
        for item in sorted(path.rglob("*")):
            if item.is_file() and item.suffix.lower() in {".md", ".txt"}:
                documents.append((item.relative_to(path).as_posix(), item.read_text(encoding="utf-8-sig")))
    elif path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            seen = set()
            for item in sorted(archive.infolist(), key=lambda entry: entry.filename):
                name = item.filename
                relative = PurePosixPath(name)
                if item.is_dir() or relative.suffix.lower() not in {".md", ".txt"} or "__MACOSX" in relative.parts:
                    continue
                if relative.is_absolute() or ".." in relative.parts or name in seen:
                    raise ValueError("knowledge base contains an invalid or duplicate source ID")
                seen.add(name)
                documents.append((name, archive.read(item).decode("utf-8-sig")))
    else:
        raise ValueError("knowledge base must be a directory or a ZIP archive")
    chunks = [chunk for source_id, text in documents for chunk in chunk_document(source_id, text)]
    if not chunks:
        raise ValueError("knowledge base contains no non-empty Markdown or TXT documents")
    return chunks


class Retriever:
    def __init__(self, chunks: list[Chunk]):
        if not chunks:
            raise ValueError("index must contain chunks")
        if len({chunk.chunk_id for chunk in chunks}) != len(chunks):
            raise ValueError("index contains duplicate chunk IDs")
        self.chunks = tuple(chunks)
        self._terms = [Counter(words(chunk.text) + words(chunk.heading) * 2) for chunk in chunks]
        self._lengths = [sum(terms.values()) for terms in self._terms]
        self._average = sum(self._lengths) / len(chunks) or 1
        self._df = Counter(term for terms in self._terms for term in terms)
        grams = [_grams(chunk.heading + " " + chunk.text) for chunk in chunks]
        frequencies = Counter(gram for vector in grams for gram in vector)
        self._idf = {gram: math.log((1 + len(chunks)) / (1 + count)) + 1 for gram, count in frequencies.items()}
        self._vectors = [self._vector(vector) for vector in grams]

    def _vector(self, counts: Counter) -> dict[str, float]:
        weights = {term: (1 + math.log(count)) * self._idf[term]
                   for term, count in counts.items() if term in self._idf}
        norm = math.sqrt(sum(value * value for value in weights.values())) or 1
        return {term: value / norm for term, value in weights.items()}

    def search(self, query: str, top_k: int = 6, topic: str | None = None) -> list[SearchHit]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        topic = topic or identify_topic(query)
        query = expanded_query(query)
        query_terms = Counter(words(query))
        if not query_terms:
            return []
        lexical = []
        total = len(self.chunks)
        for terms, length in zip(self._terms, self._lengths):
            score = 0.0
            for term, weight in query_terms.items():
                frequency = terms[term]
                if frequency:
                    idf = math.log(1 + (total - self._df[term] + 0.5) / (self._df[term] + 0.5))
                    importance = 0.15 if term.isdecimal() else 1.0
                    score += math.sqrt(weight) * importance * idf * frequency * 2.5 / (frequency + 1.5 * (0.25 + 0.75 * length / self._average))
            lexical.append(score)
        vector = self._vector(_grams(query))
        character = [sum(value * doc.get(term, 0) for term, value in vector.items()) for doc in self._vectors]
        # Shared meaningful stems, or a strong spelling match, are required.
        eligible = [index for index in range(total)
                    if (lexical[index] > 0 or character[index] >= 0.32)
                    and (topic is None or identify_topic(self.chunks[index].heading) in {None, topic})]
        if not eligible:
            return []
        ranks = []
        for scores in (lexical, character):
            ordered = sorted((index for index in eligible if scores[index] > 0), key=lambda index: (-scores[index], self.chunks[index].chunk_id))
            ranks.append({index: rank for rank, index in enumerate(ordered, 1)})
        fused = {index: sum(1 / (60 + ranking[index]) for ranking in ranks if index in ranking) for index in eligible}
        if topic:
            fused = {index: score * (1.4 if identify_topic(self.chunks[index].heading) == topic else 0.7)
                     for index, score in fused.items()}
        ordered = sorted(eligible, key=lambda index: (-fused[index], self.chunks[index].chunk_id))[:top_k]
        return [SearchHit(self.chunks[index], fused[index], lexical[index], character[index]) for index in ordered]

    def query_weights(self, query: str) -> dict[str, float]:
        """Prefer specific terms over ubiquitous product words when selecting prose."""
        return {
            term: math.sqrt(count) * math.log(1 + (len(self.chunks) + 1) / (self._df[term] + 1))
            * (0.15 if term.isdecimal() else 1)
            for term, count in Counter(words(expanded_query(query))).items()
            if self._df[term]
        }

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "chunks": [asdict(chunk) for chunk in self.chunks]}
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    @classmethod
    def load(cls, path: str | Path) -> Retriever:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("version") != 1 or not isinstance(payload.get("chunks"), list):
            raise ValueError("unsupported AI index format")
        chunks = []
        for item in payload["chunks"]:
            if not isinstance(item, dict) or set(item) != {"source_id", "chunk_id", "heading", "text"}:
                raise ValueError("invalid index chunk")
            if not all(isinstance(value, str) and value.strip() for value in item.values()):
                raise ValueError("index chunk fields must be non-empty strings")
            chunks.append(Chunk(**item))
        return cls(chunks)


def _signature(path: Path) -> tuple:
    if path.is_dir():
        return tuple((item.relative_to(path).as_posix(), item.stat().st_mtime_ns, item.stat().st_size)
                     for item in sorted(path.rglob("*")) if item.is_file() and item.suffix.lower() in {".md", ".txt"})
    stat = path.stat()
    return ((stat.st_mtime_ns, stat.st_size),)


@lru_cache(maxsize=4)
def _cached_retriever(path: str, signature: tuple, is_index: bool) -> Retriever:
    return Retriever.load(path) if is_index else Retriever(load_chunks(path))


def retriever_from_path(knowledge_base: str | Path) -> Retriever:
    """Load an explicit corpus/index; never consult global AI path settings."""
    if not isinstance(knowledge_base, (str, Path)):
        raise TypeError("knowledge_base must be a ZIP, directory or JSON index path")
    if isinstance(knowledge_base, str) and not knowledge_base.strip():
        raise ValueError("knowledge_base path must not be empty")
    path = Path(knowledge_base).expanduser().resolve()
    return _cached_retriever(str(path), _signature(path), path.suffix.lower() == ".json")


def configured_retriever() -> Retriever | None:
    index = os.getenv("AI_INDEX_PATH", "").strip()
    knowledge = os.getenv("AI_KB_PATH", "").strip()
    if index or knowledge:
        path = Path(index or knowledge).expanduser().resolve()
        # An explicit misconfiguration is an error, not a silent no-knowledge mode.
        return _cached_retriever(str(path), _signature(path), bool(index))
    data_dir = Path(os.getenv("DATA_DIR", "data"))
    for name in ("knowledge-base.zip", "knowledge_base.zip", "kb.zip"):
        path = data_dir / name
        if path.is_file():
            path = path.resolve()
            return _cached_retriever(str(path), _signature(path), False)
    return None
