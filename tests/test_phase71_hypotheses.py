"""Phase 7.1 — internal hypothesis pool (KEEP | PLAUSIBLE | REJECTED)."""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.finding_validator import validate_finding, validate_findings_node
from core.github_review import build_review_body, is_postable_finding, keep_findings_for_body
from core.hypothesis import (
    KEEP,
    PLAUSIBLE,
    REJECTED,
    UNRESOLVED,
    classify_findings,
    classify_hypothesis,
    classify_hypotheses_node,
)
from core.investigation.loop import run_investigation
from core.investigation.planner import (
    MAX_GRAPHIFY_CALLS_IN_INVESTIGATE,
    MAX_HYPOTHESES,
    findings_to_hypotheses,
    plan_graphify_calls,
)
from core.pr_facts import build_pr_facts
from core.repository_knowledge.models import (
    GraphNode,
    KnowledgeQueryResult,
    NeighborResult,
    PRImpact,
)

LOADER = "api/loaders/sqlserver_loader.py"
SCHEMA = "api/core/schema_loader.py"
PIPELINE = "api/core/pipeline.py"
WORDLIST = ".github/wordlist.txt"
LOCK = "package-lock.json"

DIFF = f"""diff --git a/{LOADER} b/{LOADER}
--- a/{LOADER}
+++ b/{LOADER}
@@ -1,3 +1,10 @@
 class SQLServerLoader:
     def load_schema(self):
         pass
+    def refresh_graph_schema(self):
+        return True
+    def connect(self):
+        cursor = self.connection.cursor()
+        return cursor
"""
FILES = [LOADER, SCHEMA, PIPELINE, WORDLIST]


class FakeProvider:
    def __init__(self, neighbors_text="CALLS pipeline.load in sqlserver_loader.py"):
        self.calls = []
        self.neighbors_text = neighbors_text

    def get_node(self, label):
        self.calls.append(("get_node", label))
        return GraphNode(
            id=label,
            label=label,
            raw={"text": f"node {label} path={LOADER}"},
        )

    def get_neighbors(self, label, relation_filter=None):
        self.calls.append(("get_neighbors", label))
        return NeighborResult(
            node=GraphNode(id=label, label=label),
            raw_text=self.neighbors_text,
        )

    def query(self, question, depth=3):
        self.calls.append(("query", question))
        return KnowledgeQueryResult(question=question, raw_text=f"query:{question}")

    def get_pr_impact(self, pr_number, repo=None):
        self.calls.append(("get_pr_impact", pr_number))
        return PRImpact(pr_number=pr_number, repo=repo, raw_text="impact ok")


def _facts(files=None, diff=None, classification=None):
    facts = build_pr_facts(
        title="SQL Server loader",
        files_changed=list(files if files is not None else FILES),
        full_diff=diff if diff is not None else DIFF,
        pr_number=538,
        repo="FalkorDB/QueryWeaver",
    )
    if classification:
        facts["classification"] = classification
    return facts


def _state(findings, extra=None, files=None, diff=None, classification=None):
    files = list(files if files is not None else FILES)
    diff = DIFF if diff is None else diff
    facts = _facts(files=files, diff=diff, classification=classification)
    st = {
        "repo": "FalkorDB/QueryWeaver",
        "number": 538,
        "title": "SQL Server loader",
        "files_changed": files,
        "full_diff": diff,
        "pr_facts": facts,
        "validated_findings": findings,
        "findings": findings,
        "review_plan": {"investigate": [], "risk_level": "medium"},
        "pr_understanding": {"risk_level": "low", "summary": "add loader"},
    }
    if extra:
        st.update(extra)
    return st


