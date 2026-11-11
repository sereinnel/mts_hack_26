"""Build a private local index: python -m scripts.build_index --help."""
from __future__ import annotations

import argparse
from pathlib import Path

from ai.retriever import Retriever, load_chunks


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the offline EnergyTool retrieval index")
    parser.add_argument("--kb", type=Path, required=True, help="Private ZIP or directory of Markdown/TXT documents")
    parser.add_argument("--output", type=Path, default=Path("indexes/energytool.json"))
    args = parser.parse_args()
    chunks = load_chunks(args.kb)
    Retriever(chunks).save(args.output)
    print(f"Indexed {len({chunk.source_id for chunk in chunks})} documents, {len(chunks)} chunks -> {args.output}")


if __name__ == "__main__":
    main()
