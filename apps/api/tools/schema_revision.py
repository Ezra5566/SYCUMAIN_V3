"""Resolve the Alembic head revision without importing Alembic.

Why this exists
---------------
A release records the schema revision its code expects, so a rollback can be
checked against the database's actual ``alembic_version`` instead of guessed
(see ``docs/deployment-v3.md`` §8). The release build job has no database and
should not install the API's runtime dependencies just to read the migration
graph, so this reads the revision modules directly with the standard library.

It is deliberately strict. "The expected revision" is only meaningful when
there is exactly one head and every parent resolves, so multiple heads, an
unknown parent or a cycle is an error rather than a guess.

Usage
-----
    python3 apps/api/tools/schema_revision.py           # head, one line
    python3 apps/api/tools/schema_revision.py --json    # revision count + file
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"

_TARGETS = ("revision", "down_revision")


def _literal(node: ast.AST) -> object:
    """Return the value of a module-level revision assignment."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(_literal(element) for element in node.elts)
    raise ValueError(f"unsupported expression {ast.dump(node)[:60]}")


def _read_revisions(path: Path) -> tuple[str, tuple[str, ...]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: dict[str, object] = {}
    for statement in tree.body:
        targets: list[str] = []
        value: ast.AST | None = None
        if isinstance(statement, ast.Assign):
            targets = [
                node.id for node in statement.targets if isinstance(node, ast.Name)
            ]
            value = statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(
            statement.target, ast.Name
        ):
            targets = [statement.target.id]
            value = statement.value
        if value is None:
            continue
        for name in targets:
            if name in _TARGETS:
                found[name] = _literal(value)

    if "revision" not in found:
        raise ValueError(f"{path.name}: no module-level `revision`")

    revision = found["revision"]
    if not isinstance(revision, str):
        raise ValueError(f"{path.name}: `revision` is not a string")

    down = found.get("down_revision")
    if down is None:
        parents: tuple[str, ...] = ()
    elif isinstance(down, str):
        parents = (down,)
    elif isinstance(down, tuple) and all(isinstance(p, str) for p in down):
        parents = down
    else:
        raise ValueError(f"{path.name}: `down_revision` is not a revision id")
    return revision, parents


def load(directory: Path = VERSIONS_DIR) -> dict[str, tuple[str, ...]]:
    graph: dict[str, tuple[str, ...]] = {}
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("__"):
            continue
        revision, parents = _read_revisions(path)
        if revision in graph:
            raise ValueError(f"revision {revision} is defined twice")
        graph[revision] = parents
    if not graph:
        raise ValueError(f"no revisions found in {directory}")
    return graph


def head(graph: dict[str, tuple[str, ...]]) -> str:
    referenced = {parent for parents in graph.values() for parent in parents}
    unknown = referenced - graph.keys()
    if unknown:
        raise ValueError(f"unknown parent revision(s): {', '.join(sorted(unknown))}")

    heads = sorted(set(graph) - referenced)
    if len(heads) != 1:
        raise ValueError(f"expected exactly one head, found {len(heads)}: {heads}")
    return heads[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="include the graph size")
    parser.add_argument(
        "--versions",
        type=Path,
        default=VERSIONS_DIR,
        help="directory holding the revision modules",
    )
    args = parser.parse_args(argv)

    try:
        graph = load(args.versions)
        resolved = head(graph)
    except ValueError as error:
        print(f"schema revision error: {error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"head": resolved, "revisions": len(graph)}))
    else:
        print(resolved)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