class TestClassifyHypothesis(unittest.TestCase):
    def test_wordlist_naming_rejected(self):
        finding = {
            "title": "Naming and Documentation",
            "claim": "wordlist nit",
            "file": WORDLIST,
            "evidence": [WORDLIST],
        }
        status, extra = classify_hypothesis(
            finding, files_changed=FILES, full_diff=DIFF
        )
        self.assertEqual(status, REJECTED)
        self.assertEqual(extra.get("reason"), "trivia_only")

    def test_empty_file_symbol_in_diff_plausible(self):
        finding = {
            "id": "p-1",
            "title": "schema refresh may fail",
            "claim": "refresh_graph_schema can raise on empty catalog",
            "file": "",
            "evidence": [],
            "symbol": "refresh_graph_schema",
        }
        buf = io.StringIO()
        with redirect_stdout(buf):
            status, extra = classify_hypothesis(
                finding, files_changed=FILES, full_diff=DIFF
            )
            classify_findings([finding], files_changed=FILES, full_diff=DIFF)
        self.assertEqual(status, PLAUSIBLE)
        self.assertEqual(extra.get("reason"), "symbol_in_diff")
        log = buf.getvalue()
        self.assertIn("[Hypotheses] keep=0 plausible=1 rejected=0", log)
        self.assertIn("PLAUSIBLE symbol=refresh_graph_schema", log)

    def test_basename_in_claim_plausible(self):
        finding = {
            "title": "loader cursor leak",
            "claim": "sqlserver_loader.py does not close the cursor",
            "file": "",
            "evidence": [],
        }
        status, extra = classify_hypothesis(
            finding, files_changed=FILES, full_diff=DIFF
        )
        self.assertEqual(status, PLAUSIBLE)
        self.assertEqual(extra.get("file_hint"), LOADER)

    def test_keep_when_l1_l5_pass(self):
        finding = {
            "title": "connect path may leak cursor",
            "claim": "SQLServerLoader.connect does not close the cursor",
            "file": LOADER,
            "evidence": [LOADER],
            "symbol": "SQLServerLoader",
        }
        status, _ = classify_hypothesis(
            finding, files_changed=FILES, full_diff=DIFF
        )
        self.assertEqual(status, KEEP)

    def test_fake_cursor_rejected(self):
        finding = {
            "title": "cursor leak",
            "claim": "FakeCursor is never closed",
            "file": "",
            "symbol": "FakeCursor",
        }
        status, extra = classify_hypothesis(
            finding, files_changed=FILES, full_diff=DIFF
        )
        self.assertEqual(status, REJECTED)
        self.assertEqual(extra.get("reason"), "invented_fake")

    def test_empty_specialist_rejected(self):
        status, extra = classify_hypothesis(
            {"title": "No issues", "claim": ""},
            files_changed=FILES,
            full_diff=DIFF,
        )
        self.assertEqual(status, REJECTED)
        self.assertEqual(extra.get("reason"), "empty_specialist")

    def test_empty_claim_rejected(self):
        status, extra = classify_hypothesis(
            {"title": "", "claim": ""},
            files_changed=FILES,
            full_diff=DIFF,
        )
        self.assertEqual(status, REJECTED)
        self.assertEqual(extra.get("reason"), "empty_claim")

    def test_ok_in_real_claim_is_not_rejected(self):
        finding = {
            "title": "ok path still leaks",
            "claim": "ok handling in SQLServerLoader.connect is missing finally",
            "file": LOADER,
            "evidence": [LOADER],
        }
        status, _ = classify_hypothesis(
            finding, files_changed=FILES, full_diff=DIFF
        )
        self.assertEqual(status, KEEP)


