from langgraph.graph import StateGraph, END
from core.state import ReviewState

# New agents for Review Intelligence
from core.pr_understanding import pr_understanding_agent
from core.pr_analysis import pr_analysis_agent
from core.agents import build_evidence_package
from core.agents import correctness_agent
from core.agents import code_quality_agent

from core.agents import (
    context_summarizer,
    context_gatherer,
    code_quality_reviewer,
    critic_agent,
    final_recommender
)


def build_review_graph():
    workflow = StateGraph(ReviewState)

    # Nodes
    workflow.add_node("pr_understanding", pr_understanding_agent)
    workflow.add_node("pr_analysis", pr_analysis_agent)
    workflow.add_node("build_evidence_package", build_evidence_package)
    workflow.add_node("context_summarizer", context_summarizer)
    workflow.add_node("context_gatherer", context_gatherer)
    workflow.add_node("code_quality_reviewer", code_quality_reviewer)
    workflow.add_node("correctness_agent", correctness_agent)
    workflow.add_node("code_quality_agent", code_quality_agent)
    workflow.add_node("critic_agent", critic_agent)
    workflow.add_node("final_recommender", final_recommender)

    # Entry point
    workflow.set_entry_point("pr_understanding")

    # Flow
    workflow.add_edge("pr_understanding", "pr_analysis")
    workflow.add_edge("pr_analysis", "build_evidence_package")
    workflow.add_edge("build_evidence_package", "context_summarizer")

    workflow.add_edge("context_summarizer", "context_gatherer")
    workflow.add_edge("context_summarizer", "code_quality_reviewer")
    workflow.add_edge("context_summarizer", "correctness_agent")
    workflow.add_edge("context_summarizer", "code_quality_agent")

    workflow.add_edge("context_gatherer", "critic_agent")
    workflow.add_edge("code_quality_reviewer", "critic_agent")
    workflow.add_edge("correctness_agent", "critic_agent")
    workflow.add_edge("code_quality_agent", "critic_agent")

    workflow.add_edge("critic_agent", "final_recommender")
    workflow.add_edge("final_recommender", END)

    return workflow.compile()


review_graph = build_review_graph()