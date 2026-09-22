"""Per-PR deterministic finding/golden matching.

The matcher deliberately records its decisions.  A future LLM judge can be
added at the final tier without making the base benchmark non-reproducible.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

_STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "from", "when", "then",
    "than", "into", "after", "before", "will", "would", "could", "should",
    "may", "might", "cause", "causes", "incorrect", "potential", "issue",
    "code", "change", "changed", "file", "files", "value", "values", "size",
    "expected", "actual", "invariant", "violated", "relevant", "severity",
    "confidence", "verified", "evidence", "path", "user", "users",
}


def _tokens(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9_]{3,}", value.lower())
        if token not in _STOPWORDS
    }


def _comment_parts(item: Dict[str, Any]) -> tuple[str, int | None, str, str, str]:
    path = str(item.get("path") or item.get("file") or "")
    line = item.get("line")
    try: line = int(line) if line is not None else None
    except (TypeError, ValueError): line = None
    text = str(item.get("body") or item.get("comment") or item.get("claim") or "")
    return path, line, text, str(item.get("category") or ""), str(item.get("severity") or "")


def evaluate_pr(prediction: Dict[str, Any], golden_comments: List[Any]) -> Dict[str, Any]:
    """Match one prediction against one PR's goldens, one-to-one."""
    predicted = list(prediction.get("review_comments") or prediction.get("findings") or [])
    goldens = [g if isinstance(g, dict) else vars(g) for g in golden_comments]
    used: set[int] = set(); matches: List[Dict[str, Any]] = []; fps: List[Dict[str, Any]] = []
    for pi, p in enumerate(predicted):
        pp, pl, pt, pc, ps = _comment_parts(p)
        best: tuple[float, str, int] | None = None
        for gi, g in enumerate(goldens):
            if gi in used: continue
            gp, gl, gt, gc, gs = _comment_parts(g)
            score = 0.0; reason = ""
            if pp and gp and pp == gp:
                score += 0.35; reason = "exact_path"
            elif pp and gp:
                continue
            if pl is not None and gl is not None and abs(pl - gl) <= 5:
                score += 0.2; reason = "line_proximity"
            if pc and gc and pc.lower() == gc.lower(): score += 0.1; reason = "category"
            pred_tokens, gold_tokens = _tokens(pt), _tokens(gt)
            overlap = len(pred_tokens & gold_tokens)
            union = len(pred_tokens | gold_tokens)
            semantic = overlap / union if union else 0.0
            containment = overlap / min(len(pred_tokens), len(gold_tokens)) if pred_tokens and gold_tokens else 0.0
            text_score = max(semantic, containment)
            score += text_score
            if semantic >= 0.12 or (overlap >= 2 and containment >= 0.08):
                reason = "semantic_overlap"
            is_match = semantic >= 0.12 or (overlap >= 2 and containment >= 0.08) or (
                pp and gp and pp == gp and overlap >= 2
            )
            if is_match and (best is None or score > best[0]):
                best = (score, reason, gi)
        if best is None:
            fps.append({"prediction_index": pi, "finding": p})
        else:
            gi = best[2]
            used.add(gi); matches.append({"prediction_index": pi, "golden_index": gi, "score": best[0], "reason": best[1], "prediction": p, "golden": goldens[gi]})
    fns = [{"golden_index": i, "golden": g} for i, g in enumerate(goldens) if i not in used]
    return {"tp": len(matches), "fp": len(fps), "fn": len(fns), "matches": matches, "false_positives": fps, "false_negatives": fns}