class TestInvestigatePool(unittest.TestCase):
    def test_wordlist_rejected_zero_hops(self):
        finding = {
            "id": "w-1",
            "title": "Naming and Documentation",
            "claim": "wordlist nit",
            "file": WORDLIST,
            "evidence": [WORDLIST],
        }
        classified, pool = self._classify([finding])
        provider = FakeProvider()
        out = run_investigation(
            _state(
                [f for f in classified if f["hypothesis_status"] == KEEP],
                extra={"classified_findings": classified, "hypothesis_pool": pool},
            ),
            provider,
        )
        self.assertTrue(out["investigation_report"]["skipped"])
        self.assertEqual(out["investigation_report"]["reason"], "no_changed_path_hypotheses")
        self.assertEqual(provider.calls, [])

    def test_plausible_symbol_targets_symbol_not_wordlist(self):
        finding = {
            "id": "p-1",
            "title": "schema refresh may fail",
            "claim": "refresh_graph_schema can raise on empty catalog",
            "file": "",
            "evidence": [],
            "symbol": "refresh_graph_schema",
        }
        classified, pool = self._classify([finding])
        self.assertEqual(pool[0]["hypothesis_status"], PLAUSIBLE)
        provider = FakeProvider()
        out = run_investigation(
            _state(
                [],
                extra={"classified_findings": classified, "hypothesis_pool": pool},
            ),
            provider,
        )
        self.assertFalse(out["investigation_report"]["skipped"])
        labels = [c[1] for c in provider.calls if c[0] in ("get_node", "get_neighbors")]
        self.assertIn("refresh_graph_schema", labels)
        blob = " ".join(str(c) for c in provider.calls)
        self.assertNotIn("wordlist", blob.lower())
        hyps = findings_to_hypotheses(pool, files_changed=FILES, full_diff=DIFF)
        self.assertEqual(hyps[0].symbol, "refresh_graph_schema")
        calls = plan_graphify_calls(hyps, pr_number=538, repo="FalkorDB/QueryWeaver")
        self.assertTrue(any(c.symbol == "refresh_graph_schema" for c in calls))
        self.assertTrue(any(c.tool == "get_node" and c.label == "refresh_graph_schema" for c in calls))

    def test_plausible_promoted_keep_after_hop(self):
        finding = {
            "id": "p-1",
            "title": "schema refresh may fail",
            "claim": "refresh_graph_schema can raise on empty catalog",
            "file": "",
            "evidence": [],
            "symbol": "refresh_graph_schema",
        }
        classified, pool = self._classify([finding])
        provider = FakeProvider(neighbors_text=f"DEFINED_IN {LOADER} refresh_graph_schema")
        out = run_investigation(
            _state(
                [],
                extra={"classified_findings": classified, "hypothesis_pool": pool},
            ),
            provider,
        )
        promoted = [
            f
            for f in out["classified_findings"]
            if f.get("id") == "p-1"
        ]
        self.assertEqual(promoted[0]["hypothesis_status"], KEEP)
        self.assertEqual(promoted[0]["file"], LOADER)
        self.assertEqual(out["validated_findings"][0]["file"], LOADER)
        ok, reason = validate_finding(
            out["validated_findings"][0],
            files_changed=FILES,
            paths_in_diff=FILES,
            full_diff=DIFF,
        )
        self.assertTrue(ok, reason)

    def test_unresolved_not_posted(self):
        finding = {
            "id": "p-1",
            "title": "schema refresh may fail",
            "claim": "refresh_graph_schema can raise on empty catalog",
            "file": "",
            "evidence": [],
            "symbol": "refresh_graph_schema",
        }
        classified, pool = self._classify([finding])
        provider = FakeProvider(neighbors_text="no matching path in this blob")
        # Force evidence with no PR source path
        provider.get_node = lambda label: GraphNode(
            id=label, label=label, raw={"text": "opaque node"}
        )
        out = run_investigation(
            _state(
                [],
                extra={"classified_findings": classified, "hypothesis_pool": pool},
            ),
            provider,
        )
        classified_out = out["classified_findings"]
        self.assertEqual(classified_out[0]["hypothesis_status"], UNRESOLVED)
        self.assertEqual(out["validated_findings"], [])
        body_state = {
            "recommendation": "COMMENT",
            "pr_facts": {"classification": "mixed"},
            "validated_findings": out["validated_findings"]
            + [
                {
                    "title": "schema refresh may fail",
                    "file": "",
                    "hypothesis_status": UNRESOLVED,
                    "verification_status": "supported",
                }
            ],
            "validation_report": {"kept": 0, "dropped": 1},
        }
        kept = keep_findings_for_body(body_state)
        self.assertEqual(kept, [])
        body = build_review_body(body_state, sha="s", decision="COMMENT")
        self.assertNotIn("schema refresh may fail", body)
        self.assertFalse(is_postable_finding(classified_out[0]))

    def test_rejected_never_in_pool(self):
        findings = [
            {
                "id": "w-1",
                "title": "Naming and Documentation",
                "claim": "wordlist nit",
                "file": WORDLIST,
                "evidence": [WORDLIST],
            },
            {
                "id": "k-1",
                "title": "connect path may leak cursor",
                "claim": "SQLServerLoader.connect does not close the cursor",
                "file": LOADER,
                "evidence": [LOADER],
                "symbol": "SQLServerLoader",
            },
        ]
        classified, pool = self._classify(findings)
        statuses = {f["id"]: f["hypothesis_status"] for f in classified}
        self.assertEqual(statuses["w-1"], REJECTED)
        self.assertEqual(statuses["k-1"], KEEP)
        self.assertTrue(all(f["hypothesis_status"] != REJECTED for f in pool))
        hyps = findings_to_hypotheses(
            classified, files_changed=FILES, full_diff=DIFF
        )
        self.assertTrue(hyps)
        self.assertTrue(all(h.hypothesis_kind != REJECTED for h in hyps))

    def test_priority_keep_before_plausible_cap_3(self):
        findings = [
            {
                "id": f"p-{i}",
                "title": f"schema refresh {i}",
                "claim": "refresh_graph_schema can raise",
                "file": "",
                "evidence": [],
                "symbol": "refresh_graph_schema",
            }
            for i in range(4)
        ] + [
            {
                "id": "k-1",
                "title": "connect path may leak cursor",
                "claim": "SQLServerLoader.connect does not close the cursor",
                "file": LOADER,
                "evidence": [LOADER],
                "symbol": "SQLServerLoader",
                "needs_investigation": True,
            },
            {
                "id": "k-2",
                "title": "pipeline error handling",
                "claim": "pipeline.run_loader swallows errors",
                "file": PIPELINE,
                "evidence": [PIPELINE],
                "needs_investigation": True,
            },
        ]
        classified, pool = self._classify(findings)
        hyps = findings_to_hypotheses(pool, files_changed=FILES, full_diff=DIFF)
        self.assertLessEqual(len(hyps), MAX_HYPOTHESES)
        self.assertEqual(hyps[0].hypothesis_kind, KEEP)
        self.assertEqual(hyps[0].finding_id, "k-1")

    def test_budget_still_capped(self):
        findings = [
            {
                "id": f"k-{i}",
                "title": f"claim {name}",
                "file": name,
                "evidence": [name],
                "claim": f"check {name}",
                "symbol": "SQLServerLoader",
                "needs_investigation": True,
                "question": "who calls SQLServerLoader",
            }
            for i, name in enumerate([LOADER, SCHEMA, PIPELINE])
        ]
        classified, pool = self._classify(findings)
        provider = FakeProvider()
        out = run_investigation(
            _state(
                [f for f in classified if f["hypothesis_status"] == KEEP],
                extra={"classified_findings": classified, "hypothesis_pool": pool},
            ),
            provider,
        )
        self.assertLessEqual(len(provider.calls), MAX_GRAPHIFY_CALLS_IN_INVESTIGATE)
        self.assertLessEqual(out["investigation_report"]["calls"], MAX_GRAPHIFY_CALLS_IN_INVESTIGATE)
        self.assertLessEqual(len(out["hypotheses"]), MAX_HYPOTHESES)

    def test_lockfile_only_skips_even_with_plausible(self):
        finding = {
            "id": "p-1",
            "title": "schema refresh may fail",
            "claim": "refresh_graph_schema can raise",
            "file": "",
            "evidence": [],
            "symbol": "refresh_graph_schema",
        }
        classified, pool = self._classify([finding])
        facts = build_pr_facts(
            files_changed=[LOCK],
            full_diff="",
            pr_number=571,
            title="lock",
        )
        self.assertEqual(facts.get("classification"), "lockfile-only")
        provider = FakeProvider()
        out = run_investigation(
            {
                "repo": "FalkorDB/QueryWeaver",
                "number": 571,
                "files_changed": [LOCK],
                "full_diff": "",
                "pr_facts": facts,
                "classified_findings": classified,
                "hypothesis_pool": pool,
                "validated_findings": [],
                "review_plan": {"investigate": []},
            },
            provider,
        )
        self.assertTrue(out["investigation_report"]["skipped"])
        self.assertEqual(
            out["investigation_report"]["reason"], "no_changed_path_hypotheses"
        )
        self.assertEqual(provider.calls, [])

    def _classify(self, findings):
        buf = io.StringIO()
        with redirect_stdout(buf):
            keep, plausible, rejected = classify_findings(
                findings, files_changed=FILES, full_diff=DIFF
            )
        return keep + plausible + rejected, keep + plausible


