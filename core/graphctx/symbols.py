"""Extract identifier symbols from hunk excerpts. No paths, no 'py'."""

from __future__ import annotations

import ast
import re
from typing import Iterable, List, Optional

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DEF_FALLBACK = re.compile(r"(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_CLASS_FALLBACK = re.compile(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)\b")
_FUNC_JS = re.compile(r"(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def is_valid_symbol(sym: str) -> bool:
    s = (sym or "").strip()
    if not s:
        return False
    if s.lower() == "py":
        return False
    if "." in s or "/" in s or "\\" in s:
        return False
    if s.endswith(".py") or s == "*.py":
        return False
    return bool(_IDENT_RE.match(s))


def _strip_diff(excerpt: str) -> str:
    lines: List[str] = []
    for ln in (excerpt or "").splitlines():
        if ln.startswith("@@") or ln.startswith("+++") or ln.startswith("---"):
            continue
        if ln.startswith(("+", "-", " ")):
            lines.append(ln[1:])
        else:
            lines.append(ln)
    return "\n".join(lines)


def _from_ast(src: str) -> List[str]:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        wrapped = "async def __ct_hunk__():\n" + "\n".join(
            "    " + ln if ln.strip() else "    pass" for ln in src.splitlines()
        )
        try:
            tree = ast.parse(wrapped)
        except SyntaxError:
            return []
    names: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if getattr(node, "name", None) and node.name != "__ct_hunk__":
                names.append(node.name)
    return names


def extract_identifiers(excerpt: str, path: str = "") -> List[str]:
    """Identifiers from a hunk excerpt. AST for Python, else def name( fallback."""
    text = _strip_diff(excerpt or "")
    found: List[str] = []
    n = (path or "").replace("\\", "/").lower()
    use_py = n.endswith(".py") or (not n and ("def " in text or "class " in text))
    if use_py:
        found.extend(_from_ast(text))
        if not found:
            found.extend(_DEF_FALLBACK.findall(text))
            found.extend(_CLASS_FALLBACK.findall(text))
    else:
        found.extend(_FUNC_JS.findall(text))
        found.extend(_DEF_FALLBACK.findall(text))
        found.extend(_CLASS_FALLBACK.findall(text))
    out: List[str] = []
    seen = set()
    for s in found:
        if not is_valid_symbol(s):
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    return out


def symbols_from_units(units: Iterable[object], paths: Optional[Iterable[str]] = None) -> List[str]:
    allowed = None
    if paths is not None:
        allowed = {(p or "").replace("\\", "/") for p in paths}
    out: List[str] = []
    seen = set()
    for u in units or []:
        path = ""
        excerpt = ""
        extra: List[str] = []
        if isinstance(u, dict):
            path = str(u.get("path") or "")
            excerpt = str(u.get("excerpt") or "")
            extra = [str(s) for s in (u.get("symbols") or []) if s]
        else:
            path = str(getattr(u, "path", "") or "")
            excerpt = str(getattr(u, "excerpt", "") or "")
            extra = [str(s) for s in (getattr(u, "symbols", None) or []) if s]
        npath = path.replace("\\", "/")
        if allowed is not None and npath not in allowed:
            continue
        for s in list(extract_identifiers(excerpt, path)) + extra:
            if not is_valid_symbol(s):
                continue
            k = s.lower()
            if k in seen:
                continue
            seen.add(k)
            out.append(s)
    return out
