"""V4 review orchestrator. LangGraph is not on this path."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from core.agent.contract import classify_kind
from core.bundling.builder import BundleBuilder
from core.change_units import attach_change_units, build_change_units
from core.graphctx.symbols import is_valid_symbol, symbols_from_units
from core.positioner import position_candidate
from core.pr_facts import build_pr_facts, normalize_path
from core.reflector import reflect_candidate
from core.runtime.models import Bundle, Candidate, Comment, ReviewResult, comment_from_candidate
from core.verification.diff_index import DiffIndex, build_diff_index
from core.verification.execute import is_pytest_file
from core.verification.policy import coverage_score, decide


def _coverage_from_units(all_units: List[Any], bundles: List[Bundle]) -> Dict[str, Any]:
    packed_ids = set()
    packed_n = 0
    for b in bundles:
        for u in b.units or []:
            uid = getattr(u, "id", None) or (u.get("id") if isinstance(u, dict) else None)
            if uid is not None:
                if uid in packed_ids:
                    continue
                packed_ids.add(uid)
            packed_n += 1
    source_n = 0
    for u in all_units:
        kind = u.get("kind") if isinstance(u, dict) else getattr(u, "kind", "")
        if kind == "source":
            source_n += 1
    total = len(all_units)
    packed = len(packed_ids) if packed_ids else packed_n
    return {
        "units_total": total,
        "units_packed": packed,
        "units_omitted": max(0, total - packed),
        "source_units": source_n,
    }


def _finding_from_comment(c: Comment) -> Dict[str, Any]:
    return {
        "title": c.title,
        "claim": c.claim,
        "file": c.file,
        "symbol": c.symbol,
        "start_line": c.line or c.start_line,
        "severity": c.severity,
        "verification_status": c.verification or "supported",
        "evidence": list(c.evidence_paths or []),
        "source": c.source,
        "bundle_id": c.bundle_id,
        "kind": str(getattr(c, "kind", "") or "defect"),
        "tests_run": bool(getattr(c, "tests_run", False)),
    }


def _bundle_test_paths(bundles: List[Bundle]) -> List[str]:
    out: List[str] = []
    for b in bundles:
        for p in b.paths or []:
            n = normalize_path(p)
            if is_pytest_file(n) and n not in out:
                out.append(n)
    return out


def _log_sandbox(execution: Dict[str, Any]) -> None:
    rec = execution or {}
    if rec.get("skipped"):
        print(f"[Sandbox] skip reason={rec.get('skip_reason') or 'disabled'}")
        return
    print(
        f"[Sandbox] cmd={rec.get('cmd')} exit={rec.get('exit_code')} "
        f"passed={rec.get('passed')} failed={rec.get('failed')}"
    )


def result_to_review_state(result: ReviewResult, context: Any = None) -> Dict[str, Any]:
    """Map ReviewResult onto the existing display / github_review state shape."""
    ctx = context
    facts = dict(getattr(ctx, "pr_facts", None) or {})
    files = list(getattr(ctx, "files_changed", None) or facts.get("files_changed") or [])
    findings = [_finding_from_comment(c) for c in (result.comments or [])]
    pr = getattr(ctx, "pr", None)
    title = ""
    body = ""
    author = ""
    if pr is not None:
        title = str(getattr(pr, "title", "") or "")
        body = str(getattr(pr, "body", "") or "")
        user = getattr(pr, "user", None)
        author = str(getattr(user, "login", "") or "") if user is not None else ""
    if not title:
        title = str(facts.get("title") or "")
    units_payload = dict(getattr(ctx, "change_units_payload", None) or {})
    repo_cfg = getattr(ctx, "repo_cfg", None)
    summary_bits = [f"**{result.decision}** ({result.policy_reason})"]
    if findings:
        summary_bits.append(f"{len(findings)} supported comment(s).")
    else:
        summary_bits.append("No validated findings.")
    summary = " ".join(summary_bits)
    cov = dict(result.coverage or {})
    packed = int(cov.get("units_packed") or 0)
    total = int(cov.get("units_total") or 0)
    classif = str(facts.get("classification") or "")
    ratio, low = coverage_score(
        cov, classification=classif, files_changed=files
    )
    state: Dict[str, Any] = {
        "repo": getattr(ctx, "repo", "") or facts.get("repo") or "",
        "number": getattr(ctx, "number", 0) or facts.get("pr_number") or 0,
        "title": title,
        "body": body,
        "author": author,
        "full_diff": getattr(ctx, "full_diff", "") or "",
        "files_changed": files,
        "pr_facts": facts,
        "pr_head_sha": getattr(ctx, "pr_head_sha", "") or "",
        "recommendation": result.decision,
        "policy_reason": result.policy_reason,
        "validated_findings": findings,
        "findings": findings,
        "review_coverage": cov,
        "coverage_ratio": ratio,
        "coverage_low": low,
        "final_comment": summary,
        "merge_decision": {
            "recommendation": result.decision,
            "policy_reason": result.policy_reason,
            "summary": summary,
            "blocking_issues": [
                f.get("title")
                for f in findings
                if str(f.get("severity") or "").lower()
                in ("medium", "concern", "high", "critical", "blocking")
            ],
        },
        "v4_bundles": [b.to_dict() for b in result.bundles],
        "v4_dropped": list(result.dropped),
        "inline_max": int(getattr(repo_cfg, "inline_max", 8) or 8) if repo_cfg is not None else 8,
        "inline_lockfile": bool(getattr(repo_cfg, "inline_lockfile", False)) if repo_cfg else False,
        "coverage_merge_min": float(getattr(repo_cfg, "coverage_merge_min", 0.5) or 0.5)
        if repo_cfg is not None
        else 0.5,
        "ignore_paths": list(getattr(repo_cfg, "ignore_paths", None) or []) if repo_cfg else [],
        "runtime": "v4",
        "execution_report": dict(result.execution or {}),
        "execute_tests": bool(getattr(ctx, "execute_tests", False)),
        "execute_install": bool(getattr(ctx, "execute_install", False)),
    }
    state.update(units_payload)
    state["review_coverage"] = cov
    state["coverage_ratio"] = ratio
    state["coverage_low"] = low
    state["recommendation"] = result.decision
    state["policy_reason"] = result.policy_reason
    state["validated_findings"] = findings
    state["findings"] = findings
    return state


class ReviewRuntime:
    """intake facts/units → bundles → BundleAgent → Positioner → Reflector → Policy."""

    def __init__(
        self,
        *,
        llm: Optional[Callable[[str], str]] = None,
        graphify_client: Any = None,
        rule_engine: Optional[Callable[..., List[Candidate]]] = None,
        agent: Any = None,
    ):
        self.llm = llm
        self.graphify_client = graphify_client
        self.rule_engine = rule_engine
        self.agent = agent

    def _client(self, repo: str) -> Any:
        if self.graphify_client is not None:
            return self.graphify_client
        if not repo:
            return None
        try:
            from core.repository_knowledge.structural import get_provider_if_available

            return get_provider_if_available(repo)
        except Exception:
            return None

    def _rules(
        self,
        bundles: List[Bundle],
        files_changed: List[str],
        *,
        full_diff: str = "",
        repo_dir: str = "",
    ) -> List[Candidate]:
        fn = self.rule_engine
        if fn is None:
            try:
                from core.rules.engine import run_rule_engine

                fn = run_rule_engine
            except Exception:
                return []
        try:
            return list(
                fn(
                    bundles,
                    files_changed=files_changed,
                    full_diff=full_diff,
                    repo_dir=repo_dir or None,
                )
                or []
            )
        except TypeError:
            try:
                return list(fn(bundles, files_changed=files_changed) or [])
            except TypeError:
                try:
                    return list(fn(bundles) or [])
                except Exception:
                    return []
        except Exception:
            return []

    def _agent_candidates(self, bundle: Bundle, tools: Any) -> List[Candidate]:
        agent = self.agent
        if agent is None:
            from core.agent.bundle_agent import BundleAgent

            agent = BundleAgent(llm=self.llm)
        try:
            return list(agent.run(bundle, tools) or [])
        except Exception:
            return []

    def run(
        self,
        context: Any = None,
        *,
        files_changed: Optional[List[str]] = None,
        full_diff: str = "",
        pr_facts: Optional[dict] = None,
        change_units: Optional[List[Any]] = None,
        repo: str = "",
        classification: str = "",
    ) -> ReviewResult:
        ctx = context
        files = list(
            files_changed
            or getattr(ctx, "files_changed", None)
            or []
        )
        files = [normalize_path(p) for p in files if p]
        diff = full_diff or getattr(ctx, "full_diff", "") or ""
        facts = dict(pr_facts or getattr(ctx, "pr_facts", None) or {})
        if not facts:
            facts = build_pr_facts(
                title=str(facts.get("title") or ""),
                files_changed=files,
                full_diff=diff,
                repo=repo or getattr(ctx, "repo", "") or "",
                pr_number=getattr(ctx, "number", None),
            )
        if not files:
            files = [normalize_path(p) for p in (facts.get("files_changed") or []) if p]
        classif = classification or str(facts.get("classification") or "")
        index: DiffIndex = build_diff_index(diff)

        payload = getattr(ctx, "change_units_payload", None) if ctx is not None else None
        units = list(change_units or [])
        if not units and isinstance(payload, dict) and payload.get("change_units") is not None:
            units = list(payload.get("change_units") or [])
        if not units:
            units = build_change_units(diff, files, index=index)
            if ctx is not None:
                try:
                    ctx.change_units_payload = attach_change_units(
                        {
                            "full_diff": diff,
                            "files_changed": files,
                            "pr_facts": facts,
                        }
                    )
                except Exception:
                    pass

        cfg = getattr(ctx, "repo_cfg", None) if ctx is not None else None
        try:
            from config import settings as _settings

            bundle_max = int(
                getattr(cfg, "bundle_max", None)
                or getattr(_settings, "bundle_max", 4)
                or 4
            )
            agent_steps = int(
                getattr(cfg, "agent_max_steps", None)
                or getattr(_settings, "agent_max_steps", 4)
                or 4
            )
        except Exception:
            bundle_max, agent_steps = 4, 4
        bundles = BundleBuilder().build(
            files_changed=files,
            units=units,
            classification=classif,
            max_bundles=bundle_max,
        )
        repo_name = repo or getattr(ctx, "repo", "") or str(facts.get("repo") or "")
        client = self._client(repo_name)
        repo_dir = str(getattr(ctx, "repo_dir", "") or "")
        if not repo_dir and repo_name:
            try:
                from core.repository_knowledge.paths import resolve_repo_dir

                repo_dir = str(resolve_repo_dir(repo_name))
            except Exception:
                repo_dir = ""

        from core.agent.tools import BundleTools
        from core.agent.bundle_agent import BundleAgent

        if self.agent is None:
            self.agent = BundleAgent(llm=self.llm, max_steps=agent_steps)

        candidates: List[Candidate] = []
        candidates.extend(
            self._rules(bundles, files, full_diff=diff, repo_dir=repo_dir)
        )
        for bundle in bundles:
            bundle.symbols = [
                s
                for s in (symbols_from_units(bundle.units, bundle.paths) or list(bundle.symbols))
                if is_valid_symbol(s)
            ]
            tools = BundleTools(bundle, index=index, client=client)
            candidates.extend(self._agent_candidates(bundle, tools))

        comments: List[Comment] = []
        dropped: List[Dict[str, Any]] = []
        for cand in candidates:
            kind = classify_kind(cand.title, cand.claim, getattr(cand, "kind", None))
            cand.kind = kind
            if kind != "defect":
                dropped.append({**cand.to_dict(), "drop_reason": "note"})
                print(
                    f"[Reflector] DROP reason=note file={cand.file} title={cand.title!r}"
                )
                continue
            line = position_candidate(cand, index)
            keep, reason = reflect_candidate(
                cand,
                files_changed=files,
                index=index,
                line=line,
            )
            if not keep or not line:
                dropped.append({**cand.to_dict(), "drop_reason": reason if not keep else "no_line"})
                continue
            comments.append(comment_from_candidate(cand, line))

        coverage = _coverage_from_units(units, bundles)
        findings = [_finding_from_comment(c) for c in comments]
        bundle_tests = _bundle_test_paths(bundles)
        for f in findings:
            f["related_tests"] = [
                p
                for b in bundles
                if normalize_path(str(f.get("file") or "")) in [
                    normalize_path(x) for x in b.paths
                ]
                for p in b.paths
                if is_pytest_file(p)
            ]

        exec_state = {
            "execute_tests": bool(getattr(ctx, "execute_tests", False)) if ctx is not None else False,
            "execute_install": bool(getattr(ctx, "execute_install", False)) if ctx is not None else False,
            "pr_facts": facts,
            "files_changed": files,
            "validated_findings": findings,
            "findings": findings,
            "sandbox_test_paths": bundle_tests,
            "repo": repo_name,
            "pr_head_sha": str(getattr(ctx, "pr_head_sha", "") or "") if ctx is not None else "",
            "number": getattr(ctx, "number", 0) if ctx is not None else 0,
        }
        from core.verification.execute import execute_tests_node

        try:
            ex_out = execute_tests_node(exec_state)
        except Exception:
            ex_out = {
                "execution_report": {
                    "skipped": True,
                    "skip_reason": "checkout_failed",
                }
            }
        execution = dict(ex_out.get("execution_report") or {})
        if ex_out.get("validated_findings"):
            findings = list(ex_out.get("validated_findings") or findings)
        tests_ran = (
            not execution.get("skipped")
            and int(execution.get("failed") or 0) == 0
            and execution.get("exit_code") in (0, None)
        )
        tests_failed = (not execution.get("skipped")) and (
            int(execution.get("failed") or 0) > 0
            or execution.get("exit_code") not in (None, 0)
        )
        for f in findings:
            if tests_ran:
                f["tests_run"] = True
                f["tests_passed"] = True
            if tests_failed:
                f["tests_run"] = True
        if tests_ran:
            kept_findings = []
            for f in findings:
                blob = f"{f.get('title') or ''} {f.get('claim') or ''}".lower()
                if "test" in blob and (
                    "missing" in blob or "no test" in blob or "add test" in blob
                ):
                    dropped.append({**f, "drop_reason": "tests_passed"})
                    continue
                kept_findings.append(f)
            findings = kept_findings
            titles = {(f.get("file"), f.get("title")) for f in findings}
            comments = [c for c in comments if (c.file, c.title) in titles]
            for c in comments:
                c.tests_run = True
        _log_sandbox(execution)

        decision, policy_reason = decide(
            findings,
            classification=classif,
            coverage=coverage,
            files_changed=files,
            execution=execution,
        )
        ratio, low = coverage_score(
            coverage, classification=classif, files_changed=files
        )
        packed = int(coverage.get("units_packed") or 0)
        total = int(coverage.get("units_total") or 0)
        print(
            f"[Coverage] packed={packed} total={total} ratio={ratio:.2f} "
            f"low={str(low).lower()} → {decision} ({policy_reason})"
        )
        print(f"[Review] Decision={decision} reason={policy_reason}")
        return ReviewResult(
            decision=decision,
            policy_reason=policy_reason,
            comments=comments,
            dropped=dropped,
            bundles=bundles,
            coverage=coverage,
            execution=execution,
        )