class TestGraphOrderAndPost(unittest.TestCase):
    def test_graph_order_classify_then_investigate_then_validate(self):
        from core.graph import build_review_graph

        g = build_review_graph()
        nodes = set(g.get_graph().nodes)
        self.assertIn("classify_hypotheses", nodes)
        edges = set()
        for e in g.get_graph().edges:
            src = getattr(e, "source", None)
            tgt = getattr(e, "target", None)
            if src is None and isinstance(e, (tuple, list)) and len(e) >= 2:
                src, tgt = e[0], e[1]
            if src and tgt:
                edges.add((str(src), str(tgt)))
        self.assertIn(("classify_hypotheses", "investigate"), edges)
        self.assertIn(("investigate", "validate_findings"), edges)
        self.assertIn(("validate_findings", "verify_findings"), edges)
        self.assertNotIn(("validate_findings", "investigate"), edges)
        for spec in (
            "correctness_agent",
            "code_quality_agent",
            "testing_agent",
            "context_gatherer",
        ):
            self.assertIn((spec, "classify_hypotheses"), edges)

    def test_validate_after_investigate_keep_only(self):
        classified = [
            {
                "id": "k-1",
                "title": "connect path may leak cursor",
                "claim": "SQLServerLoader.connect does not close the cursor",
                "file": LOADER,
                "evidence": [LOADER],
                "category": "correctness",
                "hypothesis_status": KEEP,
            },
            {
                "id": "u-1",
                "title": "schema refresh may fail",
                "claim": "refresh_graph_schema can raise",
                "file": "",
                "evidence": [],
                "symbol": "refresh_graph_schema",
                "category": "correctness",
                "hypothesis_status": UNRESOLVED,
            },
            {
                "id": "p-1",
                "title": "ghost",
                "claim": "not in pr",
                "file": "",
                "hypothesis_status": PLAUSIBLE,
            },
        ]
        out = validate_findings_node(
            {
                "files_changed": FILES,
                "full_diff": DIFF,
                "pr_facts": _facts(),
                "classified_findings": classified,
                "correctness_findings": classified,
                "quality_findings": [],
                "testing_findings": [],
            }
        )
        ids = [f["id"] for f in out["validated_findings"]]
        self.assertEqual(ids, ["k-1"])
        self.assertTrue(all(f.get("hypothesis_status") == KEEP for f in out["validated_findings"]))

    def test_github_body_omits_plausible_and_unresolved(self):
        state = {
            "recommendation": "COMMENT",
            "pr_facts": {"classification": "mixed"},
            "pr_understanding": {"summary": "SQL Server loader"},
            "validated_findings": [
                {
                    "title": "connect path may leak cursor",
                    "file": LOADER,
                    "severity": "concern",
                    "verification_status": "supported",
                    "hypothesis_status": KEEP,
                    "claim": "cursor leak",
                },
                {
                    "title": "PLAUSIBLE ghost title",
                    "file": LOADER,
                    "severity": "nit",
                    "verification_status": "supported",
                    "hypothesis_status": PLAUSIBLE,
                    "claim": "ghost",
                },
                {
                    "title": "UNRESOLVED ghost title",
                    "file": LOADER,
                    "severity": "nit",
                    "verification_status": "supported",
                    "hypothesis_status": UNRESOLVED,
                    "claim": "ghost",
                },
            ],
            "validation_report": {"kept": 1, "dropped": 2},
        }
        kept = keep_findings_for_body(state)
        self.assertEqual([k["title"] for k in kept], ["connect path may leak cursor"])
        body = build_review_body(state, sha="abc", decision="COMMENT")
        self.assertIn(LOADER, body)
        self.assertNotIn("PLAUSIBLE ghost title", body)
        self.assertNotIn("UNRESOLVED ghost title", body)

    def test_classify_node_logs_counts(self):
        findings = [
            {
                "title": "Naming and Documentation",
                "claim": "wordlist nit",
                "file": WORDLIST,
                "evidence": [WORDLIST],
                "category": "code_quality",
            },
            {
                "title": "connect path may leak cursor",
                "claim": "SQLServerLoader.connect does not close the cursor",
                "file": LOADER,
                "evidence": [LOADER],
                "category": "correctness",
            },
            {
                "title": "schema refresh may fail",
                "claim": "refresh_graph_schema can raise on empty catalog",
                "file": "",
                "evidence": [],
                "symbol": "refresh_graph_schema",
                "category": "correctness",
            },
        ]
        state = {
            "files_changed": FILES,
            "full_diff": DIFF,
            "pr_facts": _facts(),
            "correctness_findings": [findings[1], findings[2]],
            "quality_findings": [findings[0]],
            "testing_findings": [],
        }
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = classify_hypotheses_node(state)
        log = buf.getvalue()
        self.assertIn("[Hypotheses] keep=1 plausible=1 rejected=1", log)
        self.assertEqual(out["hypothesis_report"]["keep"], 1)
        self.assertEqual(out["hypothesis_report"]["plausible"], 1)
        self.assertEqual(out["hypothesis_report"]["rejected"], 1)
        self.assertEqual(len(out["hypothesis_pool"]), 2)
        self.assertEqual(len(out["validated_findings"]), 1)
        self.assertEqual(out["validated_findings"][0]["file"], LOADER)

    def test_inline_keep_supported_unchanged(self):
        from core.github_review import build_inline_comments

        sanitizer = "api/sql_utils/sql_sanitizer.py"
        diff = f"""diff --git a/{sanitizer} b/{sanitizer}
--- a/{sanitizer}
+++ b/{sanitizer}
@@ -1,3 +1,8 @@
+class SQLIdentifierQuoter:
+    def quote(self, name):
+        return name
 context
"""
        state = {
            "full_diff": diff,
            "files_changed": [sanitizer],
            "pr_facts": {
                "classification": "source",
                "files_changed": [sanitizer],
                "source_files": [sanitizer],
            },
            "validated_findings": [
                {
                    "title": "quoter",
                    "file": sanitizer,
                    "claim": "SQLIdentifierQuoter quoting",
                    "severity": "concern",
                    "verification_status": "supported",
                    "hypothesis_status": KEEP,
                    "matched_tokens": ["SQLIdentifierQuoter"],
                    "hunk_header": "@@ -1,3 +1,8 @@",
                    "start_line": 2,
                }
            ],
        }
        comments, skipped = build_inline_comments(state, inline_max=8)
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0]["path"], sanitizer)
        self.assertEqual(skipped, 0)


