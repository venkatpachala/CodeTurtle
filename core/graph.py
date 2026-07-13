from langgraph.graph import StateGraph, END
from core.state import ReviewState
from core.agents import (
    context_gatherer,
    context_summarizer,
    code_quality_reviewer,
    critic_agent,
    final_recommender
)
from core.observability import get_langfuse_handler

def build_review_graph():
    workflow = StateGraph(ReviewState)

    workflow.add_node("context_gatherer", context_gatherer)
    workflow.add_node("code_quality_reviewer", code_quality_reviewer)
    workflow.add_node("critic_agent", critic_agent)
    workflow.add_node("final_recommender", final_recommender)

    workflow.add_node("context_summarizer",context_summarizer,)

    workflow.set_entry_point(
    "context_summarizer",)

    workflow.add_edge(
    "context_summarizer",
    "context_gatherer",
    )

    workflow.add_edge(
    "context_summarizer",
    "code_quality_reviewer",
    )

    workflow.add_edge(
    ["context_gatherer", "code_quality_reviewer"],
    "critic_agent",
    )

    workflow.add_edge(
    "critic_agent",
    "final_recommender",
    )

    workflow.add_edge(
    "final_recommender",
    END,
    )
    workflow.add_edge("critic_agent", "final_recommender")
    workflow.add_edge("final_recommender", END)

    graph = workflow.compile()

    # Attach Langfuse handler if available
    langfuse_handler = get_langfuse_handler()
    if langfuse_handler:
        graph = graph.with_config(callbacks=[langfuse_handler])

    return graph


review_graph = build_review_graph()
