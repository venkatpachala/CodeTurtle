"""V4 review orchestrator. LangGraph is not on this path."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from core.agent.contract import classify_kind, proof_complete
from core.bundling.builder import BundleBuilder
from core.change_units import attach_change_units, build_change_units
from core.graphctx.symbols import is_valid_symbol, symbols_from_units
from core.positioner import position_candidate
from core.pr_facts import build_pr_facts, normalize_path
from core.reflector import reflect_candidate
from core.review.finding import ReviewFinding
from core.review.trace import (
    PipelineTrace,
    STAGE_CLASSIFY,
    STAGE_PROOF,
    STAGE_REFLECTOR,
    STAGE_POSITIONER,
    STAGE_VERIFIER,
    STAGE_FINAL,
)
from core.review.timing import TimingRecord, timed
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
        "existing_code": str(getattr(c, "existing_code", "") or ""),
        "invariant": str(getattr(c, "invariant", "") or ""),
        "violating_condition": str(getattr(c, "violating_condition", "") or ""),
        "expected": str(getattr(c, "expected", "") or ""),
        "actual": str(getattr(c, "actual", "") or ""),
        "execution_path": list(getattr(c, "execution_path", None) or []),
        "evidence": list(getattr(c, "evidence", None) or []),
        "counter_evidence": list(getattr(c, "counter_evidence", None) or []),
        "verify_status": str(getattr(c, "verify_status", "") or "candidate"),
        "confidence": float(getattr(c, "confidence", 0.5) or 0.5),
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
        print(f"[Sandbox] skip reason={rec.get('skip_reason') or 'flag_off'}")
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
    # Findings are canonical; the legacy dictionaries remain only for callers
    # that have not yet migrated off ``validated_findings``.
    findings = [f.to_dict() for f in (getattr(result, "findings", None) or [])]
    if not findings:
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
        summary_bits.append(f"{len(findings)} kept comment(s).")
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
        "pipeline_trace": (
            result.pipeline_trace.to_list()
            if getattr(result, "pipeline_trace", None) is not None
            and hasattr(result.pipeline_trace, "to_list") else []
        ),
        "timing": (
            result.timing.to_dict()
            if getattr(result, "timing", None) is not None
            and hasattr(result.timing, "to_dict") else {}
        ),
        "agent_runs": list(getattr(result, "agent_runs", None) or []),
        "pipeline_health": dict(getattr(result, "pipeline_health", None) or {}),
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
        verification_llm: Optional[Callable[[str], str]] = None,
        graphify_client: Any = None,
        rule_engine: Optional[Callable[..., List[Candidate]]] = None,
        agent: Any = None,
    ):
        self.llm = llm
        # Kept separate because verification uses a tiny classification call,
        # while BundleAgent requires a much larger completion budget.
        self.verification_llm = verification_llm
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

    def _agent_candidates(self, bundle: Bundle, tools: Any) -> tuple[List[Candidate], Dict[str, Any]]:
        agent = self.agent
        if agent is None:
            from core.agent.bundle_agent import BundleAgent

            agent = BundleAgent(llm=self.llm)
        try:
            if hasattr(agent, "run_result"):
                result = agent.run_result(bundle, tools)
                record = result.to_dict() if hasattr(result, "to_dict") else dict(result)
                record["bundle_id"] = bundle.id
                return list(getattr(result, "candidates", []) or []), record
            candidates = list(agent.run(bundle, tools) or [])
            return candidates, {"bundle_id": bundle.id, "status": "LEGACY", "candidate_count": len(candidates)}
        except Exception as exc:
            return [], {"bundle_id": bundle.id, "status": "EXCEPTION", "candidate_count": 0,
                        "exception": f"{type(exc).__name__}: {exc}"}

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

        from core.analysis.risk_signals import (
            analyze_risk_signals, attach_signals_to_bundles, attach_signals_to_candidates,
        )
        risk_signals = analyze_risk_signals(
            repo_dir=repo_dir,
            files_changed=files,
            index=index,
        )
        attach_signals_to_bundles(bundles, risk_signals)
        if risk_signals:
            print(f"[RiskSignals] n={len(risk_signals)} kinds={[signal.kind for signal in risk_signals]}")

        from core.agent.tools import BundleTools
        from core.agent.bundle_agent import BundleAgent

        if self.agent is None:
            self.agent = BundleAgent(llm=self.llm, max_steps=agent_steps)

        trace = PipelineTrace()
        timing = TimingRecord()

        candidates: List[Candidate] = []
        agent_runs: List[Dict[str, Any]] = []
        candidates.extend(
            self._rules(bundles, files, full_diff=diff, repo_dir=repo_dir)
        )
        for bundle in bundles:
            bundle.symbols = [
                s
                for s in (symbols_from_units(bundle.units, bundle.paths) or list(bundle.symbols))
                if is_valid_symbol(s)
            ]
            tools = BundleTools(bundle, index=index, client=client, repo_dir=repo_dir or None)
            with timed(timing, "bundle_agent"):
                bundle_candidates, agent_record = self._agent_candidates(bundle, tools)
                candidates.extend(bundle_candidates)
                agent_runs.append(agent_record)

        attach_signals_to_candidates(candidates, risk_signals, index)

        comments: List[Comment] = []
        dropped: List[Dict[str, Any]] = []
        survivors: List[tuple] = []
        for cand in candidates:
            cid = trace.next_candidate_id()
            # Store candidate_id on the candidate for later correlation
            try:
                object.__setattr__(cand, "_candidate_id", cid)
            except Exception:
                pass

            kind = classify_kind(cand.title, cand.claim, getattr(cand, "kind", None))
            cand.kind = kind
            if kind != "defect":
                dropped.append({**cand.to_dict(), "drop_reason": "note"})
                trace.drop(cid, STAGE_CLASSIFY, "note", cand)
                print(
                    f"[Reflector] DROP reason=note file={cand.file} title={cand.title!r}"
                )
                continue
            with timed(timing, "reflect"):
                if not proof_complete(cand.to_dict()):
                    dropped.append({**cand.to_dict(), "drop_reason": "incomplete_proof"})
                    trace.drop(cid, STAGE_PROOF, "incomplete_proof", cand)
                    print(
                        f"[Reflector] DROP reason=incomplete_proof file={cand.file} title={cand.title!r}"
                    )
                    continue
                line = position_candidate(cand, index)
                own_paths = next(
                    (list(b.paths or []) for b in bundles if b.id == cand.bundle_id),
                    None,
                )
                keep, reason = reflect_candidate(
                    cand,
                    files_changed=files,
                    index=index,
                    line=line,
                    bundle_paths=own_paths,
                )
                if not keep or not line:
                    drop_r = reason if not keep else "no_line"
                    dropped.append({**cand.to_dict(), "drop_reason": drop_r})
                    stage = STAGE_POSITIONER if (not line) else STAGE_REFLECTOR
                    trace.drop(cid, stage, drop_r, cand)
                    continue
            trace.keep(cid, STAGE_REFLECTOR, cand, line)
            survivors.append((cand, line))

        from core.runtime.verify_loop import verify_candidates

        with timed(timing, "verify"):
            verified_cands, vdrop = verify_candidates(
                [c for c, _ in survivors],
                index=index,
                bundles=bundles,
                client=client,
                llm=self.verification_llm or self.llm,
            )
        # Record verifier drops with trace
        for vd in vdrop:
            dr = vd.get("drop_reason", "verifier_drop") if isinstance(vd, dict) else "verifier_drop"
            file_ = vd.get("file", "") if isinstance(vd, dict) else ""
            title_ = vd.get("title", "") if isinstance(vd, dict) else ""
            # Best-effort: match by file+title to candidate_id
            matching_cid = next(
                (
                    getattr(c, "_candidate_id", "?")
                    for c, _ in survivors
                    if getattr(c, "file", "") == file_ and getattr(c, "title", "") == title_
                ),
                "?",
            )
            trace.record(matching_cid, STAGE_VERIFIER, "dropped", file=file_, title=title_, drop_reason=dr)
        dropped.extend(vdrop)

        line_by_id = {id(c): ln for c, ln in survivors}
        comments = []
        review_findings: List[ReviewFinding] = []
        finding_counter = 0
        for cand in verified_cands:
            ln = position_candidate(cand, index)
            if ln is None:
                ln = line_by_id.get(id(cand))
            if not ln:
                cid = getattr(cand, "_candidate_id", "?")
                dropped.append({**cand.to_dict(), "drop_reason": "no_line"})
                trace.drop(cid, STAGE_POSITIONER, "no_line", cand)
                continue
            # Build canonical Comment (backward compat)
            comments.append(comment_from_candidate(cand, int(ln)))
            # Build canonical ReviewFinding (new path)
            finding_counter += 1
            fid = f"F-{finding_counter:03d}"
            cid = getattr(cand, "_candidate_id", "?")
            rf = ReviewFinding.from_candidate_and_comment(cand, int(ln), finding_id=fid, candidate_id=cid)
            trace.keep(cid, STAGE_FINAL, cand, int(ln))
            review_findings.append(rf)

        coverage = _coverage_from_units(units, bundles)
        findings = [_finding_from_comment(c) for c in comments]
        bundle_tests = _bundle_test_paths(bundles)

        # Attach related tests to both legacy dict and ReviewFinding
        for f in findings:
            related = [
                p
                for b in bundles
                if normalize_path(str(f.get("file") or "")) in [
                    normalize_path(x) for x in b.paths
                ]
                for p in b.paths
                if is_pytest_file(p)
            ]
            f["related_tests"] = related
        for rf in review_findings:
            rf.related_tests = [
                p
                for b in bundles
                if normalize_path(rf.file) in [normalize_path(x) for x in b.paths]
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

        with timed(timing, "sandbox"):
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
        # Execution is evidence, never a finding filter.  In particular, a
        # green suite does not disprove a missing-test or behavioural finding.
        from core.review.finding import ExecutionEvidence
        evidence = _execution_evidence(execution)
        for rf in review_findings:
            rf.execution = evidence
            trace.keep(rf.candidate_id or "?", "sandbox", None, rf.line)
        for comment in comments:
            comment.tests_run = evidence.status not in ("NOT_RUN", "SKIPPED")
        _log_sandbox(execution)

        with timed(timing, "policy"):
            decision, policy_reason = decide(
                findings,
                classification=classif,
                coverage=coverage,
                files_changed=files,
                execution=execution,
            )
        healthy_statuses = {"VALID_CANDIDATES", "VALID_EMPTY", "LEGACY"}
        unhealthy = [r for r in agent_runs if r.get("status") not in healthy_statuses]
        ratio, low = coverage_score(
            coverage, classification=classif, files_changed=files
        )
        pipeline_health = {
            "healthy": not unhealthy,
            "agent_runs": len(agent_runs),
            "unhealthy_runs": len(unhealthy),
            "unhealthy_statuses": [str(r.get("status")) for r in unhealthy],
            "coverage_ratio": ratio,
            "coverage_adequate": not low,
        }
        # A clean result is meaningful only when every scheduled reviewer
        # completed and the changed executable context was represented.
        if decision == "MERGE" and (unhealthy or low):
            decision = "COMMENT"
            policy_reason = "review_inconclusive"
        timing.total_s = sum(
            timing.to_dict()[k] for k in timing.to_dict() if k != "total_s"
        )
        packed = int(coverage.get("units_packed") or 0)
        total = int(coverage.get("units_total") or 0)
        print(
            f"[Coverage] packed={packed} total={total} ratio={ratio:.2f} "
            f"low={str(low).lower()} (observational)"
        )
        print(f"[Review] Decision={decision} reason={policy_reason}")

        # Print pipeline trace summary
        ts = trace.summary()
        print(
            f"[Trace] candidates={ts.get('total_candidates', 0)} "
            f"final={ts.get('final_findings', 0)} "
            f"drop_reasons={ts.get('drop_reasons', {})}"
        )

        return ReviewResult(
            decision=decision,
            policy_reason=policy_reason,
            comments=comments,
            dropped=dropped,
            bundles=bundles,
            coverage=coverage,
            execution=execution,
            findings=review_findings,
            pipeline_trace=trace,
            timing=timing,
            agent_runs=agent_runs,
            pipeline_health=pipeline_health,
        )


def _execution_evidence(execution: Dict[str, Any]):
    """Translate legacy execution reports into per-finding evidence."""
    from core.review.finding import ExecutionEvidence

    skipped = bool(execution.get("skipped", True))
    reason = str(execution.get("skip_reason") or "")
    if skipped:
        status = "TIMEOUT" if reason == "timeout" else (
            "INSTALL_FAILED" if "install" in reason else "SKIPPED"
        )
    elif execution.get("exit_code") == 0 and not execution.get("failed"):
        status = "PASSED"
    else:
        status = "FAILED"
    return ExecutionEvidence(
        status=status,
        sandbox=not skipped,
        environment=str(execution.get("python_env") or execution.get("env") or ""),
        command=str(execution.get("cmd") or ""),
        exit_code=execution.get("exit_code"),
        passed=execution.get("passed"),
        failed=execution.get("failed"),
        duration_seconds=execution.get("elapsed_s"),
        failed_tests=list(execution.get("failed_names") or []),
    )