class TestCriticFiltersNonKeep(unittest.TestCase):
    def test_critic_drops_unresolved_titles(self):
        from core.agents import critic_agent
        from core.models import Findings, Finding

        captured = {}

        def fake_gen(**kwargs):
            captured["prompt"] = kwargs.get("prompt") or ""
            return Findings(findings=[])

        state = {
            "validated_findings": [
                {
                    "id": "k-1",
                    "title": "connect path may leak cursor",
                    "claim": "SQLServerLoader.connect does not close the cursor",
                    "file": LOADER,
                    "evidence": [LOADER],
                    "hypothesis_status": KEEP,
                    "verification_status": "supported",
                    "severity": "concern",
                },
                {
                    "id": "u-1",
                    "title": "UNRESOLVED ghost title",
                    "claim": "ghost",
                    "file": LOADER,
                    "evidence": [LOADER],
                    "hypothesis_status": UNRESOLVED,
                    "verification_status": "supported",
                },
            ],
            "findings": [],
            "files_changed": FILES,
            "full_diff": DIFF,
            "pr_facts": _facts(),
            "validation_report": {"ran": True, "raw": 2, "kept": 1, "dropped": 1},
        }
        with patch("core.agents.gateway") as gw:
            gw.generate_structured.side_effect = fake_gen
            critic_agent(state)
        prompt = captured.get("prompt") or ""
        self.assertNotIn("UNRESOLVED ghost title", prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
