"""Export AI source modules flat; does not create solution.py, CSVs or a ZIP."""
from __future__ import annotations

import argparse
import ast
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


class _FlatImports(ast.NodeTransformer):
    def __init__(self, module_names: dict[str, str]):
        self.module_names = module_names

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if not node.level:
            if node.module == "ai" or (node.module or "").startswith("ai."):
                raise ValueError("absolute ai imports must be converted before export")
            return node
        if node.level != 1:
            raise ValueError("only direct package-local imports are supported")
        if node.module is None:
            aliases = []
            for alias in node.names:
                if alias.name not in self.module_names:
                    raise ValueError("unknown package-local module")
                aliases.append(ast.alias(name=self.module_names[alias.name], asname=alias.asname or alias.name))
            return ast.copy_location(ast.Import(names=aliases), node)
        if node.module not in self.module_names:
            raise ValueError("unknown package-local module")
        return ast.copy_location(ast.ImportFrom(module=self.module_names[node.module], names=node.names, level=0), node)

    def visit_Import(self, node: ast.Import):
        if any(alias.name == "ai" or alias.name.startswith("ai.") for alias in node.names):
            raise ValueError("absolute ai imports must be converted before export")
        return node


def export_modules(output: str | Path, *, overwrite: bool = False) -> list[Path]:
    """Generate root-level modules from the canonical ai package, reproducibly."""
    source = Path(__file__).resolve().parents[1] / "ai"
    output = Path(output).resolve()
    if output == source or source in output.parents:
        raise ValueError("export outside the canonical ai source directory")
    sources = sorted(path for path in source.glob("*.py") if path.stem != "__init__")
    names = {path.stem: "energytool_ai" if path.stem == "submission" else f"energytool_ai_{path.stem}"
             for path in sources}
    if "submission" not in names:
        raise ValueError("AI submission entry point is missing")
    generated = {}
    for path in sources:
        tree = _FlatImports(names).visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        ast.fix_missing_locations(tree)
        target = output / (names[path.stem] + ".py")
        content = f"# Generated from ai/{path.name}; edit the canonical source.\n" + ast.unparse(tree) + "\n"
        if target.is_symlink():
            raise FileExistsError("generated module is a symbolic link; use a fresh export directory")
        if target.exists() and not overwrite and target.read_text(encoding="utf-8") != content:
            raise FileExistsError("generated module differs; use a fresh directory or --overwrite")
        generated[target] = content
    output.mkdir(parents=True, exist_ok=True)
    for target, content in generated.items():
        # Replacing a complete file avoids writing through hard links and keeps
        # each existing module intact if generating its replacement fails.
        temporary = None
        try:
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=output, suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
            os.chmod(temporary, 0o644)
            temporary.replace(target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return list(generated)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export flat AI modules for the backend-owned contest ZIP")
    parser.add_argument("--output", type=Path, default=Path("data/submission_ai"))
    parser.add_argument("--overwrite", action="store_true", help="Replace only generated module filenames")
    args = parser.parse_args()
    modules = export_modules(args.output, overwrite=args.overwrite)
    print(f"Exported {len(modules)} root-level modules -> {args.output}")
    print("Entry point: from energytool_ai import answer_question")


if __name__ == "__main__":
    main()
