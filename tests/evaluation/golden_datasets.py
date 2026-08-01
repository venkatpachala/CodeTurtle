"""
Golden datasets for Repository Intelligence structural evaluation.

Graphify-Labs/graphify is a graph-first, AST-based repository intelligence
project. The benchmark below is designed to validate:
- discovery of files/directories
- correct symbol extraction in the correct files
- content preservation
- graph/index integrity
- negative checks
"""

from typing import Dict, List, Tuple

# (file_path, symbol_name, symbol_type)
SymbolExpectation = Tuple[str, str, str]

# (source_symbol, edge_type, target_symbol)
EdgeExpectation = Tuple[str, str, str]

GOLDEN_DATASETS = {
    "Graphify-Labs/graphify": {
        "repo_name": "Graphify-Labs/graphify",
        "description": "Structural correctness golden set for Graphify-Labs/graphify",

        "min_files": 70,
        "max_files": 1000,
        "min_symbols": 200,
        "max_symbols": 10000,
        "min_chunks": 100,
        "max_chunks": 5000,

        "must_exist_directories": [
            ".github",
            "docs",
            "graphify",
            "graphify/extractors",
            "graphify/exporters",
            "graphify/skills",
            "tests",
            "tools",
            "worked",
        ],

        "must_exist_files": [
            "README.md",
            "ARCHITECTURE.md",
            "BENCHMARKS.md",
            "AGENTS.md",
            "pyproject.toml",
            "SECURITY.md",
            "LICENSE",
            "LICENSE-MIT",
            "NOTICE",
            "Dockerfile",
            ".pre-commit-config.yaml",
            ".dockerignore",
            "graphify/__init__.py",
            "graphify/__main__.py",
            "graphify/ingest.py",
            "graphify/analyze.py",
            "graphify/export.py",
            "graphify/validate.py",
            "graphify/report.py",
            "graphify/cluster.py",
            "graphify/dedup.py",
            "graphify/global_graph.py",
            "graphify/symbol_resolution.py",
            "graphify/semantic_cleanup.py",
            "docs/how-it-works.md",
            "docs/docker-mcp-sqlite.md",
            "docs/node-summaries-rfc.md",
            "scripts/gen_demo_path.py",
            "tests/conftest.py",
            "tests/test_pipeline.py",
            "tests/test_ingest.py",
            "tests/test_export.py",
            "tests/test_validate.py",
            "tests/test_paths.py",
            "tests/test_querylog.py",
            "tests/test_global_graph.py",
            "tests/test_benchmark.py",
            "tests/test_dedup.py",
        ],

        "expected_symbols": [
            # fill by inspecting file contents
        ],

        "must_not_exist_files": [
            ".git/config",
            "__pycache__/dummy.pyc",
            "node_modules/",
            ".venv/",
            "venv/",
            "dist/",
            "build/",
        ],

        "must_not_contain_symbols": [
            # fill only if you know they should never appear
        ],

        "forbidden_path_substrings": [
            "__pycache__",
            ".git/",
            "node_modules/",
            ".venv/",
            "venv/",
            "dist/",
            "build/",
        ],

        "must_have_content_files": [
            "README.md",
            "ARCHITECTURE.md",
            "BENCHMARKS.md",
            "pyproject.toml",
            "docs/how-it-works.md",
        ],
    }
}


def get_golden(repo_name: str) -> dict:
    if repo_name not in GOLDEN_DATASETS:
        raise ValueError(
            f"No golden dataset defined for '{repo_name}'. "
            f"Available: {list(GOLDEN_DATASETS.keys())}"
        )
    return GOLDEN_DATASETS[repo_name]