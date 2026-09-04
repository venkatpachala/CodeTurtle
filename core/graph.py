from langgraph.graph import StateGraph, END
from core.state import ReviewState

from core.agents import (
    build_evidence_package,
    correctness_agent,
    code_quality_agent,
    testing_agent,
    critic_agent,
    final_recommender,
    context_summarizer,
    context_gatherer,
)
from core.finding_validator import validate_findings_node
from core.hypothesis import classify_hypotheses_node
from core.investigation.loop import investigate_node
from core.verification.loop import verify_findings_node
from core.verification.execute import execute_tests_node
from core.change_units import change_units_node
from core.pr_understanding import pr_understanding_agent
from core.pr_analysis import pr_analysis_agent
from core.review_intelligence.planner import review_planner_agent


def build_review_graph():
    workflow = StateGraph(ReviewState)

    workflow.add_node("change_units", change_units_node)
    workflow.add_node("pr_understanding", pr_understanding_agent)
    workflow.add_node("pr_analysis", pr_analysis_agent)
    workflow.add_node("review_planner", review_planner_agent)
    workflow.add_node("build_evidence_package", build_evidence_package)
    workflow.add_node("context_summarizer", context_summarizer)
    workflow.add_node("context_gatherer", context_gatherer)
    workflow.add_node("correctness_agent", correctness_agent)
    workflow.add_node("code_quality_agent", code_quality_agent)
    workflow.add_node("testing_agent", testing_agent)
    workflow.add_node("classify_hypotheses", classify_hypotheses_node)
    workflow.add_node("investigate", investigate_node)
    workflow.add_node("validate_findings", validate_findings_node)
    workflow.add_node("verify_findings", verify_findings_node)
    workflow.add_node("execute_tests", execute_tests_node)
    workflow.add_node("critic_agent", critic_agent)
    workflow.add_node("final_recommender", final_recommender)

    workflow.set_entry_point("change_units")

    workflow.add_edge("change_units", "pr_understanding")
    workflow.add_edge("pr_understanding", "pr_analysis")
    workflow.add_edge("pr_analysis", "review_planner")
    workflow.add_edge("review_planner", "build_evidence_package")
    workflow.add_edge("build_evidence_package", "context_summarizer")

    # Parallel specialists (+ gatherer)
    workflow.add_edge("context_summarizer", "context_gatherer")
    workflow.add_edge("context_summarizer", "correctness_agent")
    workflow.add_edge("context_summarizer", "code_quality_agent")
    workflow.add_edge("context_summarizer", "testing_agent")

    workflow.add_edge("context_gatherer", "classify_hypotheses")
    workflow.add_edge("correctness_agent", "classify_hypotheses")
    workflow.add_edge("code_quality_agent", "classify_hypotheses")
    workflow.add_edge("testing_agent", "classify_hypotheses")

    workflow.add_edge("classify_hypotheses", "investigate")
    workflow.add_edge("investigate", "validate_findings")
    workflow.add_edge("validate_findings", "verify_findings")
    workflow.add_edge("verify_findings", "execute_tests")
    workflow.add_edge("execute_tests", "critic_agent")
    workflow.add_edge("critic_agent", "final_recommender")
    workflow.add_edge("final_recommender", END)

    return workflow.compile()


review_graph = build_review_graph()