from langgraph.graph import StateGraph, END
from core.state import ReviewState
from core.agents import (
    context_summarizer,
    context_gatherer,
    code_quality_reviewer,
    critic_agent,
    final_recommender
)

def build_review_graph():
    workflow = StateGraph(ReviewState)

    workflow.add_node("context_summarizer", context_summarizer)
    workflow.add_node("context_gatherer", context_gatherer)
    workflow.add_node("code_quality_reviewer", code_quality_reviewer)
    workflow.add_node("critic_agent", critic_agent)
    workflow.add_node("final_recommender", final_recommender)

    workflow.set_entry_point("context_summarizer")

    workflow.add_edge("context_summarizer", "context_gatherer")
    workflow.add_edge("context_summarizer", "code_quality_reviewer")

    workflow.add_edge("context_gatherer", "critic_agent")
    workflow.add_edge("code_quality_reviewer", "critic_agent")

    workflow.add_edge("critic_agent", "final_recommender")
    workflow.add_edge("final_recommender", END)

    return workflow.compile()


review_graph = build_review_graph()