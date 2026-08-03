"""
CodeTurtle — function-level retrieval test

Checks whether the knowledge base / hybrid retriever can return
the actual source of a known function, with the correct repo path.

Usage:
  python -m tests.verification.test_function_retrieval
  python -m tests.verification.test_function_retrieval Graphify-Labs/graphify
  python -m tests.verification.test_function_retrieval Graphify-Labs/graphify graphify/extract.py extract

Does NOT require Ollama. Needs an already-indexed repo (add-repo).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_REPO = "Graphify-Labs/graphify"


@dataclass
class FunctionTarget:
    """Ground-truth target to retrieve."""
    path: str                 # repo-relative path, e.g. graphify/extract.py
    function_name: str        # e.g. extract
    # Optional: substring that MUST appear in retrieved code (signature or body)
    must_contain: List[str] = field(default_factory=list)


@dataclass
class RetrievalHit:
    path: str
    content: str
    source: str  # vector | path | symbol | hybrid | model


def _normalize_path(p: str) -> str:
    return (p or "").replace("\\", "/").lstrip("./")


def _load_model(repo_name: str):
    from core.repository_persistence import RepositoryPersistence
    model = RepositoryPersistence(repo_name).load_repository_model()
    if model is None:
        raise RuntimeError(f"No repository model for {repo_name}. Run add-repo first.")
    return model


def _file_from_model(model, path: str):
    path = _normalize_path(path)
    for f in model.files or []:
        if _normalize_path(f.path) == path:
            return f
    return None


def extract_function_source(file_content: str, function_name: str) -> Optional[str]:
    """
    Best-effort extract of a top-level or nested def/async def from full file text.
    Uses indentation blocks (Python). Good enough for retrieval verification.
    """
    if not file_content or not function_name:
        return None

    # Match def name( or async def name(
    pattern = re.compile(
        rf"^(?P<indent>[ \t]*)(async\s+)?def\s+{re.escape(function_name)}\s*\(",
        re.MULTILINE,
    )
    m = pattern.search(file_content)
    if not m:
        return None

    start = m.start()
    base_indent = m.group("indent")
    lines = file_content[start:].splitlines()
    block = [lines[0]]
    for line in lines[1:]:
        if not line.strip():
            block.append(line)
            continue
        # next line at same or lower indent than def → end of function
        indent = len(line) - len(line.lstrip(" \t"))
        if indent <= len(base_indent) and not line.lstrip().startswith(("#", "@")):
            # allow decorators only before def; after body started, same indent ends fn
            if block and any(x.strip() and not x.strip().startswith("@") for x in block[1:]):
                break
        block.append(line)
    return "\n".join(block).rstrip() + "\n"


def check_ground_truth(model, target: FunctionTarget) -> Tuple[bool, str, Optional[str]]:
    """
    Verify the function exists on disk/model and return its full source from FileModel.content.
    """
    fm = _file_from_model(model, target.path)
    if fm is None:
        return False, f"path not in repository model: {target.path}", None
    content = getattr(fm, "content", "") or ""
    if not content.strip():
        return False, f"empty content for {target.path}", None
    src = extract_function_source(content, target.function_name)
    if not src:
        return False, f"def {target.function_name} not found in {target.path}", None
    for needle in target.must_contain:
        if needle not in src:
            return False, f"ground truth missing expected substring: {needle!r}", src
    return True, f"{len(src)} chars, {src.count(chr(10))+1} lines", src


def retrieve_by_path(kb, path: str, k: int = 8) -> List[RetrievalHit]:
    hits = []
    if hasattr(kb, "get_by_path"):
        docs = kb.get_by_path(_normalize_path(path), k=k) or []
        for d in docs:
            hits.append(
                RetrievalHit(
                    path=_normalize_path((d.metadata or {}).get("path", path)),
                    content=d.page_content or "",
                    source="path",
                )
            )
    return hits


def retrieve_by_vector(kb, query: str, k: int = 8) -> List[RetrievalHit]:
    hits = []
    docs = kb.similarity_search(query, k=k) or []
    for d in docs:
        hits.append(
            RetrievalHit(
                path=_normalize_path((d.metadata or {}).get("path", "")),
                content=d.page_content or "",
                source="vector",
            )
        )
    return hits


def retrieve_hybrid(repo_name: str, kb, query: str, files_changed: List[str], k: int = 8) -> List[RetrievalHit]:
    from core.hybrid_retriever import HybridRetriever

    graph_queries = None
    try:
        from core.repository_intelligence.graph.queries import GraphQueries
        graph_queries = GraphQueries()
    except Exception:
        pass

    retriever = HybridRetriever(
        repo_name,
        kb=kb,
        graph_queries=graph_queries,
        require_kb=True,
    )
    package = retriever.retrieve(
        query=query,
        pr_understanding={},
        files_changed=files_changed,
        k=k,
        use_calls=True,
        fail_if_empty=False,
    )

    hits = []
    evidences = getattr(package, "evidences", None) or []
    for ev in evidences:
        path = getattr(ev, "path", None) or (getattr(ev, "metadata", {}) or {}).get("path", "")
        content = (
            getattr(ev, "page_content", None)
            or getattr(ev, "content", None)
            or getattr(ev, "code", None)
            or ""
        )
        hits.append(
            RetrievalHit(
                path=_normalize_path(str(path)),
                content=str(content),
                source="hybrid",
            )
        )
    # fallback: summary only packages
    if not hits and getattr(package, "summary", None):
        hits.append(RetrievalHit(path="", content=package.summary, source="hybrid_summary"))
    return hits


def score_hits(
    hits: List[RetrievalHit],
    target: FunctionTarget,
    ground_truth_src: str,
) -> dict:
    """
    Evaluate whether retrieval recovered the function.
    """
    path_ok = any(_normalize_path(h.path) == _normalize_path(target.path) for h in hits if h.path)
    name_in_content = any(target.function_name in (h.content or "") for h in hits)

    # signature-ish presence
    sig_pat = re.compile(rf"def\s+{re.escape(target.function_name)}\s*\(")
    signature_ok = any(sig_pat.search(h.content or "") for h in hits)

    # overlap with ground-truth body (crude but effective)
    gt_lines = {
        ln.strip()
        for ln in ground_truth_src.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    }
    best_overlap = 0.0
    best_hit = None
    for h in hits:
        if not h.content:
            continue
        got = {ln.strip() for ln in h.content.splitlines() if ln.strip()}
        if not gt_lines:
            continue
        overlap = len(gt_lines & got) / max(len(gt_lines), 1)
        if overlap > best_overlap:
            best_overlap = overlap
            best_hit = h

    must_ok = True
    for needle in target.must_contain:
        if not any(needle in (h.content or "") for h in hits):
            must_ok = False
            break

    # "whole function" heuristic: signature present AND high line overlap OR very long chunk containing def
    whole = signature_ok and best_overlap >= 0.6

    return {
        "n_hits": len(hits),
        "path_match": path_ok,
        "name_in_content": name_in_content,
        "signature_found": signature_ok,
        "must_contain_ok": must_ok,
        "line_overlap_with_gt": round(best_overlap, 3),
        "whole_function_likely": whole,
        "best_path": best_hit.path if best_hit else None,
        "best_source": best_hit.source if best_hit else None,
        "best_preview": (best_hit.content[:400] + "…") if best_hit and best_hit.content else None,
    }


def run_case(repo_name: str, kb, model, target: FunctionTarget) -> bool:
    print("\n" + "=" * 72)
    print(f"TARGET  {target.path} :: {target.function_name}()")
    print("=" * 72)

    ok, detail, gt = check_ground_truth(model, target)
    if not ok:
        print(f"  FAIL  ground truth — {detail}")
        return False
    print(f"  PASS  ground truth — {detail}")
    print("  --- ground truth signature line ---")
    print("  " + (gt.splitlines()[0] if gt else ""))

    queries = [
        f"{target.function_name}",
        f"def {target.function_name}",
        f"{target.path} {target.function_name}",
        f"function {target.function_name} in {target.path}",
    ]

    all_pass = True

    # A) Path fetch
    print("\n  [A] get_by_path")
    path_hits = retrieve_by_path(kb, target.path, k=10)
    s = score_hits(path_hits, target, gt)
    _print_score(s)
    if not (s["path_match"] and (s["signature_found"] or s["line_overlap_with_gt"] >= 0.3)):
        all_pass = False
        print("  FAIL  path retrieval did not return function body/signature")
    else:
        print("  PASS  path retrieval")

    # B) Vector search
    print("\n  [B] vector similarity_search")
    best_vec = None
    for q in queries:
        hits = retrieve_by_vector(kb, q, k=8)
        sc = score_hits(hits, target, gt)
        if best_vec is None or sc["line_overlap_with_gt"] > best_vec[1]["line_overlap_with_gt"]:
            best_vec = (q, sc, hits)
    q, s, _ = best_vec
    print(f"  best query: {q!r}")
    _print_score(s)
    if not (s["signature_found"] or s["line_overlap_with_gt"] >= 0.25 or s["path_match"]):
        all_pass = False
        print("  FAIL  vector search weak for this function")
    else:
        print("  PASS  vector search (usable)")

    # C) Hybrid
    print("\n  [C] HybridRetriever")
    hq = f"{target.path}\ndef {target.function_name}\n{target.function_name}"
    hybrid_hits = retrieve_hybrid(
        repo_name,
        kb,
        query=hq,
        files_changed=[target.path],
        k=8,
    )
    s = score_hits(hybrid_hits, target, gt)
    _print_score(s)
    if not (s["path_match"] or s["signature_found"] or s["line_overlap_with_gt"] >= 0.25):
        all_pass = False
        print("  FAIL  hybrid retrieval weak for this function")
    else:
        print("  PASS  hybrid retrieval (usable)")

    # Strict bar for "whole function"
    print("\n  [D] whole-function bar (overlap >= 0.6 and signature)")
    strict = score_hits(path_hits + hybrid_hits, target, gt)
    if strict["whole_function_likely"]:
        print("  PASS  whole function likely present in retrieved chunks")
    else:
        print(
            "  WARN  full function may be split across chunks or truncated "
            f"(overlap={strict['line_overlap_with_gt']})"
        )
        # not hard-fail: chunking often splits large functions
    return all_pass


def _print_score(s: dict) -> None:
    print(
        f"    hits={s['n_hits']} path_match={s['path_match']} "
        f"signature={s['signature_found']} name_in_text={s['name_in_content']} "
        f"overlap={s['line_overlap_with_gt']} whole={s['whole_function_likely']}"
    )
    if s.get("best_path"):
        print(f"    best_path={s['best_path']} via={s['best_source']}")
    if s.get("best_preview"):
        preview = s["best_preview"].replace("\n", "\n    ")
        print(f"    preview:\n    {preview}")


def default_targets(repo_name: str, model) -> List[FunctionTarget]:
    """
    Auto-pick a few real functions from the model for Graphify-like repos.
    Falls back to first Python file with a def.
    """
    preferred = [
        FunctionTarget("graphify/extract.py", "extract", must_contain=["def extract"]),
        FunctionTarget("graphify/build.py", "build", must_contain=["def build"]),
        FunctionTarget("graphify/paths.py", "normalize", must_contain=[]),
    ]
    found = []
    for t in preferred:
        ok, _, _ = check_ground_truth(model, t)
        if ok:
            found.append(t)
        else:
            # try alternate: any function from that file
            fm = _file_from_model(model, t.path)
            if fm and getattr(fm, "symbols", None):
                for sym in fm.symbols:
                    if getattr(sym, "type", "") in ("function", "method") and sym.name:
                        alt = FunctionTarget(t.path, sym.name, must_contain=[f"def {sym.name}"])
                        ok2, _, _ = check_ground_truth(model, alt)
                        if ok2:
                            found.append(alt)
                            break
    if found:
        return found[:3]

    # generic fallback
    for fm in model.files or []:
        if not (fm.path or "").endswith(".py"):
            continue
        content = fm.content or ""
        m = re.search(r"^def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", content, re.M)
        if m:
            return [FunctionTarget(fm.path, m.group(1), must_contain=[f"def {m.group(1)}"])]
    return []


def main() -> int:
    args = sys.argv[1:]
    repo_name = args[0] if args else DEFAULT_REPO
    path = args[1] if len(args) > 1 else None
    fn = args[2] if len(args) > 2 else None

    print(f"Function retrieval test — repo={repo_name}")

    from core.knowledge_base import KnowledgeBase

    model = _load_model(repo_name)
    kb = KnowledgeBase(repo_name.replace("/", "_"))

    if path and fn:
        targets = [FunctionTarget(path, fn, must_contain=[f"def {fn}"])]
    else:
        targets = default_targets(repo_name, model)
        if not targets:
            print("FAIL: could not auto-select any function targets")
            return 1
        print("Auto-selected targets:")
        for t in targets:
            print(f"  - {t.path} :: {t.function_name}")

    results = [run_case(repo_name, kb, model, t) for t in targets]
    passed = sum(1 for r in results if r)
    print("\n" + "=" * 72)
    print(f"SUMMARY  {passed}/{len(results)} targets usable via retrieval")
    if passed == len(results):
        print("RETRIEVAL TEST PASSED")
        return 0
    print("RETRIEVAL TEST FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())