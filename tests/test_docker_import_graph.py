"""Regression: production Docker image must include local imports reachable from app.py."""
import ast
import shlex
from pathlib import Path


def test_docker_copies_transitive_startup_imports():
    root = Path(__file__).resolve().parents[1]
    lines = (root / "Dockerfile").read_text(encoding="utf-8").splitlines()
    copied = set()
    for line in lines:
        if line.startswith("COPY "):
            copied.update(shlex.split(line)[1:-1])
    pending = ["app"]
    visited = set()
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        module = root / (name + ".py")
        if not module.is_file():
            continue
        assert module.name in copied, "Dockerfile omitted runtime module: " + module.name
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                candidate = node.module.split(".")[0]
                if (root / (candidate + ".py")).is_file():
                    pending.append(candidate)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    candidate = alias.name.split(".")[0]
                    if (root / (candidate + ".py")).is_file():
                        pending.append(candidate)
    assert {"app", "restaurant_tenants", "bokharest_showcase"} <= visited
